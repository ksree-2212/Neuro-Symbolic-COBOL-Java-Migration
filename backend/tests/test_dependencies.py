import unittest
from pathlib import Path
import tempfile
from backend.app.services.parsing.cobol_adapter import CobolASTAdapter
from backend.app.services.dependencies.dependency_extractor import CobolDependencyExtractor
from backend.app.services.dependencies.copybook_resolver import CopybookResolver

COBOL_CODE = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DEP-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-RATE PIC 9V99 VALUE 0.05.
       01 WS-TOTAL PIC 9(5)V99.
       COPY CUSTDATA.
       PROCEDURE DIVISION.
       ENTRY-POINT.
           PERFORM STEP-A.
           STOP RUN.
       STEP-A.
           COMPUTE WS-TOTAL = 100 * WS-RATE.
           CALL 'EXT-AUDIT'.
"""

class TestDependencies(unittest.TestCase):
    def test_dependency_extraction(self):
        adapter = CobolASTAdapter.from_source(COBOL_CODE)
        extractor = CobolDependencyExtractor("proj_1", "file_1", adapter)
        gdata = extractor.extract_graph()

        edge_types = [e.type for e in gdata.edges]
        self.assertIn("CONTAINS", edge_types)
        self.assertIn("PERFORMS", edge_types)
        self.assertIn("CALLS", edge_types)
        self.assertIn("COPIES", edge_types)
        self.assertIn("DEFINES", edge_types)

        # Check specific edges
        performs_edge = next(e for e in gdata.edges if e.type == "PERFORMS")
        self.assertIn("ENTRY-POINT", performs_edge.source)
        self.assertIn("STEP-A", performs_edge.target)

        copies_edge = next(e for e in gdata.edges if e.type == "COPIES")
        self.assertIn("CUSTDATA", copies_edge.target)

    def test_copybook_resolver(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            cb_file = tmppath / "CUSTDATA.cpy"
            with open(cb_file, "w") as f:
                f.write("01 CUST-DATA. 05 CUST-NAME PIC X(20).")

            resolver = CopybookResolver([tmppath])
            res = resolver.resolve("CUSTDATA")
            self.assertIsNotNone(res)
            path, content = res
            self.assertIn("CUST-NAME", content)

            # Test unresolved tracking
            res_bad = resolver.resolve("UNKNOWN-CPY")
            self.assertIsNone(res_bad)
            self.assertIn("UNKNOWN-CPY", resolver.unresolved)

if __name__ == "__main__":
    unittest.main()
