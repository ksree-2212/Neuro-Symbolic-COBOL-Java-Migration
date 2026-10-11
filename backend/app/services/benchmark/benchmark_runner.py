import csv
import json
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from backend.app.schemas.migration import MigrationResponse
from backend.app.services.ingestion.workspace_manager import WorkspaceManager
from backend.app.services.retrieval.hybrid_retriever import HybridRetriever
from backend.app.services.generation.translation_service import TranslationService
from backend.app.services.generation.prompt_builder import TranslationPromptBuilder
from backend.app.services.verification.repair_loop import RepairLoopOrchestrator
from backend.app.services.dependencies.copybook_resolver import CopybookResolver
from backend.app.db.database import get_connection

class BenchmarkRunner:
    """
    Executes empirical comparative evaluation:
    Baseline (Fixed-size / Vector-only / Unconstrained)
      vs.
    Proposed (AST-guided / Vector + Graph Hybrid / Constrained / Verification / Repair).
    Records latency, compile rate, equivalence rate, and dependency failures.
    """
    def __init__(self, workspace_manager: WorkspaceManager):
        self.wm = workspace_manager
        self.retriever = HybridRetriever(self.wm.vector_store, self.wm.graph_store)
        self.translator = TranslationService()

    def _ensure_migration_record(self, migration_id: str, project_id: str, target_name: str, query: str):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO migrations
            (migration_id, project_id, target_mode, target_name, query, status, total_attempts)
            VALUES (?, ?, 'BENCHMARK', ?, ?, 'RUNNING', 1)
            """,
            (migration_id, project_id, target_name, query)
        )
        conn.commit()
        conn.close()

    def run_benchmark(self, project_id: str, target_name: str, query: str) -> Dict[str, Any]:
        pdir = self.wm.get_project_dir(project_id)
        cb_resolver = CopybookResolver([pdir / "copybooks", pdir / "source"])

        # Fetch COBOL source
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT content FROM files WHERE project_id = ? AND file_type = 'SOURCE' LIMIT 1", (project_id,))
        row = cursor.fetchone()
        conn.close()
        cobol_source = row["content"] if row else ""

        # ------------------ RUN BASELINE ------------------
        t_b_start = time.time()
        b_context = self.retriever.retrieve(
            project_id=project_id,
            query=query,
            top_k=5,
            copybook_resolver=cb_resolver,
            baseline=True
        )
        t_b_retrieval = (time.time() - t_b_start) * 1000.0

        t_b_gen_start = time.time()
        b_prompt = TranslationPromptBuilder.build_prompt(
            project_name=project_id,
            target_name=target_name,
            context=b_context,
            baseline=True
        )
        b_trans = self.translator.translate(b_prompt)
        t_b_generation = (time.time() - t_b_gen_start) * 1000.0

        b_migration_id = f"mig_base_{uuid.uuid4().hex[:8]}"
        self._ensure_migration_record(b_migration_id, project_id, target_name, query)

        b_repair = RepairLoopOrchestrator(
            project_id=project_id,
            migration_id=b_migration_id,
            workspace_dir=pdir,
            translation_service=self.translator,
            max_attempts=1
        )
        t_b_verif_start = time.time()
        b_report = b_repair.execute_verification_and_repair(
            target_name=target_name,
            context=b_context,
            initial_files=b_trans["files"],
            entry_point=b_trans["entry_point"],
            cobol_source=cobol_source,
            baseline=True
        )
        t_b_verification = (time.time() - t_b_verif_start) * 1000.0

        # ------------------ RUN PROPOSED ------------------
        t_p_start = time.time()
        p_context = self.retriever.retrieve(
            project_id=project_id,
            query=query,
            top_k=5,
            graph_hops=2,
            copybook_resolver=cb_resolver,
            baseline=False
        )
        t_p_retrieval = (time.time() - t_p_start) * 1000.0

        t_p_gen_start = time.time()
        p_prompt = TranslationPromptBuilder.build_prompt(
            project_name=project_id,
            target_name=target_name,
            context=p_context,
            baseline=False
        )
        p_trans = self.translator.translate(p_prompt)
        t_p_generation = (time.time() - t_p_gen_start) * 1000.0

        p_migration_id = f"mig_prop_{uuid.uuid4().hex[:8]}"
        self._ensure_migration_record(p_migration_id, project_id, target_name, query)

        p_repair = RepairLoopOrchestrator(
            project_id=project_id,
            migration_id=p_migration_id,
            workspace_dir=pdir,
            translation_service=self.translator,
            max_attempts=3
        )
        t_p_verif_start = time.time()
        p_report = p_repair.execute_verification_and_repair(
            target_name=target_name,
            context=p_context,
            initial_files=p_trans["files"],
            entry_point=p_trans["entry_point"],
            cobol_source=cobol_source,
            baseline=False
        )
        t_p_verification = (time.time() - t_p_verif_start) * 1000.0

        # Dependency failure metrics
        b_dep_failures = 1 if not b_context.copybooks else 0
        p_dep_failures = len(p_context.unresolved_dependencies)

        # Collect metrics dictionary
        results = {
            "baseline": {
                "system": "Baseline (Fixed / Vector-only / Unconstrained)",
                "compile_success": b_report.compilation_passed,
                "test_pass_rate": round(b_report.equivalence_rate, 2),
                "functional_equivalence": b_report.final_status == "VERIFIED",
                "dependency_failures": b_dep_failures,
                "copybook_failures": len(b_context.unresolved_dependencies),
                "retrieval_latency_ms": round(t_b_retrieval, 2),
                "generation_latency_ms": round(t_b_generation, 2),
                "verification_latency_ms": round(t_b_verification, 2),
                "repair_attempts": b_report.total_repair_attempts,
                "toolchain_status": "AVAILABLE" if b_report.compilation_passed else ("UNAVAILABLE" if b_report.final_status == "UNVERIFIED_NO_JDK" else "FAILED")
            },
            "proposed": {
                "system": "Proposed (AST-guided / Vector + Graph / Repair)",
                "compile_success": p_report.compilation_passed,
                "test_pass_rate": round(p_report.equivalence_rate, 2),
                "functional_equivalence": p_report.final_status == "VERIFIED",
                "dependency_failures": p_dep_failures,
                "copybook_failures": len(p_context.unresolved_dependencies),
                "retrieval_latency_ms": round(t_p_retrieval, 2),
                "generation_latency_ms": round(t_p_generation, 2),
                "verification_latency_ms": round(t_p_verification, 2),
                "repair_attempts": p_report.total_repair_attempts,
                "toolchain_status": "AVAILABLE" if p_report.compilation_passed else ("UNAVAILABLE" if p_report.final_status == "UNVERIFIED_NO_JDK" else "FAILED")
            }
        }

        # Export benchmark artifacts
        rep_dir = pdir / "reports"
        rep_dir.mkdir(parents=True, exist_ok=True)

        with open(rep_dir / "results.json", "w", encoding="utf-8") as jf:
            json.dump(results, jf, indent=2)

        with open(rep_dir / "results.csv", "w", newline="", encoding="utf-8") as cf:
            writer = csv.writer(cf)
            writer.writerow(["Metric", "Baseline", "Proposed"])
            writer.writerow(["Compile Success", results["baseline"]["compile_success"], results["proposed"]["compile_success"]])
            writer.writerow(["Test Pass Rate (%)", results["baseline"]["test_pass_rate"], results["proposed"]["test_pass_rate"]])
            writer.writerow(["Functional Equivalence", results["baseline"]["functional_equivalence"], results["proposed"]["functional_equivalence"]])
            writer.writerow(["Dependency Failures", results["baseline"]["dependency_failures"], results["proposed"]["dependency_failures"]])
            writer.writerow(["Retrieval Latency (ms)", results["baseline"]["retrieval_latency_ms"], results["proposed"]["retrieval_latency_ms"]])
            writer.writerow(["Generation Latency (ms)", results["baseline"]["generation_latency_ms"], results["proposed"]["generation_latency_ms"]])
            writer.writerow(["Verification Latency (ms)", results["baseline"]["verification_latency_ms"], results["proposed"]["verification_latency_ms"]])
            writer.writerow(["Repair Attempts", results["baseline"]["repair_attempts"], results["proposed"]["repair_attempts"]])

        html_content = f"""<!DOCTYPE html>
