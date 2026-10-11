import json
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
from backend.app.schemas.ast_graph import ChunkInfo
from backend.app.services.embeddings.embedding_service import EmbeddingService
from backend.app.db.database import get_connection

@dataclass
class VectorSearchResult:
    chunk_id: str
    similarity_score: float
    symbol_name: str
    symbol_type: str
    file_id: str
    source_code: str
    metadata: Dict[str, Any]

class VectorStore:
    """
    Semantic memory store holding code chunk embeddings.
    Provides project-isolated top-k vector similarity retrieval.
    """
    def __init__(self, embedding_service: Optional[EmbeddingService] = None):
        self.embedder = embedding_service or EmbeddingService()

    def index_chunks(self, project_id: str, chunks: List[ChunkInfo], file_paths: Dict[str, str]):
        conn = get_connection()
        cursor = conn.cursor()

        # Remove existing vector entries for this project to support re-indexing
        cursor.execute("CREATE TABLE IF NOT EXISTS vector_entries (chunk_id TEXT PRIMARY KEY, project_id TEXT, vector TEXT, metadata TEXT);")
        cursor.execute("DELETE FROM vector_entries WHERE project_id = ?", (project_id,))

        for chk in chunks:
            # Create embedding from symbol name + variables + source code
            embed_text = f"{chk.symbol_type} {chk.symbol_name} {' '.join(chk.variables_used)} {chk.source_code}"
            vec = self.embedder.embed_text(embed_text)
            
            meta = {
                "chunk_id": chk.chunk_id,
                "project_id": project_id,
                "file_id": chk.file_id,
                "symbol_name": chk.symbol_name,
                "symbol_type": chk.symbol_type,
                "language": "COBOL",
                "source_path": file_paths.get(chk.file_id, ""),
                "start_line": chk.start_line,
                "end_line": chk.end_line
            }

            cursor.execute(
                "INSERT INTO vector_entries (chunk_id, project_id, vector, metadata) VALUES (?, ?, ?, ?)",
                (chk.chunk_id, project_id, json.dumps(vec), json.dumps(meta))
            )

        conn.commit()
        conn.close()

    def search(self, project_id: str, query: str, top_k: int = 5) -> List[VectorSearchResult]:
        query_vec = self.embedder.embed_text(query)
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("CREATE TABLE IF NOT EXISTS vector_entries (chunk_id TEXT PRIMARY KEY, project_id TEXT, vector TEXT, metadata TEXT);")
        cursor.execute("SELECT ve.chunk_id, ve.vector, ve.metadata, c.source_code FROM vector_entries ve JOIN chunks c ON ve.chunk_id = c.chunk_id WHERE ve.project_id = ?", (project_id,))
        rows = cursor.fetchall()
        conn.close()

        scored: List[VectorSearchResult] = []
        for row in rows:
            chunk_id = row["chunk_id"]
            vec = json.loads(row["vector"])
            meta = json.loads(row["metadata"])
            code = row["source_code"]

            score = self.embedder.cosine_similarity(query_vec, vec)
            scored.append(VectorSearchResult(
                chunk_id=chunk_id,
                similarity_score=score,
                symbol_name=meta.get("symbol_name", ""),
                symbol_type=meta.get("symbol_type", ""),
                file_id=meta.get("file_id", ""),
                source_code=code,
                metadata=meta
            ))

        # Sort descending by similarity
        scored.sort(key=lambda x: x.similarity_score, reverse=True)
        return scored[:top_k]
