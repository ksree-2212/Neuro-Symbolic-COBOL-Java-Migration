import unittest
import tempfile
from pathlib import Path
from backend.app.services.execution.cobol_runtime import CobolRuntimeEngine
from backend.app.services.compilation.java_builder import JavaProjectBuilder
from backend.app.services.compilation.java_compiler import JavaCompiler
from backend.app.schemas.migration import GeneratedFile

COBOL_PROGRAM = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(5)V99 VALUE 100.00.
       01 WS-B PIC 9(5)V99 VALUE 20.00.
       01 WS-C PIC 9(5)V99 VALUE 0.00.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-CALC.
           STOP RUN.
       1000-CALC.
           COMPUTE WS-C = WS-A - WS-B.
"""

class TestExecutionAndCompilation(unittest.TestCase):
    def test_cobol_runtime_arithmetic(self):
        engine = CobolRuntimeEngine(COBOL_PROGRAM)
        out = engine.execute({"WS-A": 200.00, "WS-B": 50.00})
        self.assertEqual(out["status"], "OK")
        self.assertEqual(out["WS-C"], 150.00)

    def test_java_compilation_and_builder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdir = Path(tmpdir)
            java_code = """package com.migration;
public class TestApp {
    public static void main(String[] args) {
        System.out.println("Execution valid");
    }
}
"""
            files = [GeneratedFile(path="TestApp.java", content=java_code)]
            JavaProjectBuilder.assemble_project(pdir, files, "TestApp")
            entry_file = pdir / "src" / "main" / "java" / "com" / "migration" / "TestApp.java"

            compiler = JavaCompiler()
            res = compiler.compile(pdir, entry_file)
            from backend.app.services.compilation.toolchain import JavaToolchainDetector
            if JavaToolchainDetector.is_available():
                self.assertTrue(res.success, f"Compilation failed: {res.errors}")
            else:
                self.assertFalse(res.success)
                self.assertEqual(res.error_type, "TOOLCHAIN_UNAVAILABLE")

    def test_java_compilation_failure_detection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdir = Path(tmpdir)
            bad_java = """package com.migration;
public class BadApp {
    public static void main(String[] args) {
        int x = "incompatible";
    }
}
"""
            files = [GeneratedFile(path="BadApp.java", content=bad_java)]
            JavaProjectBuilder.assemble_project(pdir, files, "BadApp")
            entry_file = pdir / "src" / "main" / "java" / "com" / "migration" / "BadApp.java"

            compiler = JavaCompiler()
            res = compiler.compile(pdir, entry_file)
            self.assertFalse(res.success)
            from backend.app.services.compilation.toolchain import JavaToolchainDetector
            if JavaToolchainDetector.is_available():
                self.assertEqual(res.error_type, "TYPE_ERROR")
            else:
                self.assertEqual(res.error_type, "TOOLCHAIN_UNAVAILABLE")

if __name__ == "__main__":
    unittest.main()
