import tempfile
import unittest
from pathlib import Path
from backend.app.services.parsing.cobol_parser import CobolParser
from backend.app.services.parsing.cobol_ast import DataItemNode
from backend.app.services.dependencies.copybook_resolver import CopybookResolver

class TestCobolParserExtended(unittest.TestCase):
    def test_level_88_condition_attached_to_parent(self):
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. COND-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STATUS PIC X(10) VALUE 'STANDARD'.
          88 IS-STANDARD VALUE 'STANDARD'.
          88 IS-VIP VALUE 'VIP'.
       PROCEDURE DIVISION.
       000-MAIN.
           STOP RUN.
"""
        parser = CobolParser(cobol)
        prog = parser.parse()
        data_div = prog.divisions["DATA"]
        self.assertEqual(len(data_div.data_items), 1)

        parent_item = data_div.data_items[0]
        self.assertEqual(parent_item.name, "WS-STATUS")
        self.assertEqual(len(parent_item.conditions), 2)
        cond_names = [c["name"] for c in parent_item.conditions]
        self.assertIn("IS-STANDARD", cond_names)
        self.assertIn("IS-VIP", cond_names)

    def test_hierarchical_record_nesting(self):
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. NEST-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CUSTOMER-REC.
          05 WS-CUST-ID   PIC 9(6).
          05 WS-CUST-NAME PIC X(30).
          05 WS-ADDRESS.
             10 WS-CITY   PIC X(20).
             10 WS-ZIP    PIC 9(5).
       PROCEDURE DIVISION.
       000-MAIN.
           STOP RUN.
"""
        parser = CobolParser(cobol)
        prog = parser.parse()
        data_div = prog.divisions["DATA"]
        items = data_div.data_items
        self.assertEqual(len(items), 6) # 01, 05, 05, 05, 10, 10

        root = items[0]
        self.assertEqual(root.name, "WS-CUSTOMER-REC")
        # Direct children of 01: WS-CUST-ID, WS-CUST-NAME, WS-ADDRESS
        child_names = [c.name for c in root.children]
        self.assertIn("WS-CUST-ID", child_names)
        self.assertIn("WS-CUST-NAME", child_names)
        self.assertIn("WS-ADDRESS", child_names)

    def test_signed_decimal_and_redefines(self):
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SIGN-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-BALANCE PIC S9(7)V99 VALUE -150.25.
       01 WS-RAW REDEFINES WS-BALANCE PIC X(9).
       PROCEDURE DIVISION.
       000-MAIN.
           STOP RUN.
"""
        parser = CobolParser(cobol)
        prog = parser.parse()
        data_div = prog.divisions["DATA"]
        self.assertEqual(len(data_div.data_items), 2)

        bal = data_div.data_items[0]
        self.assertEqual(bal.data_type, "DECIMAL")
        self.assertTrue(bal.details.get("signed"))

        redef = data_div.data_items[1]
        self.assertEqual(redef.redefines, "WS-BALANCE")

    def test_copybook_path_traversal_protection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            search_dir = Path(tmpdir) / "copybooks"
            search_dir.mkdir()
            # Create a legitimate copybook
            legit_file = search_dir / "VALID.cpy"
            legit_file.write_text("01 VALID-ITEM PIC X.", encoding="utf-8")

            resolver = CopybookResolver([search_dir])

            # Legitimate lookup
            found = resolver.resolve("VALID")
            self.assertIsNotNone(found)
            self.assertEqual(found[0].resolve(), legit_file.resolve())

            # Attempted directory traversal with ../
            traversal_attempt = "../secret.txt"
            blocked = resolver.resolve(traversal_attempt)
            self.assertIsNone(blocked)

if __name__ == "__main__":
    unittest.main()
