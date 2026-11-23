"""Exercise the loopback API, host checks, data boundary, and cancel endpoint."""
import json
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from fabintel.server import LocalServer

ROOT = Path(__file__).resolve().parent.parent


class OfflineServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo = json.loads((ROOT / "fixtures" / "full_workflow_demo.json").read_text())

    def setUp(self):
        self.server = LocalServer(0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.jobs.stop_all()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def get_json(self, url):
        with urlopen(url, timeout=5) as response:
            return response.status, json.loads(response.read())

    def post_json(self, url, data, extra_headers=None):
        headers = {"Content-Type": "application/json"}
        headers.update(extra_headers or {})
        req = Request(url, data=json.dumps(data).encode(), headers=headers, method="POST")
        with urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read())

    def test_ui_health_preflight_and_complete_job(self):
        with urlopen(self.base + "/", timeout=5) as response:
            html = response.read().decode()
            self.assertEqual(response.status, 200)
            self.assertIn("Load synthetic walkthrough", html)
            self.assertIn("Content-Security-Policy", response.headers)
        _, health = self.get_json(self.base + "/api/health")
        self.assertEqual(health["mode"], "SYNTHETIC_DEMO")
        _, started = self.post_json(self.base + "/api/jobs", self.demo)
        deadline = time.time() + 5
        while time.time() < deadline:
            _, job = self.get_json(self.base + started["poll"])
            if job["status"] != "RUNNING":
                break
            time.sleep(0.02)
        self.assertEqual(job["status"], "COMPLETED")
        dossier = job["result"]["artifacts"][0]
        self.assertEqual(dossier["D01_sensitivity"]["status"], "VALID")
        self.assertEqual(dossier["D03_tradeoffs"]["status"], "VALID")
        self.assertEqual(dossier["D04_experiment_proposal"]["executed"], False)

    def test_host_and_origin_rejection(self):
        req = Request(self.base + "/api/health", headers={"Host": "untrusted.example"})
        with self.assertRaises(HTTPError) as host_error:
            urlopen(req, timeout=5)
        self.assertEqual(host_error.exception.code, 421)
        req = Request(self.base + "/api/health", headers={"Origin": "http://untrusted.example"})
        with self.assertRaises(HTTPError) as origin_error:
            urlopen(req, timeout=5)
        self.assertEqual(origin_error.exception.code, 403)

    def test_cancel_endpoint_stops_large_local_job(self):
        started_analyze = threading.Event()

        def cancellable_analysis(_payload, cancel=None):
            started_analyze.set()
            deadline = time.time() + 5
            while time.time() < deadline and not cancel():
                time.sleep(0.005)
            return {"status": "REFUSED", "claims": [], "artifacts": []}

        with patch("fabintel.server.analyze", side_effect=cancellable_analysis):
            _, started = self.post_json(self.base + "/api/jobs", self.demo)
            self.assertTrue(started_analyze.wait(2), "analysis worker did not start")
            req = Request(self.base + f"/api/jobs/{started['job_id']}/cancel", data=b"", method="POST")
            with urlopen(req, timeout=5) as response:
                cancel = json.loads(response.read())
            self.assertTrue(cancel["cancel_requested"])
            deadline = time.time() + 5
            while time.time() < deadline:
                _, job = self.get_json(self.base + started["poll"])
                if job["status"] != "RUNNING":
                    break
                time.sleep(0.01)
            self.assertEqual(job["status"], "CANCELED")
            self.assertEqual(job["result"]["status"], "REFUSED")


if __name__ == "__main__":
    unittest.main()
