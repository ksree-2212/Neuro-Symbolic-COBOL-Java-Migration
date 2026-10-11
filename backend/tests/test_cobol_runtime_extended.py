import unittest
from backend.app.services.execution.cobol_runtime import CobolRuntimeEngine

class TestCobolRuntimeExtended(unittest.TestCase):
    def test_arithmetic_operations(self):
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH-EXT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(5)V99 VALUE 100.00.
       01 WS-B PIC 9(5)V99 VALUE 25.00.
       01 WS-ADD-RES PIC 9(5)V99 VALUE 0.00.
       01 WS-SUB-RES PIC 9(5)V99 VALUE 0.00.
       01 WS-MUL-RES PIC 9(5)V99 VALUE 0.00.
       01 WS-DIV-RES PIC 9(5)V99 VALUE 0.00.
       PROCEDURE DIVISION.
       000-MAIN.
           ADD WS-B TO WS-ADD-RES.
           SUBTRACT WS-B FROM WS-SUB-RES.
           MULTIPLY WS-B BY WS-MUL-RES.
           DIVIDE 2 INTO WS-DIV-RES.
           STOP RUN.
"""
        engine = CobolRuntimeEngine(cobol)
        res = engine.execute({"WS-A": 100.00, "WS-B": 25.00, "WS-ADD-RES": 50.00, "WS-SUB-RES": 50.00, "WS-MUL-RES": 2.00, "WS-DIV-RES": 10.00})
        self.assertEqual(res["status"], "OK")
        self.assertEqual(res["cobol_execution_mode"], "SIMULATED_PYTHON_EMULATOR")
        self.assertEqual(res["WS-ADD-RES"], 75.00)
        self.assertEqual(res["WS-SUB-RES"], 25.00)
        self.assertEqual(res["WS-MUL-RES"], 50.00)
        self.assertEqual(res["WS-DIV-RES"], 5.00)

    def test_conditional_branching_if(self):
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. IF-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-AMOUNT   PIC 9(5)V99 VALUE 150.00.
       01 WS-DISCOUNT PIC 9(5)V99 VALUE 0.00.
       PROCEDURE DIVISION.
       000-MAIN.
           IF WS-AMOUNT >= 100.00
               MOVE 10.00 TO WS-DISCOUNT.
           STOP RUN.
"""
        # When condition is TRUE (>= 100)
        engine = CobolRuntimeEngine(cobol)
        res_true = engine.execute({"WS-AMOUNT": 150.00})
        self.assertEqual(res_true["WS-DISCOUNT"], 10.00)

        # When condition is FALSE (< 100)
        res_false = engine.execute({"WS-AMOUNT": 50.00})
        self.assertEqual(res_false["WS-DISCOUNT"], 0.00)

    def test_negative_values_and_decimals(self):
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. NEG-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC S9(5)V99 VALUE 10.00.
       01 WS-Y PIC S9(5)V99 VALUE 30.00.
       01 WS-RES PIC S9(5)V99 VALUE 0.00.
       PROCEDURE DIVISION.
       000-MAIN.
           COMPUTE WS-RES = WS-X - WS-Y.
           STOP RUN.
"""
        engine = CobolRuntimeEngine(cobol)
        res = engine.execute({"WS-X": 10.00, "WS-Y": 30.00})
        self.assertEqual(res["status"], "OK")
        self.assertEqual(res["WS-RES"], -20.00)

    def test_simulation_disclosure_and_unsupported_statement(self):
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNK-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC X(10).
       PROCEDURE DIVISION.
       000-MAIN.
           DISPLAY 'HELLO'.
           STOP RUN.
"""
        engine = CobolRuntimeEngine(cobol)
        res = engine.execute({})
        self.assertIn("cobol_execution_mode", res)
        self.assertEqual(res["cobol_execution_mode"], "SIMULATED_PYTHON_EMULATOR")
        self.assertIn("unsupported_statements", res)

if __name__ == "__main__":
    unittest.main()
