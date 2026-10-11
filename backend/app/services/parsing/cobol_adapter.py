from typing import List, Dict, Any, Optional
from backend.app.services.parsing.cobol_parser import CobolParser
from backend.app.services.parsing.cobol_ast import (
    ProgramNode, DivisionNode, SectionNode, ParagraphNode,
    DataItemNode, StatementNode, ASTBaseNode
)

class CobolASTAdapter:
    """
    Standardizes AST navigation and structural querying.
    Decouples raw parser implementation from the rest of the application.
    """
    def __init__(self, program: ProgramNode):
        self.program = program

    @classmethod
    def from_source(cls, source_code: str) -> 'CobolASTAdapter':
        parser = CobolParser(source_code)
        program = parser.parse()
        return cls(program)

    def get_program_id(self) -> str:
        return self.program.program_id or self.program.name

    def get_divisions(self) -> Dict[str, DivisionNode]:
        return self.program.divisions

    def get_data_items(self) -> List[DataItemNode]:
        data_div = self.program.divisions.get("DATA")
        if not data_div:
            return []
        items = list(data_div.data_items)
        for sec in data_div.sections:
            for child in sec.children:
                if isinstance(child, DataItemNode) and child not in items:
                    items.append(child)
        return items

    def get_sections(self) -> List[SectionNode]:
        proc_div = self.program.divisions.get("PROCEDURE")
        if not proc_div:
            return []
        return proc_div.sections

    def get_paragraphs(self) -> List[ParagraphNode]:
        paras = []
        for sec in self.get_sections():
            paras.extend(sec.paragraphs)
        return paras

    def to_tree_dict(self) -> Dict[str, Any]:
        return self.program.to_dict()

class CobolSymbolExtractor:
    """
    Extracts all declared symbols (paragraphs, sections, variables, copybooks, calls).
    """
    def __init__(self, adapter: CobolASTAdapter):
        self.adapter = adapter

    def extract_symbols(self) -> Dict[str, List[Dict[str, Any]]]:
        program_id = self.adapter.get_program_id()
        symbols = {
            "program": [{"name": program_id, "line": self.adapter.program.span.start_line}],
            "sections": [],
            "paragraphs": [],
            "variables": [],
            "copybooks": [],
            "external_calls": []
        }

        # Sections & Paragraphs
        for sec in self.adapter.get_sections():
            symbols["sections"].append({
                "name": sec.name,
                "start_line": sec.span.start_line,
                "end_line": sec.span.end_line
            })
            for p in sec.paragraphs:
                symbols["paragraphs"].append({
                    "name": p.name,
                    "section": sec.name,
                    "start_line": p.span.start_line,
                    "end_line": p.span.end_line,
                    "statements_count": len(p.statements)
                })
                # Check calls & copybooks in statements
                for s in p.statements:
                    if s.verb == 'CALL':
                        symbols["external_calls"].extend(s.targets)
                    elif s.verb == 'COPY' and s.copybook_name:
                        symbols["copybooks"].append(s.copybook_name)

        # Variables
        for var in self.adapter.get_data_items():
            symbols["variables"].append({
                "name": var.name,
                "level": var.level,
                "pic": var.pic,
                "type": var.data_type,
                "line": var.span.start_line
            })

        # Check copybooks in DATA DIVISION
        data_div = self.adapter.get_divisions().get("DATA")
        if data_div and "copybooks" in data_div.details:
            for cb in data_div.details["copybooks"]:
                if cb and cb not in symbols["copybooks"]:
                    symbols["copybooks"].append(cb)

        symbols["copybooks"] = list(set(symbols["copybooks"]))
        symbols["external_calls"] = list(set(symbols["external_calls"]))
        return symbols
