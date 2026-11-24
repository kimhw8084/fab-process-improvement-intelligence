"""Loopback-only standalone P4 workbench and API.

It operates on user-supplied files and the bundled synthetic example. Network
acquisition is unavailable unless an explicit, separately qualified adapter
configuration is supplied at launch.
"""
from __future__ import annotations

import json
from pathlib import Path
import threading
import time
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from products.p4.engine import AnalysisCancelled, analyze

MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_ACTIVE_JOBS = 2
MAX_RETAINED_JOBS = 16
UI_ROOT = Path(__file__).resolve().parent.parent / "products" / "p4" / "ui" / "standalone"
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
UI_ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
             "/ui/app.js": ("app.js", "text/javascript; charset=utf-8"),
             "/ui/mcp.css": ("mcp.css", "text/css; charset=utf-8"),
             "/ui/styles.css": ("styles.css", "text/css; charset=utf-8")}


class JobStore:
    def __init__(self):
        self.lock = threading.RLock()
        self.jobs = {}

    def start(self, payload, runner=None):
        with self.lock:
            active = sum(job["status"] == "RUNNING" for job in self.jobs.values())
            if active >= MAX_ACTIVE_JOBS:
                raise RuntimeError("analysis capacity is full; retry when a running job finishes")
            while len(self.jobs) >= MAX_RETAINED_JOBS:
                old_id, old = next(iter(self.jobs.items()))
                if old["status"] == "RUNNING":
                    raise RuntimeError("job history is full; wait for active work to finish")
                del self.jobs[old_id]
            job_id = secrets.token_urlsafe(18)
            job = {"status": "RUNNING", "cancel": threading.Event(), "result": None,
                   "started_at": time.time(), "finished_at": None}
            self.jobs[job_id] = job
            worker = threading.Thread(target=self._run, args=(job_id, payload, runner), daemon=True,
                                      name="fabintel-analysis")
            worker.start()
            return job_id

    def _run(self, job_id, payload, runner=None):
        with self.lock:
            job = self.jobs[job_id]
            cancel = job["cancel"]
        try:
            result = (runner or analyze)(payload, cancel=cancel.is_set)
            with self.lock:
                job = self.jobs.get(job_id)
                if job is None:
                    return
                job["result"] = result
                job["status"] = "CANCELED" if cancel.is_set() and result["status"] == "REFUSED" else "COMPLETED"
                job["finished_at"] = time.time()
        except Exception as exc:  # Keep failures visible without returning stack traces or input data.
            with self.lock:
                job = self.jobs.get(job_id)
                if job is not None:
                    job["status"] = "ERROR"
                    job["error"] = type(exc).__name__
                    job["finished_at"] = time.time()

    def snapshot(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            return {k: job.get(k) for k in ("status", "result", "error", "started_at", "finished_at")}

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None or job["status"] != "RUNNING":
                return False
            job["cancel"].set()
            return True

    def stop_all(self):
        with self.lock:
            for job in self.jobs.values():
                if job["status"] == "RUNNING":
                    job["cancel"].set()


def preflight_report():
    return {"status": "PENDING_INTERNAL", "network_requests": 0, "adapter": "synthetic_only",
            "required_logical_operations": ["discover", "semantics", "relationships", "read_bounded", "cancel", "audit"],
            "configurable_mcp_transport": {"transports": ["stdio", "streamable_http"],
                "external_mock_command": "python -m fabintel mcp-test",
                "site_qualification_command": "python -m fabintel site-mcp-qualify --config <site-config> --site-approval-reference <approved-ref> --authorized-site-test"},
            "reasons": ["No approved Fab Insight MCP capability report or connector is available in this package.",
                        "Actual host, authentication, approved source semantics, tool names, permissions, and relationships require site-side configuration and qualification."]}


def _mcp_state(server):
    config = server.mcp_config
    if not isinstance(config, dict):
        return {"state": "NOT_CONFIGURED", "enabled": False,
                "message": "No MCP configuration is loaded; a site owner must configure and review one before acquisition. Local file analysis remains available."}
    from fabintel.site_config import validate_site_config
    validation = validate_site_config(config)
    if not validation["p4_workflow_ready"]:
        return {"state": "CONFIGURATION_REPAIR_REQUIRED", "enabled": False,
                "message": "The loaded site configuration is incomplete or inconsistent; run mcp-config-validate before acquisition."}
    profile = config.get("p4_profile")
    environment = config.get("environment")
    qualified = (environment == "INTERNAL_APPROVED_ONLY"
                 and config.get("qualification_status") == "QUALIFIED_INTERNAL"
                 and bool(str(config.get("site_approval_reference", "")).strip()))
    synthetic_enabled = environment == "SYNTHETIC_TEST_ONLY" and server.allow_synthetic_mcp_test
    enabled = bool(isinstance(profile, dict) and (qualified or synthetic_enabled))
    return {"state": "READY" if enabled else "PENDING_INTERNAL", "enabled": enabled,
            "environment": environment, "qualification_status": config.get("qualification_status"),
            "message": ("Site-qualified, bounded read-only MCP profile is configured." if qualified else
                        "Synthetic test profile is explicitly enabled." if synthetic_enabled else
                        "A site owner must approve, configure, and qualify the MCP mapping and P4 analysis profile."),
            "source_count": len(config.get("approved_source_ids", [])) if enabled else 0}


def _mcp_request(config):
    profile = config.get("p4_profile") if isinstance(config, dict) else None
    if not isinstance(profile, dict):
        raise ValueError("site config is missing an explicit p4_profile")
    source_ids = config.get("approved_source_ids")
    if not isinstance(source_ids, list) or not source_ids:
        raise ValueError("configured source allowlist is empty")
    return {"approved_source_ids": source_ids,
            "semantic_version": profile.get("semantic_version"),
            "permission_scope": profile.get("permission_scope"),
            "time_window": profile.get("time_window"),
            "approved_plan": profile.get("approved_plan"),
            "permission_context": profile.get("permission_context"),
            "max_rows": profile.get("max_rows"),
            "normalization": profile.get("normalization"),
            "analysis_template": profile.get("analysis_template")}


class Handler(BaseHTTPRequestHandler):
    server_version = "FabIntelOffline/1.0"
    sys_version = ""

    def log_message(self, fmt, *args):
        # Query content, local input and source identifiers never enter access logs.
        return

    def _headers(self, content_type, length):
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")

    def _json(self, status, value):
        body = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.send_response(status)
        self._headers("application/json; charset=utf-8", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _local_request(self):
        expected_host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host", "").lower() != expected_host:
            self._json(421, {"error": "local host mismatch"})
            return False
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{expected_host}":
            self._json(403, {"error": "cross-origin requests are not accepted"})
            return False
        return True

    def _read_json(self):
        raw_length = self.headers.get("Content-Length", "")
        if not raw_length.isdigit():
            raise ValueError("Content-Length is required")
        length = int(raw_length)
        if length < 1 or length > MAX_REQUEST_BYTES:
            raise ValueError(f"request body must be 1..{MAX_REQUEST_BYTES} bytes")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("request JSON must be an object")
        return value

    def do_GET(self):
        if not self._local_request():
            return
        path = urlsplit(self.path).path
        if path in UI_ASSETS:
            name, mime = UI_ASSETS[path]
            body = (UI_ROOT / name).read_bytes()
            self.send_response(200)
            self._headers(mime, len(body))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/health":
            self._json(200, {"state": "CANDIDATE", "product": "p4", "network": "loopback-only", "mode": "SYNTHETIC_DEMO", "ui": "standalone"})
        elif path == "/api/preflight":
            self._json(200, preflight_report())
        elif path == "/api/mcp/status":
            self._json(200, _mcp_state(self.server))
        elif path == "/api/demo":
            body = (FIXTURES / "full_workflow_demo.json").read_bytes()
            self.send_response(200)
            self._headers("application/json; charset=utf-8", len(body))
            self.end_headers()
            self.wfile.write(body)
        elif path.startswith("/api/jobs/"):
            job_id = path.removeprefix("/api/jobs/")
            snapshot = self.server.jobs.snapshot(job_id)
            self._json(200 if snapshot else 404, snapshot or {"error": "unknown job"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._local_request():
            return
        path = urlsplit(self.path).path
        if path == "/api/jobs":
            try:
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("Content-Type must be application/json")
                payload = self._read_json()
                job_id = self.server.jobs.start(payload)
                self._json(202, {"job_id": job_id, "status": "RUNNING", "poll": f"/api/jobs/{job_id}"})
            except RuntimeError as exc:
                self._json(429, {"error": str(exc)})
            except (ValueError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})
        elif path == "/api/mcp-jobs":
            try:
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("Content-Type must be application/json")
                if not self._read_json() == {}:
                    raise ValueError("MCP acquisition inputs are controlled by the reviewed site configuration")
                status = _mcp_state(self.server)
                if not status["enabled"]:
                    self._json(403, {"error": status["message"]})
                    return
                from fabintel.mcp_client import configured_adapter
                from products.p4.mcp_workflow import run_mcp_investigation
                config = self.server.mcp_config
                def acquire(_unused, cancel):
                    adapter = configured_adapter(config,
                        allow_synthetic_test=self.server.allow_synthetic_mcp_test)
                    try:
                        return run_mcp_investigation(adapter, _mcp_request(config), cancel=cancel)
                    finally:
                        adapter.client.close()
                job_id = self.server.jobs.start({}, runner=acquire)
                self._json(202, {"job_id": job_id, "status": "RUNNING", "poll": f"/api/jobs/{job_id}"})
            except RuntimeError as exc:
                self._json(429, {"error": str(exc)})
            except (ValueError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:
                self._json(400, {"error": f"MCP acquisition could not start ({type(exc).__name__})"})
        elif path.startswith("/api/jobs/") and path.endswith("/cancel"):
            job_id = path[len("/api/jobs/"):-len("/cancel")].strip("/")
            accepted = self.server.jobs.cancel(job_id)
            self._json(200 if accepted else 409, {"cancel_requested": accepted,
                                                   "status": "CANCEL_REQUESTED" if accepted else "NOT_RUNNING"})
        else:
            self._json(404, {"error": "not found"})


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, port, *, mcp_config=None, allow_synthetic_mcp_test=False):
        super().__init__(("127.0.0.1", port), Handler)
        self.jobs = JobStore()
        self.mcp_config = mcp_config
        self.allow_synthetic_mcp_test = bool(allow_synthetic_mcp_test)


def serve(port=8765, *, mcp_config=None, allow_synthetic_mcp_test=False):
    server = LocalServer(port, mcp_config=mcp_config,
                         allow_synthetic_mcp_test=allow_synthetic_mcp_test)
    print(f"P4 standalone offline workbench: http://127.0.0.1:{port}/")
    print("Loopback only; local analysis and bundled synthetic example. Ctrl-C stops local jobs.")
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("Stopping; requesting cancellation for active analyses.")
    finally:
        server.jobs.stop_all()
        server.shutdown()
        server.server_close()
