import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Dict, List, Any, Optional
from backend.app.config import settings
from backend.app.db.database import get_connection
from backend.app.schemas.project import AnalysisSummary, FileInfo
from backend.app.services.parsing.cobol_adapter import CobolASTAdapter, CobolSymbolExtractor
from backend.app.services.chunking.structural_chunker import StructuralChunker
from backend.app.services.dependencies.dependency_extractor import CobolDependencyExtractor
from backend.app.services.dependencies.copybook_resolver import CopybookResolver
from backend.app.services.vector_store.vector_store import VectorStore
from backend.app.services.graph_store.graph_store import GraphStore
from backend.app.schemas.ast_graph import GraphData

class WorkspaceManager:
    """
    Manages project workspaces, file uploads, structural indexing,
    and coordinates Phase 1 (Parsing) and Phase 2 (Dual Memory).
    """
    def __init__(self, workspace_root: Optional[Path] = None):
        self.workspace_root = workspace_root or settings.workspace_dir
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.vector_store = VectorStore()
        self.graph_store = GraphStore()

    def get_project_dir(self, project_id: str) -> Path:
        pdir = self.workspace_root / "projects" / project_id
        for sub in ["source", "copybooks", "ast", "chunks", "graph", "embeddings", "generated", "tests", "verification", "logs", "reports"]:
            (pdir / sub).mkdir(parents=True, exist_ok=True)
        return pdir

    def create_project(self, name: str, source_language: str = "COBOL", target_language: str = "Java") -> str:
        project_id = f"proj_{uuid.uuid4().hex[:10]}"
        self.get_project_dir(project_id)

        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO projects (project_id, name, source_language, target_language, status)
                VALUES (?, ?, ?, ?, 'CREATED')
                """,
                (project_id, name, source_language, target_language)
            )
            conn.commit()
        finally:
            conn.close()
        return project_id

    def save_file(self, project_id: str, file_name: str, content: str, file_type: str = "SOURCE") -> str:
        clean_name = Path(file_name).name
        if not clean_name:
            clean_name = f"file_{uuid.uuid4().hex[:6]}.cbl"
        file_id = f"file_{uuid.uuid4().hex[:10]}"
        pdir = self.get_project_dir(project_id)
        subfolder = "copybooks" if file_type == "COPYBOOK" else "source"
        target_dir = (pdir / subfolder).resolve()
        target_path = (target_dir / clean_name).resolve()
        try:
            target_path.relative_to(target_dir)
        except ValueError:
            raise ValueError(f"Path traversal detected in file name: {file_name}")

        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)

        line_count = len(content.splitlines())

        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO files (file_id, project_id, file_name, file_path, file_type, line_count, content)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (file_id, project_id, clean_name, str(target_path), file_type, line_count, content)
            )
            conn.commit()
        finally:
            conn.close()
        return file_id

    def analyze_and_index_project(self, project_id: str) -> AnalysisSummary:
        pdir = self.get_project_dir(project_id)
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM files WHERE project_id = ?", (project_id,))
        file_rows = cursor.fetchall()

        copybook_dir = pdir / "copybooks"
        source_dir = pdir / "source"
        copybook_resolver = CopybookResolver([copybook_dir, source_dir])

        all_chunks = []
        file_path_map = {}
        all_nodes = []
        all_edges = []
        seen_node_ids = set()
        seen_edge_keys = set()
        chunk_mapping = {}

        total_lines = 0
        program_count = 0
        section_count = 0
        paragraph_count = 0
        call_count = 0
        perform_count = 0
        copybooks_detected = 0

        # Clean prior chunks for project
        cursor.execute("DELETE FROM chunks WHERE project_id = ?", (project_id,))

        for f_row in file_rows:
            f_id = f_row["file_id"]
            f_name = f_row["file_name"]
            f_type = f_row["file_type"]
            f_path = f_row["file_path"]
            content = f_row["content"]
            file_path_map[f_id] = f_path
            total_lines += f_row["line_count"]

            if f_type == "COPYBOOK":
                copybooks_detected += 1
                # Index copybook as a node
                cb_clean = f_name.rsplit(".", 1)[0]
                cb_id = f"cpy_{project_id}_{cb_clean}"
                from backend.app.schemas.ast_graph import GraphNode
                if cb_id not in seen_node_ids:
                    seen_node_ids.add(cb_id)
                    all_nodes.append(GraphNode(
                        id=cb_id,
                        label=cb_clean,
                        type="Copybook",
                        file_id=f_id,
                        properties={"file_name": f_name, "content": content}
                    ))
                continue

            # Parse COBOL source
            adapter = CobolASTAdapter.from_source(content)
            prog_id = adapter.get_program_id()
            program_count += 1

            # Save AST to DB and disk
            ast_dict = adapter.to_tree_dict()
            with open(pdir / "ast" / f"{f_name}.ast.json", "w", encoding="utf-8") as af:
                json.dump(ast_dict, af, indent=2)

            cursor.execute(
                "UPDATE files SET ast_json = ? WHERE file_id = ?",
                (json.dumps(ast_dict), f_id)
            )

            # Generate semantic chunks
            chunker = StructuralChunker(project_id, f_id, content)
            chunks = chunker.create_chunks()

            for chk in chunks:
                all_chunks.append(chk)
                chunk_mapping[chk.symbol_name] = chk.chunk_id
                cursor.execute(
                    """
                    INSERT INTO chunks 
                    (chunk_id, project_id, file_id, symbol_name, symbol_type, parent_symbol, source_code, start_line, end_line, variables_defined, variables_used, calls, called_by, copybooks, dependencies)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chk.chunk_id, project_id, chk.file_id, chk.symbol_name, chk.symbol_type,
                        chk.parent_symbol, chk.source_code, chk.start_line, chk.end_line,
                        json.dumps(chk.variables_defined), json.dumps(chk.variables_used),
                        json.dumps(chk.calls), json.dumps(chk.called_by),
                        json.dumps(chk.copybooks), json.dumps(chk.dependencies)
                    )
                )

            # Extract dependencies
            dep_extractor = CobolDependencyExtractor(project_id, f_id, adapter)
            graph_data = dep_extractor.extract_graph()

            section_count += len(adapter.get_sections())
            paragraph_count += len(adapter.get_paragraphs())

            for n in graph_data.nodes:
                if n.id not in seen_node_ids:
                    seen_node_ids.add(n.id)
                    all_nodes.append(n)

            for e in graph_data.edges:
                k = f"{e.source}:{e.type}:{e.target}"
                if k not in seen_edge_keys:
                    seen_edge_keys.add(k)
                    all_edges.append(e)
                    if e.type == 'CALLS':
                        call_count += 1
                    elif e.type == 'PERFORMS':
                        perform_count += 1

        conn.commit()

        # Step 2: Index in Vector Store
        self.vector_store.index_chunks(project_id, all_chunks, file_path_map)

        # Step 3: Index in Graph Store (and sync to Neo4j if available)
        combined_graph = GraphData(nodes=all_nodes, edges=all_edges)
        self.graph_store.index_graph(project_id, combined_graph, chunk_mapping)

        # Save graph to disk
        with open(pdir / "graph" / "dependency_graph.json", "w", encoding="utf-8") as gf:
            if hasattr(combined_graph, "model_dump_json"):
                gf.write(combined_graph.model_dump_json(indent=2))
            else:
                gf.write(combined_graph.json(indent=2))

        # Update Project Status
        cursor.execute("UPDATE projects SET status = 'INDEXED' WHERE project_id = ?", (project_id,))
        cursor.execute("SELECT name FROM projects WHERE project_id = ?", (project_id,))
        p_row = cursor.fetchone()
        proj_name = p_row["name"] if p_row else "COBOL Project"
        conn.commit()
        conn.close()

        # Check Copybook status
        cb_status = copybook_resolver.get_status()

        return AnalysisSummary(
            project_id=project_id,
            name=proj_name,
            files_detected=len(file_rows),
            copybooks_detected=copybooks_detected,
            lines_of_code=total_lines,
            programs=program_count,
            sections=section_count,
            paragraphs=paragraph_count,
            call_statements=call_count,
            perform_statements=perform_count,
            dependencies_count=len(all_edges),
            index_status="INDEXED",
            copybook_resolution_status={cb: "RESOLVED" for cb in cb_status["resolved"]},
            unresolved_copybooks=cb_status["unresolved"]
        )
