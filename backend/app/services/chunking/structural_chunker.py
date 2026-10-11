import hashlib
import re
from typing import List, Dict, Any, Optional
from backend.app.services.parsing.cobol_adapter import CobolASTAdapter
from backend.app.schemas.ast_graph import ChunkInfo

class StructuralChunker:
    """
    Chunks COBOL code into semantic units (Paragraphs, Sections, Data Item blocks, Copybooks).
    Produces shared, deterministic chunk_ids used across relational, vector, and graph stores.
    """
    def __init__(self, project_id: str, file_id: str, source_code: str):
        self.project_id = project_id
        self.file_id = file_id
        self.source_code = source_code
        self.lines = source_code.splitlines()
        self.adapter = CobolASTAdapter.from_source(source_code)

    def _generate_chunk_id(self, symbol_type: str, symbol_name: str, start_line: int) -> str:
        raw_key = f"{self.project_id}:{self.file_id}:{symbol_type}:{symbol_name}:{start_line}"
        h = hashlib.sha256(raw_key.encode('utf-8')).hexdigest()[:12]
        clean_name = re.sub(r'[^A-Za-z0-9_]', '_', symbol_name)
        return f"chk_{symbol_type[:4]}_{clean_name}_{h}"

    def _extract_source_lines(self, start_line: int, end_line: int) -> str:
        # 1-indexed lines
        s = max(0, start_line - 1)
        e = min(len(self.lines), end_line)
        return "\n".join(self.lines[s:e])

    def create_chunks(self) -> List[ChunkInfo]:
        chunks: List[ChunkInfo] = []
        program_id = self.adapter.get_program_id()

        # 1. Program Header Chunk
        prog_node = self.adapter.program
        prog_chunk_id = self._generate_chunk_id("program", program_id, prog_node.span.start_line)
        prog_code = self._extract_source_lines(1, min(len(self.lines), 20))
        chunks.append(ChunkInfo(
            chunk_id=prog_chunk_id,
            file_id=self.file_id,
            symbol_name=program_id,
            symbol_type="program",
            parent_symbol=None,
            source_code=prog_code,
            start_line=1,
            end_line=min(len(self.lines), 20),
            variables_defined=[],
            variables_used=[],
            calls=[],
            called_by=[],
            copybooks=[],
            dependencies=[]
        ))

        # 2. Data Division / Working-Storage Item Chunks
        data_items = self.adapter.get_data_items()
        if data_items:
            # Group root 01/77 records or produce meaningful data item chunks
            for item in data_items:
                if item.level in (1, 77):
                    item_chunk_id = self._generate_chunk_id("data_item", item.name, item.span.start_line)
                    code = self._extract_source_lines(item.span.start_line, item.span.end_line)
                    chunks.append(ChunkInfo(
                        chunk_id=item_chunk_id,
                        file_id=self.file_id,
                        symbol_name=item.name,
                        symbol_type="data_item",
                        parent_symbol=program_id,
                        source_code=code,
                        start_line=item.span.start_line,
                        end_line=item.span.end_line,
                        variables_defined=[item.name],
                        variables_used=[],
                        calls=[],
                        called_by=[],
                        copybooks=[],
                        dependencies=[]
                    ))

        # 3. Procedure Division Sections & Paragraphs
        for sec in self.adapter.get_sections():
            sec_chunk_id = self._generate_chunk_id("section", sec.name, sec.span.start_line)
            sec_code = self._extract_source_lines(sec.span.start_line, sec.span.end_line)
            
            # Extract section-level dependencies
            sec_used = set()
            sec_calls = set()
            sec_copybooks = set()
            for p in sec.paragraphs:
                for s in p.statements:
                    sec_used.update(s.variables_read)
                    sec_used.update(s.variables_written)
                    if s.verb == 'CALL':
                        sec_calls.update(s.targets)
                    elif s.verb == 'COPY' and s.copybook_name:
                        sec_copybooks.add(s.copybook_name)

            chunks.append(ChunkInfo(
                chunk_id=sec_chunk_id,
                file_id=self.file_id,
                symbol_name=sec.name,
                symbol_type="section",
                parent_symbol=program_id,
                source_code=sec_code,
                start_line=sec.span.start_line,
                end_line=sec.span.end_line,
                variables_defined=[],
                variables_used=sorted(list(sec_used)),
                calls=sorted(list(sec_calls)),
                called_by=[],
                copybooks=sorted(list(sec_copybooks)),
                dependencies=[p.name for p in sec.paragraphs]
            ))

            for p in sec.paragraphs:
                p_chunk_id = self._generate_chunk_id("paragraph", p.name, p.span.start_line)
                p_code = self._extract_source_lines(p.span.start_line, p.span.end_line)

                p_vars_read = set()
                p_vars_written = set()
                p_calls = set()
                p_performs = set()
                p_copybooks = set()

                for stmt in p.statements:
                    p_vars_read.update(stmt.variables_read)
                    p_vars_written.update(stmt.variables_written)
                    if stmt.verb == 'CALL':
                        p_calls.update(stmt.targets)
                    elif stmt.verb == 'PERFORM':
                        p_performs.update(stmt.targets)
                    elif stmt.verb == 'COPY' and stmt.copybook_name:
                        p_copybooks.add(stmt.copybook_name)

                deps = sorted(list(p_performs.union(p_calls)))
                all_used = sorted(list(p_vars_read.union(p_vars_written)))

                chunks.append(ChunkInfo(
                    chunk_id=p_chunk_id,
                    file_id=self.file_id,
                    symbol_name=p.name,
                    symbol_type="paragraph",
                    parent_symbol=sec.name,
                    source_code=p_code,
                    start_line=p.span.start_line,
                    end_line=p.span.end_line,
                    variables_defined=sorted(list(p_vars_written)),
                    variables_used=all_used,
                    calls=sorted(list(p_calls)),
                    called_by=[],
                    copybooks=sorted(list(p_copybooks)),
                    dependencies=deps
                ))

        return chunks
