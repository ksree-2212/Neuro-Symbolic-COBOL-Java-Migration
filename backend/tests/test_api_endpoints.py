import io
import unittest
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.db.database import init_db

SAMPLE_COBOL = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. API-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-AMOUNT PIC 9(5)V99 VALUE 100.00.
       01 WS-TOTAL  PIC 9(5)V99 VALUE 0.00.
       PROCEDURE DIVISION.
       000-MAIN.
           COMPUTE WS-TOTAL = WS-AMOUNT * 1.08.
           STOP RUN.
"""

class TestFastAPIEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)

    def test_toolchain_status_endpoint(self):
        res = self.client.get("/api/toolchain/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("available", data)
        self.assertIn("status_message", data)
        self.assertIn("details", data)

    def test_capability_matrix_endpoint(self):
        res = self.client.get("/api/capability-matrix")
        self.assertEqual(res.status_code, 200)
        matrix = res.json()
        self.assertTrue(len(matrix) > 0)
        features = [m["feature"] for m in matrix]
        self.assertIn("IF / ELSE", features)
        self.assertIn("COMPUTE", features)
        self.assertIn("COPYBOOK", features)

    def test_project_lifecycle_api(self):
        # 1. Create project
        create_res = self.client.post("/api/projects", json={"name": "LifecycleApp", "source_language": "COBOL", "target_language": "Java"})
        self.assertEqual(create_res.status_code, 200)
        proj_data = create_res.json()
        pid = proj_data["project_id"]
        self.assertIsNotNone(pid)

        # 2. Get project details
        get_res = self.client.get(f"/api/projects/{pid}")
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.json()["name"], "LifecycleApp")

        # 3. Upload COBOL file
        file_bytes = SAMPLE_COBOL.encode("utf-8")
        files = [("files", ("API_TEST.cob", io.BytesIO(file_bytes), "text/plain"))]
        upload_res = self.client.post(f"/api/projects/{pid}/upload", files=files, data={"file_type": "SOURCE"})
        self.assertEqual(upload_res.status_code, 200)
        self.assertEqual(upload_res.json()["count"], 1)

        # 4. List files
        list_files_res = self.client.get(f"/api/projects/{pid}/files")
        self.assertEqual(list_files_res.status_code, 200)
        self.assertEqual(len(list_files_res.json()), 1)

        # 5. Analyze project
        analyze_res = self.client.post(f"/api/projects/{pid}/analyze")
        self.assertEqual(analyze_res.status_code, 200)
        summary = analyze_res.json()
        self.assertEqual(summary["index_status"], "INDEXED")
        self.assertEqual(summary["programs"], 1)

        # 6. Retrieve AST
        ast_res = self.client.get(f"/api/projects/{pid}/ast")
        self.assertEqual(ast_res.status_code, 200)
        self.assertTrue(len(ast_res.json()) > 0)

        # 7. Retrieve Graph
        graph_res = self.client.get(f"/api/projects/{pid}/graph")
        self.assertEqual(graph_res.status_code, 200)
        graph = graph_res.json()
        self.assertTrue(len(graph["nodes"]) > 0)

        # 8. Hybrid Retrieval
        ret_res = self.client.post(f"/api/projects/{pid}/retrieve?query=tax%20computation")
        self.assertEqual(ret_res.status_code, 200)
        ret_data = ret_res.json()
        self.assertIn("inspection", ret_data)

        # 9. Offline Translation & Migration
        mig_res = self.client.post(f"/api/projects/{pid}/migrate", json={
            "project_id": pid,
            "target_mode": "MODULE",
            "target_name": "API-TEST",
            "query": "total computation",
            "top_k": 3,
            "graph_hops": 2,
            "max_repair_attempts": 1,
            "baseline": False
        })
        self.assertEqual(mig_res.status_code, 200)
        mig_data = mig_res.json()
        self.assertIn("final_status", mig_data)
        self.assertTrue(len(mig_data["generated_files"]) > 0)
        self.assertTrue(any(f["path"].endswith(".java") for f in mig_data["generated_files"]))

if __name__ == "__main__":
    unittest.main()
