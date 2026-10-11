import asyncio
import io
import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.app.config import settings
from backend.app.db.database import get_connection, init_db
from backend.app.schemas.project import ProjectCreate, ProjectResponse, AnalysisSummary
from backend.app.schemas.migration import MigrationRequest, MigrationResponse, RetrievalInspection, GeneratedFile
from backend.app.schemas.ast_graph import GraphData, ASTNode
from backend.app.schemas.test_result import VerificationReport
from backend.app.services.ingestion.workspace_manager import WorkspaceManager
from backend.app.services.retrieval.hybrid_retriever import HybridRetriever, ContextBundle
from backend.app.services.generation.translation_service import TranslationService
from backend.app.services.generation.prompt_builder import TranslationPromptBuilder
from backend.app.services.verification.repair_loop import RepairLoopOrchestrator
from backend.app.services.dependencies.copybook_resolver import CopybookResolver
from backend.app.services.benchmark.benchmark_runner import BenchmarkRunner

app = FastAPI(
    title="AST-Guided Neuro-Symbolic RAG COBOL → Java Migration API",
    version="1.0.0",
    description="Dual Memory (Vector + Graph) AST-Guided COBOL to Java Migration with Cross-Language Differential Verification"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

workspace_mgr = WorkspaceManager()
retriever = HybridRetriever(workspace_mgr.vector_store, workspace_mgr.graph_store)
translator = TranslationService()
benchmark_runner = BenchmarkRunner(workspace_mgr)

# In-memory event stream subscribers for live pipeline progress
pipeline_subscribers: Dict[str, List[asyncio.Queue]] = {}

async def emit_pipeline_event(project_id: str, phase_number: int, phase_name: str, status: str, message: str, details: Optional[Dict[str, Any]] = None):
    data = {
        "phase_number": phase_number,
        "phase_name": phase_name,
        "status": status,
        "message": message,
        "details": details or {}
    }
    if project_id in pipeline_subscribers:
        for q in pipeline_subscribers[project_id]:
            await q.put(data)

# ----------------- PROJECTS & UPLOADS -----------------

@app.post("/api/projects", response_model=Dict[str, Any])
def create_project(req: ProjectCreate):
    pid = workspace_mgr.create_project(name=req.name, source_language=req.source_language, target_language=req.target_language)
    return {"project_id": pid, "name": req.name, "status": "CREATED"}

@app.get("/api/projects", response_model=List[Dict[str, Any]])
def list_projects():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM projects ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/projects/{project_id}", response_model=Dict[str, Any])
def get_project(project_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return dict(row)

@app.post("/api/projects/{project_id}/upload")
async def upload_files(
    project_id: str,
    files: List[UploadFile] = File(...),
    file_type: str = Form("SOURCE") # 'SOURCE' | 'COPYBOOK'
):
    saved_files = []
    for f in files:
        content_bytes = await f.read()
        try:
            content_str = content_bytes.decode("utf-8")
        except:
            content_str = content_bytes.decode("latin-1", errors="ignore")

        # Handle zip archive upload
        if f.filename.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(content_bytes)) as z:
                for zname in z.namelist():
                    if not zname.endswith("/") and not zname.startswith("__MACOSX"):
                        z_data = z.read(zname)
                        try:
                            z_str = z_data.decode("utf-8")
                        except:
                            z_str = z_data.decode("latin-1", errors="ignore")
                        z_type = "COPYBOOK" if zname.lower().endswith((".cpy", ".copy")) else "SOURCE"
                        fname = Path(zname).name
                        fid = workspace_mgr.save_file(project_id, fname, z_str, z_type)
                        saved_files.append({"file_id": fid, "file_name": fname, "file_type": z_type})
        else:
            actual_type = "COPYBOOK" if f.filename.lower().endswith((".cpy", ".copy")) or file_type == "COPYBOOK" else "SOURCE"
            fid = workspace_mgr.save_file(project_id, f.filename, content_str, actual_type)
            saved_files.append({"file_id": fid, "file_name": f.filename, "file_type": actual_type})

    return {"project_id": project_id, "files": saved_files, "count": len(saved_files)}

@app.get("/api/projects/{project_id}/files")
def get_project_files(project_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT file_id, project_id, file_name, file_path, file_type, line_count, created_at FROM files WHERE project_id = ?", (project_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/projects/{project_id}/files/{file_id}")
def get_file_content(project_id: str, file_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM files WHERE project_id = ? AND file_id = ?", (project_id, file_id))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="File not found")
    return dict(row)

# ----------------- ANALYSIS & INDEXING -----------------

@app.post("/api/projects/{project_id}/analyze")
async def analyze_project(project_id: str):
    await emit_pipeline_event(project_id, 1, "Parsing", "RUNNING", "Parsing COBOL source files...")
    await asyncio.sleep(0.05)
    await emit_pipeline_event(project_id, 2, "Structural Extraction", "RUNNING", "Extracting AST, Data Items, and Paragraphs...")
    await asyncio.sleep(0.05)
    await emit_pipeline_event(project_id, 3, "Vector Indexing", "RUNNING", "Generating dense semantic embeddings...")
    await asyncio.sleep(0.05)
    await emit_pipeline_event(project_id, 4, "Graph Indexing", "RUNNING", "Building dependency knowledge graph...")

    summary = workspace_mgr.analyze_and_index_project(project_id)

    await emit_pipeline_event(project_id, 1, "Parsing", "SUCCESS", f"Parsed {summary.files_detected} files, {summary.lines_of_code} LOC.")
    await emit_pipeline_event(project_id, 2, "Structural Extraction", "SUCCESS", f"Extracted {summary.programs} programs, {summary.sections} sections, {summary.paragraphs} paragraphs.")
    await emit_pipeline_event(project_id, 3, "Vector Indexing", "SUCCESS", "Semantic vector memory populated.")
    await emit_pipeline_event(project_id, 4, "Graph Indexing", "SUCCESS", f"Graph memory populated with {summary.dependencies_count} relationships.")

    return summary

@app.get("/api/projects/{project_id}/ast")
def get_project_ast(project_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT file_id, file_name, ast_json FROM files WHERE project_id = ? AND file_type = 'SOURCE'", (project_id,))
    rows = cursor.fetchall()
    conn.close()
    asts = []
    for r in rows:
        if r["ast_json"]:
            asts.append({
                "file_id": r["file_id"],
                "file_name": r["file_name"],
                "ast": json.loads(r["ast_json"])
            })
    return asts

@app.get("/api/projects/{project_id}/graph", response_model=GraphData)
def get_project_graph(project_id: str):
    return workspace_mgr.graph_store.get_project_graph(project_id)

# ----------------- RETRIEVAL & MIGRATION -----------------

@app.post("/api/projects/{project_id}/retrieve")
def retrieve_context(project_id: str, query: str = Query(...), top_k: int = 5, graph_hops: int = 2):
    pdir = workspace_mgr.get_project_dir(project_id)
    cb_resolver = CopybookResolver([pdir / "copybooks", pdir / "source"])
    bundle = retriever.retrieve(
        project_id=project_id,
        query=query,
        top_k=top_k,
        graph_hops=graph_hops,
        copybook_resolver=cb_resolver,
        baseline=False
    )
    return {
        "inspection": bundle.inspection,
        "primary_chunks": bundle.primary_chunks,
        "dependency_chunks": bundle.dependency_chunks,
        "copybooks": bundle.copybooks,
        "structural_constraints": bundle.structural_constraints
    }

@app.post("/api/projects/{project_id}/migrate", response_model=MigrationResponse)
async def migrate_code(project_id: str, req: MigrationRequest):
    import uuid
    import time
    t_start = time.time()
    migration_id = f"mig_{uuid.uuid4().hex[:10]}"
    pdir = workspace_mgr.get_project_dir(project_id)

    # 1. Retrieval
    await emit_pipeline_event(project_id, 5, "Retrieval", "RUNNING", f"Retrieving context for {req.target_name}...")
    cb_resolver = CopybookResolver([pdir / "copybooks", pdir / "source"])
    query_str = req.query or req.target_name
    bundle = retriever.retrieve(
        project_id=project_id,
        query=query_str,
        top_k=req.top_k,
        graph_hops=req.graph_hops,
        copybook_resolver=cb_resolver,
        baseline=req.baseline
    )
    await emit_pipeline_event(project_id, 5, "Retrieval", "SUCCESS", f"Found {len(bundle.primary_chunks)} primary chunks, {len(bundle.dependency_chunks)} graph dependencies.")

    # 2. Context Assembly
    await emit_pipeline_event(project_id, 6, "Context Assembly", "RUNNING", "Assembling prompt and structural constraints...")
    prompt = TranslationPromptBuilder.build_prompt(
        project_name=project_id,
        target_name=req.target_name,
        context=bundle,
        baseline=req.baseline
    )
    await emit_pipeline_event(project_id, 6, "Context Assembly", "SUCCESS", f"Context assembled with {len(bundle.structural_constraints)} constraints.")

    # 3. Java Generation
    await emit_pipeline_event(project_id, 7, "Java Generation", "RUNNING", "Generating target Java code...")
    trans_res = translator.translate(prompt)
    await emit_pipeline_event(project_id, 7, "Java Generation", "SUCCESS", f"Generated Java class {trans_res['entry_point']}.")

    # 4. Verification & Repair Loop
    await emit_pipeline_event(project_id, 8, "Compilation", "RUNNING", "Validating Java compilation...")
    await emit_pipeline_event(project_id, 9, "Differential Testing", "RUNNING", "Executing original COBOL vs Java on test suites...")

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT content FROM files WHERE project_id = ? AND file_type = 'SOURCE' LIMIT 1", (project_id,))
        row = cursor.fetchone()
        cobol_source = row["content"] if row else ""

        # Insert migration row before running repair loop to satisfy foreign key on attempts
        cursor.execute(
            """
            INSERT INTO migrations
            (migration_id, project_id, target_mode, target_name, query, status, retrieval_context, generated_code, final_status, total_attempts, metrics)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                migration_id, project_id, req.target_mode, req.target_name, req.query,
                "PROCESSING", json.dumps(bundle.inspection.model_dump() if hasattr(bundle.inspection, "model_dump") else bundle.inspection.dict()),
                trans_res["files"][0].content if trans_res["files"] else "",
                "PROCESSING", 0, "{}"
            )
        )
        conn.commit()
    finally:
        conn.close()

    repair_orchestrator = RepairLoopOrchestrator(
        project_id=project_id,
        migration_id=migration_id,
        workspace_dir=pdir,
        translation_service=translator,
        max_attempts=req.max_repair_attempts
    )

    verif_report: VerificationReport = repair_orchestrator.execute_verification_and_repair(
        target_name=req.target_name,
        context=bundle,
        initial_files=trans_res["files"],
        entry_point=trans_res["entry_point"],
        cobol_source=cobol_source,
        baseline=req.baseline
    )

    if verif_report.total_repair_attempts > 1:
        await emit_pipeline_event(project_id, 10, "Repair", "SUCCESS", f"Completed {verif_report.total_repair_attempts - 1} repair attempts.")

    if verif_report.final_status == "VERIFIED":
        final_msg = "Functional verification PASS (100% equivalence)."
        final_stat = "SUCCESS"
    elif verif_report.final_status == "UNVERIFIED_NO_JDK":
        final_msg = "Code generated. Java 17 toolchain is unavailable on host - compilation & differential testing skipped."
        final_stat = "WARNING"
    else:
        final_msg = "Verification FAILED."
        final_stat = "FAILED"
    await emit_pipeline_event(project_id, 11, "Final Verification", final_stat, final_msg)

    # Update Persisted Migration
    total_time = (time.time() - t_start) * 1000.0
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE migrations
            SET status = ?, generated_code = ?, final_status = ?, total_attempts = ?, metrics = ?
            WHERE migration_id = ?
            """,
            (
                verif_report.final_status,
                trans_res["files"][0].content if trans_res["files"] else "",
                verif_report.final_status,
                verif_report.total_repair_attempts,
                json.dumps({"total_time_ms": total_time, "equivalence_rate": verif_report.equivalence_rate}),
                migration_id
            )
        )
        conn.commit()
    finally:
        conn.close()

    return MigrationResponse(
        migration_id=migration_id,
        project_id=project_id,
        target_mode=req.target_mode,
        target_name=req.target_name,
        status=verif_report.final_status,
        retrieval=bundle.inspection,
        generated_files=trans_res["files"],
        compilation_passed=verif_report.compilation_passed,
        tests_total=verif_report.total_tests,
        tests_passed=verif_report.passed_tests,
        equivalence_rate=verif_report.equivalence_rate,
        repair_attempts=verif_report.total_repair_attempts,
        final_status=verif_report.final_status,
        metrics={"total_time_ms": round(total_time, 2)}
    )

@app.get("/api/migrations/{migration_id}/verification")
def get_migration_verification(migration_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM attempts WHERE migration_id = ? ORDER BY attempt_number ASC", (migration_id,))
    att_rows = cursor.fetchall()

    cursor.execute("SELECT * FROM migrations WHERE migration_id = ?", (migration_id,))
    mig_row = cursor.fetchone()
    conn.close()

    if not mig_row:
        raise HTTPException(status_code=404, detail="Migration not found")

    attempts = [dict(a) for a in att_rows]
    return {
        "migration_id": migration_id,
        "final_status": mig_row["final_status"],
        "total_attempts": mig_row["total_attempts"],
        "attempts": attempts
    }

# ----------------- BENCHMARK & EVALUATION -----------------

@app.post("/api/benchmark/run")
def run_benchmark_endpoint(project_id: str, target_name: str = "BILLING-MODULE", query: str = "billing calculation"):
    return benchmark_runner.run_benchmark(project_id, target_name, query)

@app.get("/api/capability-matrix")
def get_capability_matrix():
    return [
        {"feature": "IF / ELSE", "status": "SUPPORTED", "description": "Conditional branching, nested IFs, and condition evaluation"},
        {"feature": "MOVE", "status": "SUPPORTED", "description": "Data movement, literal transfers, field assignments"},
        {"feature": "COMPUTE", "status": "SUPPORTED", "description": "Arithmetic evaluation, ROUNDED clause, precision handling"},
        {"feature": "ADD / SUBTRACT", "status": "SUPPORTED", "description": "GIVING and accumulator arithmetic"},
        {"feature": "MULTIPLY / DIVIDE", "status": "SUPPORTED", "description": "Multiplication, division, and rounding rules"},
        {"feature": "PERFORM", "status": "SUPPORTED", "description": "Paragraph invocation, loops, and call stack preservation"},
        {"feature": "EVALUATE", "status": "SUPPORTED", "description": "Multi-way switch branching (WHEN clauses)"},
        {"feature": "COPYBOOK", "status": "SUPPORTED", "description": "External record layout and copybook resolution (.cpy, .cbl)"},
        {"feature": "CALL", "status": "SUPPORTED", "description": "External program calls with parameter binding (USING)"},
        {"feature": "FILE I/O", "status": "PARTIAL", "description": "Sequential read/write parsed, complex VSAM partial"},
        {"feature": "REDEFINES", "status": "PARTIAL", "description": "Union storage representation in Java"},
        {"feature": "OCCURS", "status": "PARTIAL", "description": "Array/table layout mapped to Java List/Array"},
        {"feature": "COMP-3", "status": "PARTIAL", "description": "Packed decimal mapped to BigDecimal"},
        {"feature": "EXEC SQL", "status": "UNSUPPORTED", "description": "Embedded SQL requires separate JDBC pre-compiler"},
        {"feature": "CICS", "status": "UNSUPPORTED", "description": "Online transaction monitor requires microservice wrapper"}
    ]

@app.get("/api/toolchain/status")
def get_toolchain_status(refresh: bool = True):
    from backend.app.services.compilation.toolchain import JavaToolchainDetector
    return JavaToolchainDetector.detect(refresh=refresh).to_dict()

# ----------------- EXPORT / DOWNLOAD -----------------

@app.get("/api/migrations/{migration_id}/export")
def export_migration(migration_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM migrations WHERE migration_id = ?", (migration_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Migration not found")

    project_id = row["project_id"]
    pdir = workspace_mgr.get_project_dir(project_id)
    attempt_dir = pdir / "generated" / f"attempt_{row['total_attempts']}"

    zip_path = pdir / f"migration_{migration_id}.zip"
    if attempt_dir.exists():
        shutil.make_archive(str(pdir / f"migration_{migration_id}"), 'zip', str(attempt_dir))
        return FileResponse(zip_path, filename=f"migration_{migration_id}.zip", media_type="application/zip")
    else:
        raise HTTPException(status_code=404, detail="Generated project files not found on disk")

# ----------------- SERVER SENT EVENTS FOR LIVE PIPELINE -----------------

@app.get("/api/projects/{project_id}/stream")
async def stream_pipeline(project_id: str):
    q = asyncio.Queue()
    pipeline_subscribers.setdefault(project_id, []).append(q)

    async def event_generator():
        try:
            while True:
                data = await q.get()
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            if project_id in pipeline_subscribers and q in pipeline_subscribers[project_id]:
                pipeline_subscribers[project_id].remove(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# Mount static files for frontend
frontend_dist = settings.base_dir / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
else:
    frontend_static = settings.base_dir / "frontend" / "static"
    if frontend_static.exists():
        app.mount("/", StaticFiles(directory=str(frontend_static), html=True), name="frontend")
