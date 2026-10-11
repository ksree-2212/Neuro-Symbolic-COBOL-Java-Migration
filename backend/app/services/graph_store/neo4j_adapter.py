import logging
from typing import Dict, Any, Optional, List, Tuple
from backend.app.config import settings
from backend.app.schemas.ast_graph import GraphData, GraphNode, GraphEdge

logger = logging.getLogger(__name__)

class Neo4jAdapter:
    """
    Adapter for external Neo4j instances.
    Provides Cypher query mapping and handles fallback gracefully when Neo4j is offline.
    """
    def __init__(self):
        self.uri = settings.neo4j_uri
        self.username = settings.neo4j_username
        self.password = settings.neo4j_password
        self.connected = False
        self.driver = None
        self._init_connection()

    def _init_connection(self):
        if settings.use_embedded_graph:
            logger.info("Using high-performance embedded graph store.")
            return

        try:
            from neo4j import GraphDatabase
            self.driver = GraphDatabase.driver(self.uri, auth=(self.username, self.password))
            with self.driver.session() as session:
                session.run("RETURN 1")
            self.connected = True
            logger.info(f"Connected to Neo4j at {self.uri}")
        except Exception as e:
            logger.warning(f"Neo4j connection failed ({e}). Falling back to embedded graph store.")
            self.connected = False

    def sync_graph(self, project_id: str, graph: GraphData):
        if not self.connected or not self.driver:
            return

        try:
            with self.driver.session() as session:
                # Delete existing project nodes
                session.run("MATCH (n {project_id: $pid}) DETACH DELETE n", pid=project_id)

                # Insert nodes
                for n in graph.nodes:
                    cypher = f"CREATE (n:{n.type} {{id: $id, label: $label, project_id: $pid}})"
                    session.run(cypher, id=n.id, label=n.label, pid=project_id)

                # Insert edges
                for e in graph.edges:
                    cypher = f"""
                    MATCH (s {{id: $s_id, project_id: $pid}}), (t {{id: $t_id, project_id: $pid}})
                    CREATE (s)-[r:{e.type}]->(t)
                    """
                    session.run(cypher, s_id=e.source, t_id=e.target, pid=project_id)
        except Exception as e:
            logger.error(f"Error syncing to Neo4j: {e}")

    def close(self):
        if self.driver:
            self.driver.close()
