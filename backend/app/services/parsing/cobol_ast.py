from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

@dataclass
class SourceSpan:
    start_line: int
    end_line: int
    start_col: int = 1
    end_col: int = 1

@dataclass
class ASTBaseNode:
    node_type: str
    span: SourceSpan
    name: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    children: List['ASTBaseNode'] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": f"{self.node_type}_{self.name}_{self.span.start_line}_{self.span.end_line}",
            "name": self.name or self.node_type,
            "node_type": self.node_type,
            "start_line": self.span.start_line,
            "end_line": self.span.end_line,
            "details": self.details,
            "children": [c.to_dict() for c in self.children]
        }

@dataclass
class DataItemNode(ASTBaseNode):
    level: int = 1
    pic: str = ""
    value: Optional[str] = None
    data_type: str = "ALPHANUMERIC" # NUMERIC, DECIMAL, ALPHANUMERIC
    usage: str = "DISPLAY" # COMP, COMP-3, DISPLAY
    redefines: Optional[str] = None
    occurs: Optional[int] = None
    conditions: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "level": self.level,
            "pic": self.pic,
            "value": self.value,
            "data_type": self.data_type,
            "usage": self.usage,
            "redefines": self.redefines,
            "occurs": self.occurs,
            "conditions": self.conditions
        })
        return d

@dataclass
class StatementNode(ASTBaseNode):
    verb: str = "" # MOVE, COMPUTE, PERFORM, CALL, COPY, IF, EVALUATE, etc.
    raw_statement: str = ""
    variables_read: List[str] = field(default_factory=list)
    variables_written: List[str] = field(default_factory=list)
    targets: List[str] = field(default_factory=list) # e.g. CALL target, PERFORM target
    copybook_name: Optional[str] = None

@dataclass
class ParagraphNode(ASTBaseNode):
    statements: List[StatementNode] = field(default_factory=list)

@dataclass
class SectionNode(ASTBaseNode):
    paragraphs: List[ParagraphNode] = field(default_factory=list)

@dataclass
class DivisionNode(ASTBaseNode):
    sections: List[SectionNode] = field(default_factory=list)
    data_items: List[DataItemNode] = field(default_factory=list)

@dataclass
class ProgramNode(ASTBaseNode):
    program_id: str = ""
    divisions: Dict[str, DivisionNode] = field(default_factory=dict)
