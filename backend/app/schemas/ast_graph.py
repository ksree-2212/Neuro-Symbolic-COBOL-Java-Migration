from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

class ASTNode(BaseModel):
    id: str
    name: str
    node_type: str # 'Program', 'Division', 'Section', 'Paragraph', 'DataItem', 'Statement'
    start_line: int
    end_line: int
    details: Dict[str, Any] = {}
    children: List['ASTNode'] = []

ASTNode.update_forward_refs()

class ChunkInfo(BaseModel):
    chunk_id: str
    file_id: str
    symbol_name: str
    symbol_type: str
    parent_symbol: Optional[str] = None
    source_code: str
    start_line: int
    end_line: int
    variables_defined: List[str] = []
    variables_used: List[str] = []
    calls: List[str] = []
    called_by: List[str] = []
    copybooks: List[str] = []
    dependencies: List[str] = []

class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    file_id: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    properties: Dict[str, Any] = {}

class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str # 'CONTAINS', 'PERFORMS', 'CALLS', 'REFERENCES', 'COPIES', 'DEPENDS_ON', 'DEFINES', 'READS', 'WRITES'
    properties: Dict[str, Any] = {}

class GraphData(BaseModel):
    nodes: List[GraphNode]
    edges: List[GraphEdge]
