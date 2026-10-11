from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

class TestCaseSchema(BaseModel):
    test_id: str
    module_name: str
    source_type: str # 'boundary' | 'fuzz' | 'existing' | 'symbolic_planned'
    input_data: Dict[str, Any]
    expected_output: Optional[Dict[str, Any]] = None

class TestResultSchema(BaseModel):
    test_id: str
    input_data: Dict[str, Any]
    cobol_output: Optional[Dict[str, Any]] = None
    java_output: Optional[Dict[str, Any]] = None
    status: str # 'PASS' | 'FAIL' | 'ERROR'
    difference: Optional[str] = None
    execution_time_ms: float = 0.0
    failure_category: Optional[str] = None

class RepairAttemptSchema(BaseModel):
    attempt_id: str
    attempt_number: int
    compile_status: str
    compile_errors: Optional[str] = None
    tests_passed: int
    tests_total: int
    status: str
    failure_category: Optional[str] = None
    diagnosis: Optional[str] = None
    generated_code: Optional[str] = None
    test_results: List[TestResultSchema] = []

class VerificationReport(BaseModel):
    migration_id: str
    project_id: str
    target_name: str
    final_status: str # 'VERIFIED' | 'VERIFICATION FAILED' | 'PARTIALLY SUPPORTED'
    compilation_passed: bool
    total_tests: int
    passed_tests: int
    equivalence_rate: float
    total_repair_attempts: int
    attempts_history: List[RepairAttemptSchema] = []
    unsupported_constructs: List[str] = []
