import json
import tempfile
import unittest
from pathlib import Path
from backend.app.schemas.ast_graph import GraphNode, GraphEdge, GraphData
from backend.app.services.ingestion.workspace_manager import WorkspaceManager

class TestPydanticV2Regression(unittest.TestCase):
    def test_graph_data_serialization_model_dump_json(self):
        nodes = [
            GraphNode(id="prog_1", label="MAIN", type="Program", file_id="f1", properties={"loc": 100}),
            GraphNode(id="var_1", label="WS-TOTAL", type="DataItem", file_id="f1", properties={"pic": "9(5)V99"})
        ]
        edges = [
            GraphEdge(id="e1", source="prog_1", target="var_1", type="DEFINES", properties={})
        ]
        graph = GraphData(nodes=nodes, edges=edges)

        # Ensure model_dump_json completes without error
        json_str = graph.model_dump_json(indent=2) if hasattr(graph, "model_dump_json") else graph.json()
        self.assertIsInstance(json_str, str)
        self.assertIn("prog_1", json_str)
        self.assertIn("var_1", json_str)
        self.assertIn("DEFINES", json_str)

        # Ensure valid JSON and reloadable
        parsed = json.loads(json_str)
        self.assertEqual(len(parsed["nodes"]), 2)
        self.assertEqual(len(parsed["edges"]), 1)

    def test_workspace_analysis_saves_and_reloads_graph(self):
        cobol = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SER-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-VAR PIC 9(4) VALUE 10.
       PROCEDURE DIVISION.
       000-MAIN.
           STOP RUN.
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            wm = WorkspaceManager(Path(tmpdir))
            pid = wm.create_project("SerTest")
            wm.save_file(pid, "TEST.cob", cobol, "SOURCE")

            # This invokes analyze_and_index_project, which previously failed on graph.json(indent=2)
            summary = wm.analyze_and_index_project(pid)
            self.assertEqual(summary.index_status, "INDEXED")
            self.assertEqual(summary.files_detected, 1)

            # Verify saved dependency_graph.json
            pdir = wm.get_project_dir(pid)
            graph_file = pdir / "graph" / "dependency_graph.json"
            self.assertTrue(graph_file.exists())

            with open(graph_file, "r", encoding="utf-8") as f:
                saved_data = json.load(f)

            self.assertIn("nodes", saved_data)
            self.assertIn("edges", saved_data)
            self.assertTrue(len(saved_data["nodes"]) >= 2)

if __name__ == "__main__":
    unittest.main()
