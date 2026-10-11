import unittest
from backend.app.services.execution.normalizer import OutputNormalizer

class TestDifferentialVerification(unittest.TestCase):
    def setUp(self):
        self.normalizer = OutputNormalizer(tolerance=0.01)

    def test_numeric_tolerance_matching(self):
        # Within tolerance (0.01)
        eq1, diff1 = self.normalizer.compare_values(100.005, 100.009, policy="NUMERIC_TOLERANCE")
        self.assertTrue(eq1)

        # Exceeds tolerance
        eq2, diff2 = self.normalizer.compare_values(100.00, 100.05, policy="NUMERIC_TOLERANCE")
        self.assertFalse(eq2)
        self.assertIn("Numeric divergence", diff2)

    def test_structured_dict_normalization(self):
        cobol_out = {
            "status": "OK",
            "WS-NET-TOTAL": 108.00,
            "WS-DISCOUNT-AMOUNT": 0.00
        }
        java_out = {
            "status": "OK",
            "netTotal": 108.00,
            "discountAmount": 0.00
        }
        eq, diff = self.normalizer.compare_values(cobol_out, java_out)
        self.assertTrue(eq, f"Failed match: {diff}")

    def test_error_divergence_detection(self):
        cobol_out = {"status": "ERROR", "error_type": "INVALID_INPUT"}
        java_out = {"status": "OK", "netTotal": 0.00} # Silent return 0
        eq, diff = self.normalizer.compare_values(cobol_out, java_out)
        self.assertFalse(eq)

if __name__ == "__main__":
    unittest.main()
