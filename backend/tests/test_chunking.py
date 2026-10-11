import unittest
from backend.app.services.chunking.structural_chunker import StructuralChunker

SAMPLE_COBOL = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDER-APP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-SUBTOTAL PIC 9(5)V99 VALUE 50.00.
       01 WS-DISCOUNT PIC 9(5)V99 VALUE 5.00.
       PROCEDURE DIVISION.
       PROCESS-ORDER.
           PERFORM CALC-DISCOUNT.
           STOP RUN.
       CALC-DISCOUNT.
           COMPUTE WS-SUBTOTAL = WS-SUBTOTAL - WS-DISCOUNT.
"""

class TestStructuralChunker(unittest.TestCase):
    def test_semantic_chunks_generation(self):
        chunker = StructuralChunker(project_id="test_proj", file_id="file_1", source_code=SAMPLE_COBOL)
        chunks = chunker.create_chunks()

        types = [c.symbol_type for c in chunks]
        self.assertIn("program", types)
        self.assertIn("data_item", types)
        self.assertIn("section", types)
        self.assertIn("paragraph", types)

    def test_shared_chunk_id_determinism(self):
        chunker1 = StructuralChunker(project_id="proj_A", file_id="f1", source_code=SAMPLE_COBOL)
        chunker2 = StructuralChunker(project_id="proj_A", file_id="f1", source_code=SAMPLE_COBOL)

        chunks1 = chunker1.create_chunks()
        chunks2 = chunker2.create_chunks()

        self.assertEqual(len(chunks1), len(chunks2))
        for c1, c2 in zip(chunks1, chunks2):
            self.assertEqual(c1.chunk_id, c2.chunk_id)
            self.assertTrue(c1.chunk_id.startswith("chk_"))

    def test_chunk_dependencies_metadata(self):
        chunker = StructuralChunker(project_id="proj_A", file_id="f1", source_code=SAMPLE_COBOL)
        chunks = chunker.create_chunks()

        proc_para = next(c for c in chunks if c.symbol_name == "PROCESS-ORDER")
        self.assertIn("CALC-DISCOUNT", proc_para.dependencies)

        calc_para = next(c for c in chunks if c.symbol_name == "CALC-DISCOUNT")
        self.assertIn("WS-SUBTOTAL", calc_para.variables_used)
        self.assertIn("WS-DISCOUNT", calc_para.variables_used)

if __name__ == "__main__":
    unittest.main()
