import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from backend.app.schemas.migration import GeneratedFile
from backend.app.schemas.test_result import (
    TestCaseSchema, TestResultSchema, RepairAttemptSchema, VerificationReport
)
from backend.app.services.compilation.java_builder import JavaProjectBuilder
from backend.app.services.compilation.java_compiler import JavaCompiler, CompileResult
from backend.app.services.verification.differential_tester import DifferentialTester
from backend.app.services.verification.failure_analyzer import FailureAnalyzer
from backend.app.services.generation.translation_service import TranslationService
from backend.app.services.generation.prompt_builder import TranslationPromptBuilder
from backend.app.services.retrieval.hybrid_retriever import ContextBundle
from backend.app.db.database import get_connection

logger = logging.getLogger(__name__)

class RepairLoopOrchestrator:
    """
    Coordinates compilation, differential testing, failure diagnosis,
    and iterative targeted LLM repair with full regression testing.
    """
    def __init__(
        self,
        project_id: str,
        migration_id: str,
        workspace_dir: Path,
        translation_service: TranslationService,
        max_attempts: int = 3
    ):
        self.project_id = project_id
        self.migration_id = migration_id
        self.workspace_dir = workspace_dir
        self.translation_service = translation_service
        self.max_attempts = max_attempts
        self.compiler = JavaCompiler()

    def execute_verification_and_repair(
        self,
        target_name: str,
        context: ContextBundle,
        initial_files: List[GeneratedFile],
        entry_point: str,
        cobol_source: str,
        baseline: bool = False
    ) -> VerificationReport:
        attempts_history: List[RepairAttemptSchema] = []
        current_files = initial_files
        final_status = "FAILED"
        compilation_passed = False
        last_test_results: List[TestResultSchema] = []

        # Generate test suite once for consistent evaluation across attempts
        test_cases = DifferentialTester.generate_test_suite(target_name)

        for attempt_no in range(1, self.max_attempts + 1):
            attempt_id = f"att_{self.migration_id}_{attempt_no}"
            attempt_dir = self.workspace_dir / "generated" / f"attempt_{attempt_no}"
            
            # Step A: Assemble Java Project
            JavaProjectBuilder.assemble_project(attempt_dir, current_files, entry_point)
            entry_file = attempt_dir / "src" / "main" / "java" / "com" / "migration" / f"{entry_point}.java"

            # Step B: Layer 1 - Compilation Check
            compile_res: CompileResult = self.compiler.compile(attempt_dir, entry_file)
            compilation_passed = compile_res.success

            if not compile_res.success:
                if compile_res.error_type == "TOOLCHAIN_UNAVAILABLE":
                    attempt_record = RepairAttemptSchema(
                        attempt_id=attempt_id,
                        attempt_number=attempt_no,
                        compile_status="SKIPPED",
                        compile_errors=compile_res.errors,
                        tests_passed=0,
                        tests_total=len(test_cases),
                        status="TOOLCHAIN_UNAVAILABLE",
                        failure_category="TOOLCHAIN_UNAVAILABLE",
                        diagnosis=compile_res.errors,
                        generated_code=current_files[0].content if current_files else "",
                        test_results=[]
                    )
                    attempts_history.append(attempt_record)
                    self._persist_attempt(attempt_record)
                    final_status = "UNVERIFIED_NO_JDK"
                    break

                diag = FailureAnalyzer.diagnose_compile_failure(compile_res.errors)
                attempt_record = RepairAttemptSchema(
                    attempt_id=attempt_id,
                    attempt_number=attempt_no,
                    compile_status="FAIL",
                    compile_errors=compile_res.errors,
                    tests_passed=0,
                    tests_total=len(test_cases),
                    status="FAILED",
                    failure_category=diag["category"],
                    diagnosis=diag["diagnosis"],
                    generated_code=current_files[0].content if current_files else "",
                    test_results=[]
                )
                attempts_history.append(attempt_record)
                self._persist_attempt(attempt_record)

                if attempt_no < self.max_attempts:
                    logger.info(f"Attempt #{attempt_no} failed compilation. Initiating repair...")
                    repair_ctx = {
                        "attempt_number": attempt_no,
                        "compile_errors": compile_res.errors,
                        "failing_tests": []
                    }
                    repair_prompt = TranslationPromptBuilder.build_prompt(
                        project_name=self.project_id,
                        target_name=target_name,
                        context=context,
                        repair_context=repair_ctx,
                        baseline=baseline
                    )
                    trans_res = self.translation_service.translate(repair_prompt)
                    current_files = trans_res["files"]
                    continue
                else:
                    final_status = "VERIFICATION FAILED"
                    break

            # Step C: Layer 2 - Differential Functional Testing
            tester = DifferentialTester(cobol_source, attempt_dir, entry_point)
            test_results = tester.run_suite(test_cases)
            last_test_results = test_results

            passed_count = sum(1 for tr in test_results if tr.status == "PASS")
            failing_results = [tr for tr in test_results if tr.status != "PASS"]

            if not failing_results:
                # All tests passed! Fully verified!
                final_status = "VERIFIED"
                attempt_record = RepairAttemptSchema(
                    attempt_id=attempt_id,
                    attempt_number=attempt_no,
                    compile_status="PASS",
                    compile_errors=None,
                    tests_passed=passed_count,
                    tests_total=len(test_cases),
                    status="VERIFIED",
                    failure_category=None,
                    diagnosis="Functional equivalence verified on all boundary, fuzz, and standard cases.",
                    generated_code=current_files[0].content if current_files else "",
                    test_results=test_results
                )
                attempts_history.append(attempt_record)
                self._persist_attempt(attempt_record)
                break
            else:
                diag = FailureAnalyzer.diagnose_test_failures(failing_results)
                attempt_record = RepairAttemptSchema(
                    attempt_id=attempt_id,
                    attempt_number=attempt_no,
                    compile_status="PASS",
                    compile_errors=None,
                    tests_passed=passed_count,
                    tests_total=len(test_cases),
                    status="FAILED",
                    failure_category=diag["category"],
                    diagnosis=diag["diagnosis"],
                    generated_code=current_files[0].content if current_files else "",
                    test_results=test_results
                )
                attempts_history.append(attempt_record)
                self._persist_attempt(attempt_record)

                if attempt_no < self.max_attempts:
                    logger.info(f"Attempt #{attempt_no} failed functional tests ({passed_count}/{len(test_cases)} passed). Initiating repair...")
                    repair_ctx = {
                        "attempt_number": attempt_no,
                        "compile_errors": None,
                        "failing_tests": [
                            {"input": f.input_data, "expected": f.cobol_output, "actual": f.java_output}
                            for f in failing_results
                        ]
                    }
                    repair_prompt = TranslationPromptBuilder.build_prompt(
                        project_name=self.project_id,
                        target_name=target_name,
                        context=context,
                        repair_context=repair_ctx,
                        baseline=baseline
                    )
                    trans_res = self.translation_service.translate(repair_prompt)
                    current_files = trans_res["files"]
                else:
                    final_status = "VERIFICATION FAILED"

        total_tests = len(test_cases)
        passed_tests = attempts_history[-1].tests_passed if attempts_history else 0
        eq_rate = (passed_tests / total_tests * 100.0) if total_tests > 0 else 0.0

        return VerificationReport(
            migration_id=self.migration_id,
            project_id=self.project_id,
            target_name=target_name,
            final_status=final_status,
            compilation_passed=compilation_passed,
            total_tests=total_tests,
            passed_tests=passed_tests,
            equivalence_rate=round(eq_rate, 2),
            total_repair_attempts=len(attempts_history),
            attempts_history=attempts_history,
            unsupported_constructs=[]
        )

    def _persist_attempt(self, attempt: RepairAttemptSchema):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO attempts
            (attempt_id, migration_id, attempt_number, generated_code, compile_status, compile_errors, tests_passed, tests_total, status, failure_category, diagnosis)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt.attempt_id,
                self.migration_id,
                attempt.attempt_number,
                attempt.generated_code,
                attempt.compile_status,
                attempt.compile_errors,
                attempt.tests_passed,
                attempt.tests_total,
                attempt.status,
                attempt.failure_category,
                attempt.diagnosis
            )
        )
        conn.commit()
        conn.close()
