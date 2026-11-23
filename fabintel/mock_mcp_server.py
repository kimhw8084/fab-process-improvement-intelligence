"""Synthetic MCP 2025-11-25 server for offline transport qualification.

Every tool, source, row, and semantic identifier here is explicitly synthetic.
Run as ``python -m fabintel.mock_mcp_server --transport stdio`` or ``--transport http``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


VERSION = "2025-11-25"
SCENARIO = "normal"
TOOLS = [
    {"name": "synthetic.test.discover", "description": "Synthetic capabilities only", "inputSchema": {"type": "object", "properties": {"permission_scope": {"type": "string"}}, "required": ["permission_scope"]}},
    {"name": "synthetic.test.semantics", "description": "Synthetic semantic catalog", "inputSchema": {"type": "object", "properties": {"source_ids": {"type": "array"}, "semantic_version": {"type": "string"}}}},
    {"name": "synthetic.test.relationships", "description": "Synthetic relationship catalog", "inputSchema": {"type": "object", "properties": {"typed_entity_ids": {"type": "array"}, "time_window": {"type": "object"}}}},
    {"name": "synthetic.test.read_bounded", "description": "Synthetic bounded read", "annotations": {"readOnlyHint": True, "destructiveHint": False}, "inputSchema": {"type": "object", "properties": {"approved_plan": {"type": "object"}, "permission_context": {"type": "object"}, "limits": {"type": "object"}}}},
    {"name": "synthetic.test.cancel", "description": "Synthetic cancellation status", "inputSchema": {"type": "object", "properties": {"operation_id": {"type": "string"}}}},
    {"name": "synthetic.test.audit", "description": "Synthetic audit metadata", "inputSchema": {"type": "object", "properties": {"operation_id": {"type": "string"}}}},
]


class RpcFailure(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def _tool_result(name, args, scenario="normal"):
    if not isinstance(args, dict):
        raise RpcFailure(-32602, "arguments must be an object")
    if name == "synthetic.test.discover":
        result = {"tool_versions": {tool["name"]: "SYNTHETIC-1" for tool in TOOLS},
                  "semantic_versions": ["SYNTHETIC-SEMANTICS-1"],
                  "limits": {"max_rows": 1000, "max_seconds": 30},
                  "auth_scopes": (["SYNTHETIC_TEST_ONLY"] if scenario == "permission_denied" else ["SYNTHETIC_READ"]),
                  "audit_support": True}
    elif name == "synthetic.test.semantics":
        sources = args.get("source_ids", [])
        if not isinstance(sources, list) or any(source not in ("SYN-SOURCE-A", "SYN-SOURCE-B") for source in sources):
            raise RpcFailure(-32001, "synthetic source is not approved")
        columns = [
            {"name": "row_id", "type": "string", "unit": "SYNTHETIC-ID"},
            {"name": "unit_id", "type": "string", "unit": "SYNTHETIC-ID"},
            {"name": "lot_id", "type": "string", "unit": "SYNTHETIC-ID"},
            {"name": "wafer_id", "type": "string", "unit": "SYNTHETIC-ID"},
            {"name": "chamber", "type": "string", "unit": "SYNTHETIC-ID"},
            {"name": "analysis_partition", "type": "string", "unit": "SYNTHETIC-ID"},
            {"name": "upstream_unit_id", "type": "string", "unit": "SYNTHETIC-ID"},
            {"name": "downstream_unit_id", "type": "string", "unit": "SYNTHETIC-ID"},
            {"name": "event_ts", "type": "string", "unit": "UTC-ISO8601"},
            {"name": "upstream_event_ts", "type": "string", "unit": "UTC-ISO8601"},
            {"name": "downstream_event_ts", "type": "string", "unit": "UTC-ISO8601"},
            {"name": "population_id", "type": "string", "unit": "SYNTHETIC-ID"},
            {"name": "x", "type": "number", "unit": "SYNTHETIC-U"},
            {"name": "y", "type": "number", "unit": "SYNTHETIC-U"},
            {"name": "pressure", "type": "number", "unit": "SYNTHETIC-PRESSURE"},
            {"name": "temperature", "type": "number", "unit": "SYNTHETIC-TEMPERATURE"},
            {"name": "response_primary", "type": "number", "unit": "SYNTHETIC-INDEX"},
            {"name": "response_secondary", "type": "number", "unit": "SYNTHETIC-INDEX"},
            {"name": "synthetic_value", "type": "number", "unit": "SYNTHETIC-U"},
        ]
        if scenario == "semantic_schema_drift":
            columns = [column for column in columns if column["name"] != "response_primary"]
        result = {"column_definitions": columns,
                  "grain": "one row per synthetic process observation",
                  "units": {"synthetic_value": "SYNTHETIC-U", "x": "SYNTHETIC-U", "y": "SYNTHETIC-U",
                            "pressure": "SYNTHETIC-PRESSURE", "temperature": "SYNTHETIC-TEMPERATURE",
                            "response_primary": "SYNTHETIC-INDEX", "response_secondary": "SYNTHETIC-RATE"},
                  "effectivity": {"start": "2026-01-01T00:00:00Z", "end": None}, "approval": "SYNTHETIC-APPROVAL",
                  "semantic_version": "SYNTHETIC-SEMANTICS-1",
                  "source_versions": {source: "SYN-SOURCE-V1" for source in sources}}
        if scenario == "missing_semantic_evidence":
            result.pop("semantic_version")
        if scenario == "missing_semantic_source_versions":
            result.pop("source_versions")
    elif name == "synthetic.test.relationships":
        ids = args.get("typed_entity_ids", [])
        if not isinstance(ids, list) or any(source not in ("SYN-SOURCE-A", "SYN-SOURCE-B") for source in ids):
            raise RpcFailure(-32001, "synthetic entity is not approved")
        upstream, downstream = (ids + ["SYN-SOURCE-A", "SYN-SOURCE-B"])[:2]
        relationship_contract = {"approved": True, "relationship_id": "SYN-RELATIONSHIP-1",
            "contract_version": "1.0.0", "approval_reference": "SYN-RELATIONSHIP-APPROVAL-1",
            "upstream": {"source_id": upstream, "key_field": "upstream_unit_id", "event_time_field": "upstream_event_ts",
                         "population_field": "population_id", "population_id": "SYNTHETIC-POPULATION-1",
                         "metric_field": "response_primary", "metric": "quality"},
            "downstream": {"source_id": downstream, "key_field": "downstream_unit_id", "event_time_field": "downstream_event_ts",
                           "population_field": "population_id", "population_id": "SYNTHETIC-POPULATION-1",
                           "metric_field": "response_secondary", "metric": "secondary_quality"},
            "maximum_lag_seconds": 3600, "unit_field": "unit_id", "decision_factors": ["pressure"]}
        result = {"approved": scenario != "relationship_unapproved", "keys": {"upstream": "upstream_unit_id", "downstream": "downstream_unit_id"},
                  "cardinality": "many_to_many" if scenario == "relationship_many_to_many" else "one_to_one",
                  "grain": "one row per synthetic process observation",
                  "effectivity": {"max_lag_seconds": 3600}, "source_reference": "SYN-RELATIONSHIP-1",
                  "relationship_contract": relationship_contract}
        if scenario == "missing_relationship_evidence":
            result.pop("relationship_contract")
    elif name == "synthetic.test.read_bounded":
        limits = args.get("limits", {})
        limit = limits.get("max_rows") if isinstance(limits, dict) else None
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000 or limits.get("read_only") is not True:
            raise RpcFailure(-32001, "read-only limit must be 1..1000")
        planned = args.get("approved_plan", {}).get("synthetic_rows", [])
        if not isinstance(planned, list):
            raise RpcFailure(-32602, "synthetic_rows must be a list")
        selected = planned[:limit]
        source_ids = args.get("approved_plan", {}).get("source_ids", ["SYN-SOURCE-A"])
        versions = {source: ("SYN-SOURCE-DRIFT" if scenario == "source_version_drift" else "SYN-SOURCE-V1")
                    for source in source_ids}
        hashes = {source: hashlib.sha256(json.dumps({"source": source, "rows": selected}, sort_keys=True,
                                                   separators=(",", ":")).encode()).hexdigest()
                  for source in source_ids}
        result = {"typed_rows": selected, "audit_id": "SYN-AUDIT-READ-1",
                  "operation_id": "SYN-OP-READ-1", "source_versions": versions,
                  "source_hashes": hashes,
                  "truncation": len(planned) > limit or scenario == "server_truncated"}
        if scenario == "missing_read_hashes":
            result.pop("source_hashes")
    elif name == "synthetic.test.cancel":
        result = {"confirmed_stopped": args.get("operation_id") == "SYN-OP-STOPPED"}
    elif name == "synthetic.test.audit":
        result = {"permission_scope": "SYNTHETIC_READ", "sources": ["SYN-SOURCE-A", "SYN-SOURCE-B"],
                  "timestamps": {"started": "2026-01-01T00:00:00Z", "ended": "2026-01-01T00:00:01Z"},
                  "query_hash": "invalid" if scenario == "audit_invalid" else "0"*64}
    else:
        raise RpcFailure(-32602, "unknown synthetic test tool")
    return {"structuredContent": result, "content": [{"type": "text", "text": "Synthetic test result; no company data."}]}


def handle(message, *, cursor_pages=True, scenario="normal"):
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        raise RpcFailure(-32600, "invalid JSON-RPC message")
    method, params = message.get("method"), message.get("params", {})
    request_id = message.get("id")
    if method in ("notifications/initialized", "notifications/cancelled", "notifications/progress"):
        return None
    if method == "initialize":
        return {"protocolVersion": VERSION, "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "synthetic-p4-mock-mcp", "version": "1.0.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        cursor = params.get("cursor") if isinstance(params, dict) else None
        if cursor_pages:
            if cursor is None:
                return {"tools": TOOLS[:3], "nextCursor": "synthetic-page-2"}
            if cursor == "synthetic-page-2":
                return {"tools": TOOLS[3:]}
            raise RpcFailure(-32602, "unknown pagination cursor")
        return {"tools": TOOLS}
    if method == "tools/call":
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            raise RpcFailure(-32602, "tools/call requires a tool name")
        return _tool_result(params["name"], params.get("arguments", {}), scenario)
    raise RpcFailure(-32601, "method not found")


def _rpc(message, *, scenario="normal"):
    request_id = message.get("id") if isinstance(message, dict) else None
    try:
        result = handle(message, scenario=scenario)
        if request_id is None:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except RpcFailure as exc:
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": exc.code, "message": exc.message}}


def stdio():
    for raw in sys.stdin.buffer:
        if len(raw) > 4*1024*1024:
            break
        try:
            message = json.loads(raw)
            response = _rpc(message, scenario=SCENARIO)
            if response is not None:
                sys.stdout.write(json.dumps(response, separators=(",", ":"), allow_nan=False)+"\n")
                sys.stdout.flush()
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    sessions = set()

    def log_message(self, _fmt, *_args):
        return

    def _reply(self, status, data=b"", content_type="application/json", extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if data:
            self.wfile.write(data)

    def do_POST(self):
        if self.path != "/mcp":
            self._reply(404, b"not found", "text/plain")
            return
        version = self.headers.get("MCP-Protocol-Version")
        session = self.headers.get("Mcp-Session-Id")
        length = self.headers.get("Content-Length", "")
        if not length.isdigit() or int(length) > 4*1024*1024:
            self._reply(413, b"request too large", "text/plain")
            return
        try:
            message = json.loads(self.rfile.read(int(length)))
        except json.JSONDecodeError:
            self._reply(400, b"invalid JSON", "text/plain")
            return
        if message.get("method") == "initialize":
            session = secrets.token_urlsafe(16)
            self.sessions.add(session)
            extra = {"Mcp-Session-Id": session}
        else:
            extra = {}
            if not session or session not in self.sessions or version != VERSION:
                self._reply(400, b"session or protocol version missing", "text/plain")
                return
        response = _rpc(message, scenario=SCENARIO)
        if response is None:
            self._reply(202, b"", "application/json", extra)
            return
        encoded = json.dumps(response, separators=(",", ":"), allow_nan=False).encode("utf-8")
        wants_sse = "text/event-stream" in self.headers.get("Accept", "")
        if wants_sse:
            encoded = b"event: message\ndata: "+encoded+b"\n\n"
            self._reply(200, encoded, "text/event-stream", extra)
        else:
            self._reply(200, encoded, "application/json", extra)

    def do_DELETE(self):
        session = self.headers.get("Mcp-Session-Id")
        if session:
            self.sessions.discard(session)
        self._reply(204)


class QuietLoopbackHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # Streamable HTTP clients may close an SSE connection after its response.
        # Treat only the resulting transport reset as normal mock-server cleanup.
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


def http(host="127.0.0.1", port=8766):
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise SystemExit("mock MCP HTTP server may bind only to loopback")
    server = QuietLoopbackHTTPServer((host, port), Handler)
    print(f"Synthetic mock MCP listening on {host}:{port}/mcp", file=sys.stderr)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main():
    global SCENARIO
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--scenario", choices=("normal", "permission_denied", "semantic_schema_drift",
        "source_version_drift", "relationship_unapproved", "relationship_many_to_many",
        "server_truncated", "audit_invalid", "missing_semantic_evidence", "missing_semantic_source_versions",
        "missing_relationship_evidence", "missing_read_hashes"), default="normal")
    args = parser.parse_args()
    SCENARIO = args.scenario
    stdio() if args.transport == "stdio" else http(args.host, args.port)


if __name__ == "__main__":
    main()
