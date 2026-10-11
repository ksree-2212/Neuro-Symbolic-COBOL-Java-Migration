import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Tuple
from backend.app.config import settings

class OutputNormalizer:
    """
    Normalizes outputs from diverse language runtimes (COBOL, Java)
    into canonical structured representations for differential verification.
    """
    def __init__(self, tolerance: float = None):
        self.tolerance = tolerance if tolerance is not None else settings.numeric_tolerance

    @staticmethod
    def _to_decimal(val: Any) -> Optional[Decimal]:
        if isinstance(val, (int, float)):
            return Decimal(str(val))
        if isinstance(val, str):
            clean = val.strip().replace("$", "").replace(",", "")
            try:
                return Decimal(clean)
            except InvalidOperation:
                return None
        return None

    @staticmethod
    def _normalize_key(key: str) -> str:
        k = re.sub(r'^(WS|LK|CUST)[-_]', '', key, flags=re.IGNORECASE)
        k = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', k)
        return k.lower().replace("-", "_").strip("_")

    def compare_values(self, expected: Any, actual: Any, policy: str = "NUMERIC_TOLERANCE") -> Tuple[bool, Optional[str]]:
        """
        Compares two values according to policy (EXACT, NUMERIC_TOLERANCE, NORMALIZED_STRING, STRUCTURED_JSON).
        Returns (is_equal, difference_description).
        """
        if expected is None and actual is None:
            return True, None

        if expected is None or actual is None:
            return False, f"Null mismatch: Expected {expected} vs Actual {actual}"

        # If comparing dictionaries / JSON structures
        if isinstance(expected, dict) and isinstance(actual, dict):
            # Check status equivalence first (Section 29)
            exp_status = expected.get("status")
            act_status = actual.get("status")
            if exp_status and act_status and exp_status != act_status:
                return False, f"Status divergence: Expected {exp_status} vs Actual {act_status}"

            norm_actual = {self._normalize_key(ak): (ak, av) for ak, av in actual.items()}
            
            for k, v in expected.items():
                norm_k = self._normalize_key(k)
                if norm_k in ("status", "execution_time_ms", "vars", "transaction_vars"):
                    continue

                # Skip group records with empty string value
                if v == "" or v is None:
                    continue

                # If key is present in actual output, verify numerical / string equivalence
                if norm_k in norm_actual:
                    _, actual_val = norm_actual[norm_k]
                    eq, diff = self.compare_values(v, actual_val, policy)
                    if not eq:
                        return False, f"Key '{k}' mismatch: {diff}"
                elif norm_k in ("net_total", "total", "net_pay", "gross_pay"):
                    return False, f"Missing critical metric '{k}' in actual output"

            return True, None

        # Numeric comparison
        exp_dec = self._to_decimal(expected)
        act_dec = self._to_decimal(actual)
        if exp_dec is not None and act_dec is not None:
            diff = abs(exp_dec - act_dec)
            if diff <= Decimal(str(self.tolerance)):
                return True, None
            return False, f"Numeric divergence: Expected {exp_dec} vs Actual {act_dec} (diff: {diff} > tol: {self.tolerance})"

        # String / Default comparison
        s_exp = str(expected).strip()
        s_act = str(actual).strip()
        if policy == "NORMALIZED_STRING":
            if s_exp.lower() == s_act.lower():
                return True, None
        else:
            if s_exp == s_act:
                return True, None

        return False, f"Value mismatch: Expected '{s_exp}' vs Actual '{s_act}'"
