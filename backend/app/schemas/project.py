from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

class ProjectCreate(BaseModel):
    name: str
    source_language: str = "COBOL"
    target_language: str = "Java"

class FileInfo(BaseModel):
    file_id: str
    project_id: str
    file_name: str
    file_path: str
    file_type: str # 'SOURCE' | 'COPYBOOK'
    line_count: int
    created_at: str

class AnalysisSummary(BaseModel):
    project_id: str
    name: str
    files_detected: int
    copybooks_detected: int
    lines_of_code: int
    programs: int
    sections: int
    paragraphs: int
    call_statements: int
    perform_statements: int
    dependencies_count: int
    index_status: str # 'NOT_INDEXED', 'INDEXED', 'FAILED'
    copybook_resolution_status: Dict[str, str] = {}
    unresolved_copybooks: List[str] = []

class ProjectResponse(BaseModel):
    project_id: str
    name: str
    source_language: str
    target_language: str
    status: str
    created_at: str
    summary: Optional[AnalysisSummary] = None
