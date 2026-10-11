import random
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from backend.app.schemas.test_result import TestCaseSchema, TestResultSchema
from backend.app.services.execution.cobol_runtime import CobolRuntimeEngine
from backend.app.services.execution.java_runner import JavaRunner
from backend.app.services.execution.normalizer import OutputNormalizer

class DifferentialTester:
    """
    Executes cross-language differential verification.
    Generates test suites (boundary, fuzz, symbolic adapter) and compares normalized runtime outputs.
    """
    def __init__(self, cobol_source: str, java_project_dir: Path, java_entry_class: str):
        self.cobol_engine = CobolRuntimeEngine(cobol_source)
        self.java_runner = JavaRunner()
        self.project_dir = java_project_dir
        self.entry_class = java_entry_class
        self.normalizer = OutputNormalizer()

    @staticmethod
    def generate_test_suite(module_name: str = "BILLING-MODULE") -> List[TestCaseSchema]:
        """
        Generates boundary and fuzz test cases according to Section 30.
        """
        cases: List[TestCaseSchema] = []
        is_payroll = "payroll" in module_name.lower() or "salary" in module_name.lower() or "employee" in module_name.lower()

        if is_payroll:
            # Payroll specific test cases
            cases.append(TestCaseSchema(test_id="TC_01_BASE_PAY", module_name=module_name, source_type="existing", input_data={"HOURLY-RATE": 25.0, "HOURS-WORKED": 40.0}))
            cases.append(TestCaseSchema(test_id="TC_02_OVERTIME_PAY", module_name=module_name, source_type="existing", input_data={"HOURLY-RATE": 30.0, "HOURS-WORKED": 45.0}))
            cases.append(TestCaseSchema(test_id="TC_03_ZERO_HOURS", module_name=module_name, source_type="boundary", input_data={"HOURLY-RATE": 20.0, "HOURS-WORKED": 0.0}))
            cases.append(TestCaseSchema(test_id="TC_04_MAX_HOURS", module_name=module_name, source_type="boundary", input_data={"HOURLY-RATE": 50.0, "HOURS-WORKED": 80.0}))
            cases.append(TestCaseSchema(test_id="TC_05_THRESHOLD_40", module_name=module_name, source_type="boundary", input_data={"HOURLY-RATE": 35.0, "HOURS-WORKED": 40.0}))
            cases.append(TestCaseSchema(test_id="TC_06_MIN_RATE", module_name=module_name, source_type="boundary", input_data={"HOURLY-RATE": 7.25, "HOURS-WORKED": 40.0}))
            cases.append(TestCaseSchema(test_id="TC_07_HIGH_RATE", module_name=module_name, source_type="boundary", input_data={"HOURLY-RATE": 250.0, "HOURS-WORKED": 40.0}))
            cases.append(TestCaseSchema(test_id="TC_08_FRACTIONAL_HOURS", module_name=module_name, source_type="boundary", input_data={"HOURLY-RATE": 40.0, "HOURS-WORKED": 37.5}))
            random.seed(42)
            for i in range(1, 11):
                cases.append(TestCaseSchema(test_id=f"TC_FUZZ_{i:02d}", module_name=module_name, source_type="fuzz", input_data={"HOURLY-RATE": round(random.uniform(15.0, 100.0), 2), "HOURS-WORKED": round(random.uniform(10.0, 60.0), 2)}))
            cases.append(TestCaseSchema(test_id="TC_SYM_01_EDGE", module_name=module_name, source_type="symbolic_planned", input_data={"HOURLY-RATE": 45.0, "HOURS-WORKED": 60.0}))
            cases.append(TestCaseSchema(test_id="TC_SYM_02_OVERTIME", module_name=module_name, source_type="symbolic_planned", input_data={"HOURLY-RATE": 35.0, "HOURS-WORKED": 50.0}))
            return cases

        # 1. Standard cases
        cases.append(TestCaseSchema(
            test_id="TC_01_STANDARD_BASE",
            module_name=module_name,
            source_type="existing",
            input_data={"GROSS-AMOUNT": 150.00, "CUSTOMER-STATUS": "STANDARD", "TAX-RATE": 0.08}
        ))
        cases.append(TestCaseSchema(
            test_id="TC_02_VIP_DISCOUNT",
            module_name=module_name,
            source_type="existing",
            input_data={"GROSS-AMOUNT": 200.00, "CUSTOMER-STATUS": "VIP", "TAX-RATE": 0.08}
        ))

        # 2. Boundary cases
        cases.append(TestCaseSchema(
            test_id="TC_03_ZERO_AMOUNT",
            module_name=module_name,
            source_type="boundary",
            input_data={"GROSS-AMOUNT": 0.00, "CUSTOMER-STATUS": "STANDARD", "TAX-RATE": 0.08}
        ))
        cases.append(TestCaseSchema(
            test_id="TC_04_DISCOUNT_THRESHOLD_BELOW",
            module_name=module_name,
            source_type="boundary",
            input_data={"GROSS-AMOUNT": 99.99, "CUSTOMER-STATUS": "VIP", "TAX-RATE": 0.08}
        ))
        cases.append(TestCaseSchema(
            test_id="TC_05_DISCOUNT_THRESHOLD_EXACT",
            module_name=module_name,
            source_type="boundary",
            input_data={"GROSS-AMOUNT": 100.00, "CUSTOMER-STATUS": "VIP", "TAX-RATE": 0.08}
        ))
        cases.append(TestCaseSchema(
            test_id="TC_06_LARGE_AMOUNT",
            module_name=module_name,
            source_type="boundary",
            input_data={"GROSS-AMOUNT": 99999.99, "CUSTOMER-STATUS": "VIP", "TAX-RATE": 0.08}
        ))
        cases.append(TestCaseSchema(
            test_id="TC_07_ZERO_TAX",
            module_name=module_name,
            source_type="boundary",
            input_data={"GROSS-AMOUNT": 250.00, "CUSTOMER-STATUS": "STANDARD", "TAX-RATE": 0.00}
        ))
        cases.append(TestCaseSchema(
            test_id="TC_08_HIGH_TAX_BOUNDARY",
            module_name=module_name,
            source_type="boundary",
            input_data={"GROSS-AMOUNT": 100.00, "CUSTOMER-STATUS": "STANDARD", "TAX-RATE": 0.25}
        ))

        # 3. Property / Fuzz testing cases
        random.seed(42)
        for i in range(1, 11):
            rnd_amt = round(random.uniform(10.0, 5000.0), 2)
            rnd_status = "VIP" if i % 2 == 0 else "STANDARD"
            cases.append(TestCaseSchema(
                test_id=f"TC_FUZZ_{i:02d}",
                module_name=module_name,
                source_type="fuzz",
                input_data={"GROSS-AMOUNT": rnd_amt, "CUSTOMER-STATUS": rnd_status, "TAX-RATE": 0.08}
            ))

        # 4. Symbolic / Path-based adapter cases
        cases.append(TestCaseSchema(
            test_id="TC_SYM_01_EDGE_PATH",
            module_name=module_name,
            source_type="symbolic_planned",
            input_data={"GROSS-AMOUNT": 1000.00, "CUSTOMER-STATUS": "UNKNOWN", "TAX-RATE": 0.05}
        ))
        cases.append(TestCaseSchema(
            test_id="TC_SYM_02_BOUNDARY_PATH",
            module_name=module_name,
            source_type="symbolic_planned",
            input_data={"GROSS-AMOUNT": 500.00, "CUSTOMER-STATUS": "VIP", "TAX-RATE": 0.10}
        ))

        return cases

    def run_suite(self, test_cases: List[TestCaseSchema]) -> List[TestResultSchema]:
        results: List[TestResultSchema] = []

        for tc in test_cases:
            t_start = time.time()
            cobol_out = self.cobol_engine.execute(tc.input_data)
            java_out = self.java_runner.execute(self.project_dir, self.entry_class, tc.input_data)
            t_elapsed_ms = (time.time() - t_start) * 1000.0

            if java_out.get("status") == "ERROR":
                results.append(TestResultSchema(
                    test_id=tc.test_id,
                    input_data=tc.input_data,
                    cobol_output=cobol_out,
                    java_output=java_out,
                    status="FAIL",
                    difference=f"Runtime error in Java: {java_out.get('error_type')} - {java_out.get('message', java_out.get('stderr', ''))}",
                    execution_time_ms=t_elapsed_ms,
                    failure_category=java_out.get("error_type", "RUNTIME_ERROR")
                ))
                continue

            is_equal, diff_msg = self.normalizer.compare_values(cobol_out, java_out)

            if is_equal:
                results.append(TestResultSchema(
                    test_id=tc.test_id,
                    input_data=tc.input_data,
                    cobol_output=cobol_out,
                    java_output=java_out,
                    status="PASS",
                    difference=None,
                    execution_time_ms=t_elapsed_ms,
                    failure_category=None
                ))
            else:
                results.append(TestResultSchema(
                    test_id=tc.test_id,
                    input_data=tc.input_data,
                    cobol_output=cobol_out,
                    java_output=java_out,
                    status="FAIL",
                    difference=diff_msg,
                    execution_time_ms=t_elapsed_ms,
                    failure_category="OUTPUT_MISMATCH"
                ))

        return results
