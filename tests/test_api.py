"""API tests on a synthetic project (no network, no WolfTL)."""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

# Must be set before anything imports config, so tests never touch real data.
_DATA = tempfile.mkdtemp(prefix="nelir_api_")
os.environ["NELIR_DATA_DIR"] = _DATA

from test_core import make_dump  # noqa: E402

_PROJ = os.path.join(_DATA, "projects", "demo")
os.makedirs(_PROJ)
make_dump(os.path.join(_PROJ, "dump_original"))
with open(os.path.join(_PROJ, "project.json"), "w", encoding="utf-8") as f:
    json.dump({"id": "demo", "name": "Demo", "game_path": "", "game_data_path": ""}, f)

import config  # noqa: E402
config.DATA_DIR = _DATA  # in case config was imported earlier by another test module
config.PROJECTS_DIR = os.path.join(_DATA, "projects")
config.GLOBAL_DB_PATH = os.path.join(_DATA, "global_settings.db")

from fastapi.testclient import TestClient  # noqa: E402

import bridge as bridge_mod  # noqa: E402
import server  # noqa: E402

server.bridge = bridge_mod.WolfBridge(_DATA)


def tearDownModule():
    shutil.rmtree(_DATA, ignore_errors=True)


class TestApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def test_stats_scoped_by_file(self):
        all_stats = self.client.get("/api/stats").json()
        map_stats = self.client.get("/api/stats", params={"file": os.path.join("mps", "Map001.json")}).json()
        self.assertGreater(all_stats["total"], map_stats["total"])
        self.assertEqual(map_stats["total"], 2)

    def test_rows_filter_by_type(self):
        rows = self.client.post("/api/rows", json={"row_type": "Choice"}).json()["rows"]
        self.assertEqual([r["raw"] for r in rows], ["はい"])

    def test_context_returns_neighbours_in_same_file(self):
        rows = self.client.post("/api/rows", json={"file": os.path.join("common", "0_test.json")}).json()["rows"]
        mid = rows[2]
        ctx = self.client.get(f"/api/rows/{mid['id']}/context", params={"n": 1}).json()
        self.assertEqual(ctx["row"]["id"], mid["id"])
        self.assertEqual([r["id"] for r in ctx["before"]], [rows[1]["id"]])
        self.assertEqual([r["id"] for r in ctx["after"]], [rows[3]["id"]])
        self.assertEqual(self.client.get("/api/rows/999999/context").status_code, 404)

    def test_files_have_review_counts(self):
        files = self.client.get("/api/files").json()
        self.assertTrue(all({"reviewed", "qa", "translatable"} <= set(f) for f in files))


if __name__ == "__main__":
    unittest.main()
