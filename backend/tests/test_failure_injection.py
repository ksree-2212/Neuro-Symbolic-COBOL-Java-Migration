import unittest
import tempfile
from pathlib import Path
from backend.app.schemas.test_result import TestResultSchema
from backend.app.services.verification.failure_analyzer import FailureAnalyzer
from backend.app.services.compilation.java_builder import JavaProjectBuilder
from backend.app.services.compilation.java_compiler import JavaCompiler
from backend.app.services.execution.normalizer import OutputNormalizer
from backend.app.schemas.migration import GeneratedFile

class TestFailureInjection(unittest.TestCase):
    def test_case_1_missing_dependency_diagnosis(self):
        compile_err = "CustomerProcessor.java:42: error: cannot find symbol: variable TAX_RATE"
        diag = FailureAnalyzer.diagnose_compile_failure(compile_err)
        self.assertEqual(diag["category"], "MISSING_DEPENDENCY")
        self.assertIn("TAX_RATE", diag["diagnosis"])

    def test_case_2_compile_error_diagnosis(self):
        compile_err = "CustomerProcessor.java:18: error: ';' expected\n            int x = 10\n                      ^"
        diag = FailureAnalyzer.diagnose_compile_failure(compile_err)
        self.assertEqual(diag["category"], "SYNTAX_ERROR")

    def test_case_3_calculation_divergence_diagnosis(self):
        failing_res = [
            TestResultSchema(
                test_id="TC_01",
                input_data={"GROSS-AMOUNT": 100.00},
                cobol_output={"WS-NET-TOTAL": 97.20},
                java_output={"netTotal": 108.00}, # Missing discount
                status="FAIL",
                difference="Numeric divergence: Expected 97.20 vs Actual 108.00 (diff: 10.80)"
            )
        ]
        diag = FailureAnalyzer.diagnose_test_failures(failing_res)
        self.assertIn(diag["category"], ("OUTPUT_MISMATCH", "NUMERIC_PRECISION", "MISSING_DEPENDENCY"))
        self.assertIn("Numeric divergence", diag["sample_difference"])

    def test_case_4_unresolved_copybook_detection(self):
        from backend.app.services.dependencies.copybook_resolver import CopybookResolver
        with tempfile.TemporaryDirectory() as tmpdir:
            resolver = CopybookResolver([Path(tmpdir)])
            res = resolver.resolve("MISSING-TAX-CPY")
            self.assertIsNone(res)
            self.assertIn("MISSING-TAX-CPY", resolver.unresolved)

    def test_case_5_compilation_pass_but_functional_verification_fail(self):
        """
        Crucial research test (Section 57 Case 5):
        Java code compiles cleanly, but returns wrong numeric value.
        Must demonstrate why compilation is insufficient for migration correctness!
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            pdir = Path(tmpdir)
            # Java code that compiles cleanly
            buggy_java = """package com.migration;
import java.util.Map;
import java.util.HashMap;
import java.math.BigDecimal;

public class BuggyBilling {
    public Map<String, Object> execute(Map<String, Object> input) {
        Map<String, Object> res = new HashMap<>();
        res.put("status", "OK");
        // BUG: Always returns 0.00 instead of calculated total
        res.put("netTotal", BigDecimal.ZERO);
        return res;
    }
}
"""
            files = [GeneratedFile(path="BuggyBilling.java", content=buggy_java)]
            JavaProjectBuilder.assemble_project(pdir, files, "BuggyBilling")
            entry_file = pdir / "src" / "main" / "java" / "com" / "migration" / "BuggyBilling.java"

            # 1. Verify Compilation PASSES (when Java available) or reports TOOLCHAIN_UNAVAILABLE
            compiler = JavaCompiler()
            comp_res = compiler.compile(pdir, entry_file)
            from backend.app.services.compilation.toolchain import JavaToolchainDetector
            if JavaToolchainDetector.is_available():
                self.assertTrue(comp_res.success, "Compilation was expected to PASS")
            else:
                self.assertEqual(comp_res.error_type, "TOOLCHAIN_UNAVAILABLE")

            # 2. Verify Functional Equivalence FAILS
            normalizer = OutputNormalizer()
            expected_cobol_total = 108.00
            actual_java_total = 0.00 # from BuggyBilling
            is_equal, diff = normalizer.compare_values(expected_cobol_total, actual_java_total)

            self.assertFalse(is_equal, "Functional verification MUST fail when outputs diverge")
            self.assertIn("Numeric divergence", diff)

if __name__ == "__main__":
    unittest.main()
