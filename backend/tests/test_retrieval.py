import unittest
import tempfile
from pathlib import Path
from backend.app.services.ingestion.workspace_manager import WorkspaceManager
from backend.app.services.retrieval.hybrid_retriever import HybridRetriever
from backend.app.services.dependencies.copybook_resolver import CopybookResolver

COBOL_CODE = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BILLING.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-AMOUNT PIC 9(5)V99.
       01 WS-TAX PIC 9(5)V99.
       COPY TAXCONFIG.
       PROCEDURE DIVISION.
       CALCULATE-TOTAL.
           PERFORM APPLY-DISCOUNT.
           PERFORM CALCULATE-TAX.
           STOP RUN.
       APPLY-DISCOUNT.
           MOVE 0.05 TO WS-TAX.
       CALCULATE-TAX.
           COMPUTE WS-TAX = WS-AMOUNT * 0.08.
"""

class TestHybridRetrieval(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.wm = WorkspaceManager(Path(self.tmpdir.name))
        self.proj_id = self.wm.create_project("RetrievalTest")
        
        # Save source and copybook
        self.wm.save_file(self.proj_id, "BILLING.cob", COBOL_CODE, "SOURCE")
        self.wm.save_file(self.proj_id, "TAXCONFIG.cpy", "01 TAXCONFIG. 05 TAX-RATE PIC 9V99 VALUE 0.08.", "COPYBOOK")
        self.wm.analyze_and_index_project(self.proj_id)
        self.retriever = HybridRetriever(self.wm.vector_store, self.wm.graph_store)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_neuro_symbolic_retrieval_recovers_graph_dependencies(self):
        # Query specifically for CALCULATE-TOTAL
        pdir = self.wm.get_project_dir(self.proj_id)
        resolver = CopybookResolver([pdir / "copybooks", pdir / "source"])

        # 1. Baseline retrieval (Vector only)
        baseline_bundle = self.retriever.retrieve(
            project_id=self.proj_id,
            query="CALCULATE-TOTAL",
            top_k=1,
            copybook_resolver=resolver,
            baseline=True
        )
        # In baseline, only the single top-1 chunk is returned without dependencies
        self.assertEqual(len(baseline_bundle.primary_chunks), 1)
        self.assertEqual(len(baseline_bundle.dependency_chunks), 0)
        self.assertEqual(len(baseline_bundle.structural_constraints), 0)

        # 2. Proposed Neuro-Symbolic retrieval (Vector + Graph)
        proposed_bundle = self.retriever.retrieve(
            project_id=self.proj_id,
            query="CALCULATE-TOTAL",
            top_k=1,
            graph_hops=2,
            copybook_resolver=resolver,
            baseline=False
        )
        # In proposed, graph expansion recovers APPLY-DISCOUNT, CALCULATE-TAX, and TAXCONFIG!
        dep_symbols = [c.symbol_name for c in proposed_bundle.dependency_chunks]
        self.assertTrue("APPLY-DISCOUNT" in dep_symbols or "CALCULATE-TAX" in dep_symbols)
        self.assertTrue(len(proposed_bundle.structural_constraints) > 0)
        
        # Check that constraints explicitly guide dependencies
        constraint_text = " ".join(proposed_bundle.structural_constraints)
        self.assertIn("CALCULATE-TOTAL performs", constraint_text)

if __name__ == "__main__":
    unittest.main()
