import unittest
import tempfile
from pathlib import Path
from backend.app.services.ingestion.workspace_manager import WorkspaceManager
from backend.app.services.benchmark.benchmark_runner import BenchmarkRunner

SAMPLE_BILLING = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BILLING-APP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VARS.
          05 WS-GROSS-AMOUNT PIC 9(5)V99 VALUE 100.00.
          05 WS-TAX-RATE     PIC 9V99 VALUE 0.08.
          05 WS-TAX-AMOUNT   PIC 9(5)V99 VALUE 0.00.
          05 WS-NET-TOTAL    PIC 9(5)V99 VALUE 0.00.
       COPY TAXCONFIG.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-PROCESS.
           STOP RUN.
       1000-PROCESS.
           COMPUTE WS-TAX-AMOUNT ROUNDED = WS-GROSS-AMOUNT * WS-TAX-RATE.
           COMPUTE WS-NET-TOTAL = WS-GROSS-AMOUNT + WS-TAX-AMOUNT.
"""

TAX_CONFIG_CPY = """
       01 TAX-CONFIG.
          05 DEFAULT-TAX-RATE PIC 9V99 VALUE 0.08.
"""

class TestBenchmarkAndEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.wm = WorkspaceManager(Path(self.tmpdir.name))
        self.proj_id = self.wm.create_project("E2E-Benchmark-Test")

        self.wm.save_file(self.proj_id, "BILLING.cob", SAMPLE_BILLING, "SOURCE")
        self.wm.save_file(self.proj_id, "TAXCONFIG.cpy", TAX_CONFIG_CPY, "COPYBOOK")
        self.summary = self.wm.analyze_and_index_project(self.proj_id)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_indexing_summary_metrics(self):
        self.assertEqual(self.summary.files_detected, 2)
        self.assertEqual(self.summary.copybooks_detected, 1)
        self.assertTrue(self.summary.paragraphs >= 2)
        self.assertTrue(self.summary.dependencies_count > 0)
        self.assertEqual(self.summary.index_status, "INDEXED")

    def test_benchmark_runner_execution(self):
        runner = BenchmarkRunner(self.wm)
        results = runner.run_benchmark(
            project_id=self.proj_id,
            target_name="BILLING-APP",
            query="billing and tax computation"
        )

        self.assertIn("baseline", results)
        self.assertIn("proposed", results)

        from backend.app.services.compilation.toolchain import JavaToolchainDetector
        if JavaToolchainDetector.is_available():
            self.assertTrue(results["baseline"]["compile_success"])
            self.assertTrue(results["proposed"]["functional_equivalence"])
        else:
            self.assertFalse(results["baseline"]["compile_success"])
            self.assertFalse(results["proposed"]["functional_equivalence"])
            self.assertEqual(results["proposed"].get("toolchain_status"), "UNAVAILABLE")

        # Check export files were created
        pdir = self.wm.get_project_dir(self.proj_id)
        self.assertTrue((pdir / "reports" / "results.json").exists())
        self.assertTrue((pdir / "reports" / "results.csv").exists())
        self.assertTrue((pdir / "reports" / "report.html").exists())

if __name__ == "__main__":
    unittest.main()
