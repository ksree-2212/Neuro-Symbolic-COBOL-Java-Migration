import json
from collections import deque
from typing import List, Dict, Set, Any, Optional, Tuple
from backend.app.schemas.ast_graph import GraphNode, GraphEdge, GraphData
from backend.app.db.database import get_connection

class GraphStore:
    """
    Structural memory store holding the AST and dependency knowledge graph.
    Maintains project isolation and executes bounded k-hop expansion.
    """
    def __init__(self):
        self._ensure_tables()

    def _ensure_tables(self):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS graph_nodes (
            node_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            label TEXT NOT NULL,
            node_type TEXT NOT NULL,
            file_id TEXT,
            start_line INTEGER,
            end_line INTEGER,
            chunk_id TEXT,
            properties TEXT DEFAULT '{}'
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_graph_nodes_proj ON graph_nodes(project_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_graph_nodes_chunk ON graph_nodes(chunk_id);")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS graph_edges (
            edge_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            rel_type TEXT NOT NULL,
            properties TEXT DEFAULT '{}'
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_graph_edges_proj ON graph_edges(project_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_graph_edges_src ON graph_edges(source_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_graph_edges_tgt ON graph_edges(target_id);")
        conn.commit()
        conn.close()

    def index_graph(self, project_id: str, graph: GraphData, chunk_mapping: Optional[Dict[str, str]] = None):
        """
        Indexes graph nodes and edges for a specific project.
        chunk_mapping maps symbol_name or node_id -> chunk_id.
        """
        chunk_mapping = chunk_mapping or {}
        conn = get_connection()
        cursor = conn.cursor()

        # Clean existing graph for this project
        cursor.execute("DELETE FROM graph_nodes WHERE project_id = ?", (project_id,))
        cursor.execute("DELETE FROM graph_edges WHERE project_id = ?", (project_id,))

        for n in graph.nodes:
            # Match chunk_id by node_id or label
            c_id = chunk_mapping.get(n.id) or chunk_mapping.get(n.label)
            cursor.execute(
                """
                INSERT OR REPLACE INTO graph_nodes 
                (node_id, project_id, label, node_type, file_id, start_line, end_line, chunk_id, properties)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (n.id, project_id, n.label, n.type, n.file_id, n.start_line, n.end_line, c_id, json.dumps(n.properties))
            )

        for e in graph.edges:
            cursor.execute(
                """
                INSERT OR REPLACE INTO graph_edges
                (edge_id, project_id, source_id, target_id, rel_type, properties)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (e.id, project_id, e.source, e.target, e.type, json.dumps(e.properties))
            )

        conn.commit()
        conn.close()

    def get_project_graph(self, project_id: str) -> GraphData:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM graph_nodes WHERE project_id = ?", (project_id,))
        node_rows = cursor.fetchall()

        cursor.execute("SELECT * FROM graph_edges WHERE project_id = ?", (project_id,))
        edge_rows = cursor.fetchall()
        conn.close()

        nodes = [
            GraphNode(
                id=r["node_id"],
                label=r["label"],
                type=r["node_type"],
                file_id=r["file_id"],
                start_line=r["start_line"],
                end_line=r["end_line"],
                properties=json.loads(r["properties"])
            )
            for r in node_rows
        ]

        edges = [
            GraphEdge(
                id=r["edge_id"],
                source=r["source_id"],
                target=r["target_id"],
                type=r["rel_type"],
                properties=json.loads(r["properties"])
            )
            for r in edge_rows
        ]

        return GraphData(nodes=nodes, edges=edges)

    def find_nodes_by_chunk_ids(self, project_id: str, chunk_ids: List[str]) -> List[GraphNode]:
        if not chunk_ids:
            return []
        conn = get_connection()
        cursor = conn.cursor()
        placeholders = ",".join("?" * len(chunk_ids))
        cursor.execute(
            f"SELECT * FROM graph_nodes WHERE project_id = ? AND chunk_id IN ({placeholders})",
            [project_id] + chunk_ids
        )
        rows = cursor.fetchall()
        conn.close()

        return [
            GraphNode(
                id=r["node_id"],
                label=r["label"],
                type=r["node_type"],
                file_id=r["file_id"],
                start_line=r["start_line"],
                end_line=r["end_line"],
                properties=json.loads(r["properties"])
            )
            for r in rows
        ]

    def traverse_bounded(self, project_id: str, start_node_ids: List[str], max_hops: int = 2) -> Tuple[List[GraphNode], List[GraphEdge]]:
        """
        Executes bounded BFS graph expansion starting from start_node_ids.
        Returns newly discovered nodes and traversal edges.
        """
        if not start_node_ids:
            return [], []

        conn = get_connection()
        cursor = conn.cursor()

        # Load all edges for project to perform rapid in-memory traversal
        cursor.execute("SELECT * FROM graph_edges WHERE project_id = ?", (project_id,))
        edge_rows = cursor.fetchall()

        adj: Dict[str, List[Tuple[str, str, str, Dict]]] = {} # node -> list of (neighbor, edge_id, rel_type, props)
        for r in edge_rows:
            src, tgt, eid, rtype = r["source_id"], r["target_id"], r["edge_id"], r["rel_type"]
            props = json.loads(r["properties"])
            adj.setdefault(src, []).append((tgt, eid, rtype, props))
            # Also allow traversing reverse dependencies if needed (e.g., references)
            adj.setdefault(tgt, []).append((src, eid, rtype, props))

        visited_nodes: Set[str] = set(start_node_ids)
        discovered_edges: Dict[str, GraphEdge] = {}
        queue = deque([(nid, 0) for nid in start_node_ids])

        while queue:
            curr_id, depth = queue.popleft()
            if depth >= max_hops:
                continue

            for neighbor_id, eid, rtype, props in adj.get(curr_id, []):
                if eid not in discovered_edges:
                    discovered_edges[eid] = GraphEdge(
                        id=eid,
                        source=curr_id,
                        target=neighbor_id,
                        type=rtype,
                        properties=props
                    )
                if neighbor_id not in visited_nodes:
                    visited_nodes.add(neighbor_id)
                    queue.append((neighbor_id, depth + 1))

        # Query all visited nodes
        placeholders = ",".join("?" * len(visited_nodes))
        cursor.execute(
            f"SELECT * FROM graph_nodes WHERE project_id = ? AND node_id IN ({placeholders})",
            [project_id] + list(visited_nodes)
        )
        node_rows = cursor.fetchall()
        conn.close()

        all_nodes = [
            GraphNode(
                id=r["node_id"],
                label=r["label"],
                type=r["node_type"],
                file_id=r["file_id"],
                start_line=r["start_line"],
                end_line=r["end_line"],
                properties=json.loads(r["properties"])
            )
            for r in node_rows
        ]

        return all_nodes, list(discovered_edges.values())
