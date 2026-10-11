import unittest
from backend.app.services.embeddings.embedding_service import EmbeddingService
from backend.app.services.vector_store.vector_store import VectorStore
from backend.app.services.graph_store.graph_store import GraphStore
from backend.app.schemas.ast_graph import ChunkInfo, GraphData, GraphNode, GraphEdge

class TestVectorAndGraphStores(unittest.TestCase):
    def test_embedding_cosine_similarity(self):
        embedder = EmbeddingService(dimension=64)
        v1 = embedder.embed_text("PERFORM CALCULATE-TAX WITH TAX-RATE")
        v2 = embedder.embed_text("PERFORM CALCULATE-TAX WITH TAX-RATE")
        v3 = embedder.embed_text("CUSTOMER-RECORD ADDRESS FIELD")

        sim_identical = embedder.cosine_similarity(v1, v2)
        sim_diff = embedder.cosine_similarity(v1, v3)

        self.assertAlmostEqual(sim_identical, 1.0, places=4)
        self.assertTrue(sim_identical > sim_diff)

    def test_graph_bounded_traversal(self):
        graph_store = GraphStore()
        proj_id = "test_graph_proj"

        nodes = [
            GraphNode(id="n1", label="MAIN", type="Paragraph"),
            GraphNode(id="n2", label="CALC-TAX", type="Paragraph"),
            GraphNode(id="n3", label="TAX-RATE", type="DataItem"),
            GraphNode(id="n4", label="UNRELATED", type="Paragraph")
        ]
        edges = [
            GraphEdge(id="e1", source="n1", target="n2", type="PERFORMS"),
            GraphEdge(id="e2", source="n2", target="n3", type="REFERENCES")
        ]
        gdata = GraphData(nodes=nodes, edges=edges)
        graph_store.index_graph(proj_id, gdata)

        # 1-hop from n1
        exp_1_nodes, exp_1_edges = graph_store.traverse_bounded(proj_id, ["n1"], max_hops=1)
        labels_1 = [n.label for n in exp_1_nodes]
        self.assertIn("MAIN", labels_1)
        self.assertIn("CALC-TAX", labels_1)
        self.assertNotIn("TAX-RATE", labels_1)

        # 2-hop from n1
        exp_2_nodes, exp_2_edges = graph_store.traverse_bounded(proj_id, ["n1"], max_hops=2)
        labels_2 = [n.label for n in exp_2_nodes]
        self.assertIn("MAIN", labels_2)
        self.assertIn("CALC-TAX", labels_2)
        self.assertIn("TAX-RATE", labels_2)
        self.assertNotIn("UNRELATED", labels_2)

if __name__ == "__main__":
    unittest.main()
