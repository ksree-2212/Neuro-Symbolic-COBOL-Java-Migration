import unittest
from backend.app.services.parsing.cobol_lexer import CobolLexer
from backend.app.services.parsing.cobol_parser import CobolParser
from backend.app.services.parsing.cobol_adapter import CobolASTAdapter, CobolSymbolExtractor

COBOL_SAMPLE = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-PROG.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-AMOUNT    PIC 9(5)V99 VALUE 150.00.
       01 WS-TAX       PIC 9(5)V99.
       01 WS-TOTAL     PIC 9(5)V99.

       COPY TAXCONFIG.

       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-CALC.
           STOP RUN.

       1000-CALC.
           MOVE 0.08 TO WS-TAX.
           COMPUTE WS-TOTAL = WS-AMOUNT + (WS-AMOUNT * WS-TAX).
           CALL 'LOGGER-PROG' USING WS-TOTAL.
"""

class TestCobolParser(unittest.TestCase):
    def test_lexer_tokenization(self):
        tokens = CobolLexer.tokenize(COBOL_SAMPLE)
        self.assertTrue(len(tokens) > 20)
        words = [t.value for t in tokens if t.type == 'WORD']
        self.assertIn("IDENTIFICATION", words)
        self.assertIn("PROGRAM-ID", words)
        self.assertIn("TEST-PROG", words)
        self.assertIn("PERFORM", words)
        self.assertIn("COMPUTE", words)

    def test_ast_parsing_divisions(self):
        parser = CobolParser(COBOL_SAMPLE)
        program = parser.parse()
        self.assertEqual(program.program_id, "TEST-PROG")
        self.assertIn("IDENTIFICATION", program.divisions)
        self.assertIn("DATA", program.divisions)
        self.assertIn("PROCEDURE", program.divisions)

    def test_data_items_extraction(self):
        adapter = CobolASTAdapter.from_source(COBOL_SAMPLE)
        items = adapter.get_data_items()
        item_names = [i.name for i in items]
        self.assertIn("WS-AMOUNT", item_names)
        self.assertIn("WS-TAX", item_names)
        self.assertIn("WS-TOTAL", item_names)

    def test_paragraphs_and_statements(self):
        adapter = CobolASTAdapter.from_source(COBOL_SAMPLE)
        paras = adapter.get_paragraphs()
        para_names = [p.name for p in paras]
        self.assertIn("0000-MAIN", para_names)
        self.assertIn("1000-CALC", para_names)

        calc_para = next(p for p in paras if p.name == "1000-CALC")
        verbs = [s.verb for s in calc_para.statements]
        self.assertIn("MOVE", verbs)
        self.assertIn("COMPUTE", verbs)
        self.assertIn("CALL", verbs)

    def test_symbol_extractor(self):
        adapter = CobolASTAdapter.from_source(COBOL_SAMPLE)
        extractor = CobolSymbolExtractor(adapter)
        symbols = extractor.extract_symbols()
        self.assertEqual(symbols["program"][0]["name"], "TEST-PROG")
        self.assertTrue(len(symbols["paragraphs"]) >= 2)
        self.assertIn("TAXCONFIG", symbols["copybooks"])
        self.assertIn("LOGGER-PROG", symbols["external_calls"])

if __name__ == "__main__":
    unittest.main()