<html>
<head><title>COBOL to Java Migration Benchmark Report</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 40px; background: #f8fafc; color: #1e293b; }}
h1 {{ color: #0f172a; }}
table {{ border-collapse: collapse; width: 100%; max-width: 800px; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
th, td {{ padding: 14px 20px; text-align: left; border-bottom: 1px solid #e2e8f0; }}
th {{ background: #f1f5f9; font-weight: 600; }}
.pass {{ color: #16a34a; font-weight: 600; }}
.fail {{ color: #dc2626; font-weight: 600; }}
</style>
</head>
<body>
<h1>Evaluation: Baseline vs. Proposed Neuro-Symbolic RAG</h1>
<p>Project: <strong>{project_id}</strong> | Target: <strong>{target_name}</strong></p>
<table>
<tr><th>Evaluation Metric</th><th>Baseline (Vector Only)</th><th>Proposed (Neuro-Symbolic)</th></tr>
<tr><td>Compile Success</td><td>{results["baseline"]["compile_success"]}</td><td>{results["proposed"]["compile_success"]}</td></tr>
<tr><td>Test Pass Rate</td><td>{results["baseline"]["test_pass_rate"]}%</td><td>{results["proposed"]["test_pass_rate"]}%</td></tr>
<tr><td>Functional Equivalence</td><td class="{'pass' if results['baseline']['functional_equivalence'] else 'fail'}">{results['baseline']['functional_equivalence']}</td><td class="{'pass' if results['proposed']['functional_equivalence'] else 'fail'}">{results['proposed']['functional_equivalence']}</td></tr>
<tr><td>Dependency Failures</td><td>{results["baseline"]["dependency_failures"]}</td><td>{results["proposed"]["dependency_failures"]}</td></tr>
<tr><td>Retrieval Latency</td><td>{results["baseline"]["retrieval_latency_ms"]} ms</td><td>{results["proposed"]["retrieval_latency_ms"]} ms</td></tr>
<tr><td>Generation Latency</td><td>{results["baseline"]["generation_latency_ms"]} ms</td><td>{results["proposed"]["generation_latency_ms"]} ms</td></tr>
<tr><td>Verification Latency</td><td>{results["baseline"]["verification_latency_ms"]} ms</td><td>{results["proposed"]["verification_latency_ms"]} ms</td></tr>
<tr><td>Repair Attempts</td><td>{results["baseline"]["repair_attempts"]}</td><td>{results["proposed"]["repair_attempts"]}</td></tr>
</table>
</body>
</html>
"""
        with open(rep_dir / "report.html", "w", encoding="utf-8") as hf:
            hf.write(html_content)

        return results
