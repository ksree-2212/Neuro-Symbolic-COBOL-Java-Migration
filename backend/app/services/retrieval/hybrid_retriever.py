import json
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Set, Tuple
from backend.app.schemas.ast_graph import ChunkInfo, GraphNode, GraphEdge
from backend.app.schemas.migration import RetrievalInspection
from backend.app.services.vector_store.vector_store import VectorStore, VectorSearchResult
from backend.app.services.graph_store.graph_store import GraphStore
from backend.app.services.retrieval.constraint_generator import StructuralConstraintGenerator
from backend.app.services.dependencies.copybook_resolver import CopybookResolver
from backend.app.db.database import get_connection

@dataclass
class ContextBundle:
    primary_chunks: List[ChunkInfo]
    dependency_chunks: List[ChunkInfo]
    copybooks: List[Dict[str, str]] # name, content, path
    graph_edges: List[GraphEdge]
    retrieval_scores: List[Dict[str, Any]]
    structural_constraints: List[str]
    unresolved_dependencies: List[str]
    inspection: RetrievalInspection

class HybridRetriever:
    """
    AST-Guided Neuro-Symbolic Hybrid Retriever:
    1. Vector retrieval finds what is relevant (semantic candidates).
    2. Graph memory finds what is required (bounded dependency expansion).
    3. Merges, deduplicates, and generates structural constraints.
    """
    def __init__(self, vector_store: Optional[VectorStore] = None, graph_store: Optional[GraphStore] = None):
        self.vector_store = vector_store or VectorStore()
        self.graph_store = graph_store or GraphStore()

    def _load_chunk_by_id(self, chunk_id: str) -> Optional[ChunkInfo]:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None

        return ChunkInfo(
            chunk_id=row["chunk_id"],
            file_id=row["file_id"],
            symbol_name=row["symbol_name"],
            symbol_type=row["symbol_type"],
            parent_symbol=row["parent_symbol"],
            source_code=row["source_code"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            variables_defined=json.loads(row["variables_defined"]),
            variables_used=json.loads(row["variables_used"]),
            calls=json.loads(row["calls"]),
            called_by=json.loads(row["called_by"]),
            copybooks=json.loads(row["copybooks"]),
            dependencies=json.loads(row["dependencies"])
        )

    def _find_chunks_by_symbol(self, project_id: str, symbol_name: str) -> List[ChunkInfo]:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM chunks WHERE project_id = ? AND symbol_name = ?", (project_id, symbol_name))
        rows = cursor.fetchall()
        conn.close()
        chunks = []
        for row in rows:
            chunks.append(ChunkInfo(
                chunk_id=row["chunk_id"],
                file_id=row["file_id"],
                symbol_name=row["symbol_name"],
                symbol_type=row["symbol_type"],
                parent_symbol=row["parent_symbol"],
                source_code=row["source_code"],
                start_line=row["start_line"],
                end_line=row["end_line"],
                variables_defined=json.loads(row["variables_defined"]),
                variables_used=json.loads(row["variables_used"]),
                calls=json.loads(row["calls"]),
                called_by=json.loads(row["called_by"]),
                copybooks=json.loads(row["copybooks"]),
                dependencies=json.loads(row["dependencies"])
            ))
        return chunks

    def retrieve(
        self,
        project_id: str,
        query: str,
        top_k: int = 5,
        graph_hops: int = 2,
        copybook_resolver: Optional[CopybookResolver] = None,
        baseline: bool = False
    ) -> ContextBundle:
        # Step 1: Semantic Vector Search
        vector_results = self.vector_store.search(project_id, query, top_k=top_k)
        primary_chunks: List[ChunkInfo] = []
        retrieval_scores = []
        seen_chunk_ids: Set[str] = set()

        for vr in vector_results:
            chk = self._load_chunk_by_id(vr.chunk_id)
            if chk and chk.chunk_id not in seen_chunk_ids:
                seen_chunk_ids.add(chk.chunk_id)
                primary_chunks.append(chk)
                retrieval_scores.append({
                    "chunk_id": chk.chunk_id,
                    "symbol_name": chk.symbol_name,
                    "symbol_type": chk.symbol_type,
                    "similarity_score": vr.similarity_score
                })

        # If baseline mode: skip graph expansion and structural constraints!
        if baseline:
            inspection = RetrievalInspection(
                query=query,
                vector_results=[{"chunk_id": r["chunk_id"], "symbol": r["symbol_name"], "score": r["similarity_score"]} for r in retrieval_scores],
                graph_expansion_nodes=[],
                graph_expansion_edges=[],
                final_chunk_ids=list(seen_chunk_ids),
                structural_constraints=[],
                unresolved_dependencies=[]
            )
            return ContextBundle(
                primary_chunks=primary_chunks,
                dependency_chunks=[],
                copybooks=[],
                graph_edges=[],
                retrieval_scores=retrieval_scores,
                structural_constraints=[],
                unresolved_dependencies=[],
                inspection=inspection
            )

        # Step 2: Bounded Graph Memory Expansion
        start_nodes: List[GraphNode] = self.graph_store.find_nodes_by_chunk_ids(project_id, list(seen_chunk_ids))
        start_node_ids = [n.id for n in start_nodes]
        
        # If no direct chunk mapping, map by symbol names of primary chunks
        if not start_node_ids:
            for chk in primary_chunks:
                start_node_ids.append(f"para_{project_id}_{chk.symbol_name}")
                start_node_ids.append(f"var_{project_id}_{chk.symbol_name}")
                start_node_ids.append(f"sec_{project_id}_{chk.symbol_name}")

        expanded_nodes, expanded_edges = self.graph_store.traverse_bounded(
            project_id=project_id,
            start_node_ids=start_node_ids,
            max_hops=graph_hops
        )

        # Step 3: Resolve Dependency Chunks
        dependency_chunks: List[ChunkInfo] = []
        copybooks_needed: Set[str] = set()
        unresolved_deps: List[str] = []

        # Collect copybooks and symbols from primary chunks
        for chk in primary_chunks:
            copybooks_needed.update(chk.copybooks)

        # Check expanded nodes
        for node in expanded_nodes:
            if node.type == 'Copybook':
                copybooks_needed.add(node.label)
            elif node.type in ('Paragraph', 'Section', 'DataItem'):
                # Find matching chunk if not already in primary
                cand_chunks = self._find_chunks_by_symbol(project_id, node.label)
                for c in cand_chunks:
                    if c.chunk_id not in seen_chunk_ids:
                        seen_chunk_ids.add(c.chunk_id)
                        dependency_chunks.append(c)
                        copybooks_needed.update(c.copybooks)

        # Step 4: Resolve Copybooks
        resolved_copybooks: List[Dict[str, str]] = []
        if copybook_resolver:
            for cb in sorted(list(copybooks_needed)):
                res = copybook_resolver.resolve(cb)
                if res:
                    p, content = res
                    resolved_copybooks.append({
                        "name": cb,
                        "path": str(p),
                        "content": content
                    })
                else:
                    unresolved_deps.append(f"COPYBOOK: {cb}")

        # Step 5: Generate Structural Constraints
        constraints = StructuralConstraintGenerator.generate_constraints(
            edges=expanded_edges,
            nodes=expanded_nodes,
            copybooks=list(copybooks_needed)
        )

        inspection = RetrievalInspection(
            query=query,
            vector_results=[{"chunk_id": r["chunk_id"], "symbol": r["symbol_name"], "score": r["similarity_score"]} for r in retrieval_scores],
            graph_expansion_nodes=[{"id": n.id, "label": n.label, "type": n.type} for n in expanded_nodes if n.id not in start_node_ids],
            graph_expansion_edges=[{"source": e.source, "type": e.type, "target": e.target} for e in expanded_edges],
            final_chunk_ids=list(seen_chunk_ids),
            structural_constraints=constraints,
            unresolved_dependencies=unresolved_deps
        )

        return ContextBundle(
            primary_chunks=primary_chunks,
            dependency_chunks=dependency_chunks,
            copybooks=resolved_copybooks,
            graph_edges=expanded_edges,
            retrieval_scores=retrieval_scores,
            structural_constraints=constraints,
            unresolved_dependencies=unresolved_deps,
            inspection=inspection
        )
