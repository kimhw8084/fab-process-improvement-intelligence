"""Synthetic MCP 2025-11-25 server for offline transport qualification.

Every tool, source, row, and semantic identifier here is explicitly synthetic.
Run as ``python -m fabintel.mock_mcp_server --transport stdio`` or ``--transport http``.
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


VERSION = "2025-11-25"
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


def _tool_result(name, args):
    if not isinstance(args, dict):
        raise RpcFailure(-32602, "arguments must be an object")
    if name == "synthetic.test.discover":
        result = {"tool_versions": {tool["name"]: "SYNTHETIC-1" for tool in TOOLS},
                  "semantic_versions": ["SYNTHETIC-SEMANTICS-1"],
                  "limits": {"max_rows": 1000, "max_seconds": 30},
                  "auth_scopes": ["SYNTHETIC_READ"], "audit_support": True}
    elif name == "synthetic.test.semantics":
        sources = args.get("source_ids", [])
        if not isinstance(sources, list) or any(source not in ("SYNTHETIC-SOURCE-A", "SYNTHETIC-SOURCE-B") for source in sources):
            raise RpcFailure(-32001, "synthetic source is not approved")
        result = {"column_definitions": [{"name": "synthetic_value", "type": "number", "unit": "SYNTHETIC-U"}],
                  "grain": "one synthetic unit row", "units": {"synthetic_value": "SYNTHETIC-U"},
                  "effectivity": {"start": "2026-01-01T00:00:00Z", "end": None}, "approval": "SYNTHETIC-APPROVAL"}
    elif name == "synthetic.test.relationships":
        ids = args.get("typed_entity_ids", [])
        if not isinstance(ids, list) or any(source not in ("SYNTHETIC-SOURCE-A", "SYNTHETIC-SOURCE-B") for source in ids):
            raise RpcFailure(-32001, "synthetic entity is not approved")
        result = {"approved": True, "keys": {"upstream": "synthetic_unit_id", "downstream": "synthetic_unit_id"},
                  "cardinality": "one_to_one", "grain": "one synthetic unit row",
                  "effectivity": {"max_lag_seconds": 86400}, "source_reference": "SYNTHETIC-RELATION-1"}
    elif name == "synthetic.test.read_bounded":
        limits = args.get("limits", {})
        limit = limits.get("max_rows") if isinstance(limits, dict) else None
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000 or limits.get("read_only") is not True:
            raise RpcFailure(-32001, "read-only limit must be 1..1000")
        planned = args.get("approved_plan", {}).get("synthetic_rows", [])
        if not isinstance(planned, list):
            raise RpcFailure(-32602, "synthetic_rows must be a list")
        result = {"typed_rows": planned[:limit], "audit_id": "SYN-AUDIT-READ-1",
                  "source_versions": {"SYNTHETIC-SOURCE-A": "SYNTHETIC-1"}, "truncation": len(planned) > limit}
    elif name == "synthetic.test.cancel":
        result = {"confirmed_stopped": args.get("operation_id") == "SYN-OP-STOPPED"}
    elif name == "synthetic.test.audit":
        result = {"permission_scope": "SYNTHETIC_READ", "sources": ["SYNTHETIC-SOURCE-A"],
                  "timestamps": {"started": "2026-01-01T00:00:00Z", "ended": "2026-01-01T00:00:01Z"},
                  "query_hash": "0"*64}
    else:
        raise RpcFailure(-32602, "unknown synthetic test tool")
    return {"structuredContent": result, "content": [{"type": "text", "text": "Synthetic test result; no company data."}]}


def handle(message, *, cursor_pages=True):
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
        return _tool_result(params["name"], params.get("arguments", {}))
    raise RpcFailure(-32601, "method not found")


def _rpc(message):
    request_id = message.get("id") if isinstance(message, dict) else None
    try:
        result = handle(message)
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
            response = _rpc(message)
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
        response = _rpc(message)
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    stdio() if args.transport == "stdio" else http(args.host, args.port)


if __name__ == "__main__":
    main()
