from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from backend.app.schemas.ast_graph import ChunkInfo, GraphEdge

class MigrationRequest(BaseModel):
    project_id: str
    target_mode: str # 'FILE' | 'PARAGRAPH' | 'QUERY'
    target_name: str
    query: Optional[str] = None
    top_k: int = 5
    graph_hops: int = 2
    max_repair_attempts: int = 3
    baseline: bool = False # If true, runs baseline (unconstrained + vector only)

class RetrievalInspection(BaseModel):
    query: str
    vector_results: List[Dict[str, Any]] # chunk_id, score, symbol_name
    graph_expansion_nodes: List[Dict[str, Any]]
    graph_expansion_edges: List[Dict[str, Any]]
    final_chunk_ids: List[str]
    structural_constraints: List[str]
    unresolved_dependencies: List[str]

class GeneratedFile(BaseModel):
    path: str
    content: str

class MigrationResponse(BaseModel):
    migration_id: str
    project_id: str
    target_mode: str
    target_name: str
    status: str
    retrieval: Optional[RetrievalInspection] = None
    generated_files: List[GeneratedFile] = []
    compilation_passed: bool = False
    tests_total: int = 0
    tests_passed: int = 0
    equivalence_rate: float = 0.0
    repair_attempts: int = 0
    final_status: str
    metrics: Dict[str, Any] = {}
