"""Configurable MCP 2025-11-25 client and fail-closed semantic mapping adapter.

No site names, tool names, source semantics, or grants are embedded here. The
transport is exercised only against the synthetic local mock in this package.
"""
from __future__ import annotations

import json
import os
import queue
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


PROTOCOL_VERSION = "2025-11-25"
MAX_RPC_BYTES = 4 * 1024 * 1024
MAX_TOOLS = 10_000


class McpError(RuntimeError):
    pass


class McpPermissionError(PermissionError):
    pass


def _json_bytes(value):
    try:
        encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise McpError("MCP payload must be finite JSON") from exc
    if len(encoded) > MAX_RPC_BYTES:
        raise McpError("MCP payload exceeds the configured 4 MiB limit")
    return encoded


def _is_loopback(host):
    if host == "localhost":
        return True
    try:
        return socket.getaddrinfo(host, None)[0][4][0].startswith(("127.", "::1"))
    except OSError:
        return False


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class StreamableHttpTransport:
    """MCP Streamable HTTP over a single configured endpoint, no redirects."""
    def __init__(self, endpoint, *, allowed_hosts, timeout_seconds=10, bearer_token_env=None):
        parsed = urlsplit(endpoint)
        if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise McpError("MCP endpoint must be an absolute HTTP(S) URL without embedded credentials or fragments")
        if not isinstance(allowed_hosts, list) or not allowed_hosts or any(not isinstance(host, str) or not host for host in allowed_hosts):
            raise McpError("an explicit exact allowed_hosts list is required")
        if parsed.hostname.lower() not in {host.lower() for host in allowed_hosts}:
            raise McpPermissionError("MCP endpoint host is not in the exact configured allowlist")
        if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
            raise McpPermissionError("cleartext HTTP is allowed only for loopback test servers")
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or not 0 < timeout_seconds <= 30:
            raise McpError("MCP HTTP timeout must be in (0, 30] seconds")
        self.endpoint = endpoint
        self.timeout_seconds = float(timeout_seconds)
        self.token = None
        if bearer_token_env:
            if not isinstance(bearer_token_env, str) or not bearer_token_env:
                raise McpError("bearer_token_env must be a variable name")
            self.token = os.environ.get(bearer_token_env)
            if not self.token:
                raise McpPermissionError("the configured bearer token environment variable is unset")
        self.opener = build_opener(_NoRedirect())
        self.session_id = None

    def request(self, message, *, initialized=False, timeout=None):
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if initialized:
            headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
            if self.session_id:
                headers["Mcp-Session-Id"] = self.session_id
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(self.endpoint, data=_json_bytes(message), headers=headers, method="POST")
        try:
            response = self.opener.open(request, timeout=timeout or self.timeout_seconds)
        except HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                raise McpPermissionError("MCP endpoint redirects are disabled to protect configured credentials") from exc
            exc.read(512)
            raise McpError(f"MCP HTTP server returned status {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise McpError(f"MCP HTTP request failed: {type(exc).__name__}") from exc
        with response:
            body = response.read(MAX_RPC_BYTES+1)
            if len(body) > MAX_RPC_BYTES:
                raise McpError("MCP HTTP response exceeds the configured 4 MiB limit")
            self.session_id = response.headers.get("Mcp-Session-Id", self.session_id)
            content_type = response.headers.get_content_type().lower()
        if content_type == "application/json":
            try:
                parsed = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise McpError("MCP server returned invalid JSON") from exc
            return parsed
        if content_type == "text/event-stream":
            return self._parse_sse(body)
        raise McpError(f"MCP server returned unsupported content type: {content_type}")

    @staticmethod
    def _parse_sse(body):
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise McpError("MCP SSE body is not UTF-8") from exc
        messages = []
        data_lines = []
        for line in text.splitlines()+[""]:
            if not line:
                if data_lines:
                    raw = "\n".join(data_lines)
                    try:
                        messages.append(json.loads(raw))
                    except json.JSONDecodeError as exc:
                        raise McpError("MCP SSE event contains invalid JSON") from exc
                    data_lines = []
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if not messages:
            raise McpError("MCP SSE response contained no JSON-RPC message")
        return messages

    def notify(self, message, *, initialized=False):
        # Notifications have no JSON-RPC response; a 202/204 server response
        # is accepted by a dedicated fire-and-forget POST.
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if initialized:
            headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
            if self.session_id:
                headers["Mcp-Session-Id"] = self.session_id
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(self.endpoint, data=_json_bytes(message), headers=headers, method="POST")
        try:
            response = self.opener.open(request, timeout=self.timeout_seconds)
        except HTTPError as exc:
            raise McpError(f"MCP notification failed with HTTP status {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise McpError(f"MCP notification failed: {type(exc).__name__}") from exc
        with response:
            response.read(512)
            if response.status not in (200, 202, 204):
                raise McpError(f"MCP notification returned unexpected status {response.status}")

    def close(self):
        if not self.session_id:
            return
        headers = {"MCP-Protocol-Version": PROTOCOL_VERSION, "Mcp-Session-Id": self.session_id}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(self.endpoint, headers=headers, method="DELETE")
        try:
            with self.opener.open(request, timeout=min(3.0, self.timeout_seconds)) as response:
                response.read(256)
        except Exception:
            # Session termination is best effort; never hide primary results.
            pass
        self.session_id = None


class StdioTransport:
    """Line-delimited JSON-RPC over a subprocess using MCP stdio framing."""
    def __init__(self, command, *, cwd=None, env_from=None, timeout_seconds=10):
        if not isinstance(command, list) or not command or any(not isinstance(part, str) or not part for part in command):
            raise McpError("stdio MCP command must be an explicit nonempty argument list")
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or not 0 < timeout_seconds <= 30:
            raise McpError("MCP stdio timeout must be in (0, 30] seconds")
        safe_keys = ("PATH", "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "LC_CTYPE",
                     "SYSTEMROOT", "WINDIR", "PATHEXT")
        child_env = {key: os.environ[key] for key in safe_keys if key in os.environ}
        if env_from is not None:
            if (not isinstance(env_from, dict)
                    or any(not isinstance(target, str) or not target or not isinstance(source, str) or not source
                           for target, source in env_from.items())):
                raise McpError("stdio env_from must map child variable names to parent variable names")
            for target, source in env_from.items():
                value = os.environ.get(source)
                if value is None:
                    raise McpPermissionError(f"configured stdio environment source is unset: {source}")
                child_env[target] = value
        try:
            self.process = subprocess.Popen(command, cwd=cwd, env=child_env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, shell=False)
        except OSError as exc:
            raise McpError(f"could not start configured MCP stdio server: {type(exc).__name__}") from exc
        self.timeout_seconds = float(timeout_seconds)
        self.incoming = queue.Queue()
        self.write_lock = threading.Lock()
        self.closed = False
        self.reader = threading.Thread(target=self._read_stdout, daemon=True, name="mcp-stdio-reader")
        self.stderr_reader = threading.Thread(target=self._drain_stderr, daemon=True, name="mcp-stdio-stderr")
        self.reader.start(); self.stderr_reader.start()

    def _read_stdout(self):
        try:
            while True:
                line = self.process.stdout.readline(MAX_RPC_BYTES+2)
                if not line:
                    break
                if len(line) > MAX_RPC_BYTES or not line.endswith(b"\n"):
                    self.incoming.put(McpError("stdio MCP response exceeded the line limit"))
                    break
                try:
                    self.incoming.put(json.loads(line.decode("utf-8")))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self.incoming.put(McpError("stdio MCP stdout must contain only line-delimited JSON-RPC"))
                    break
        finally:
            self.incoming.put(None)

    def _drain_stderr(self):
        while self.process.stderr and self.process.stderr.readline():
            pass

    def _write(self, message):
        encoded = _json_bytes(message)+b"\n"
        with self.write_lock:
            if self.closed or self.process.poll() is not None:
                raise McpError("stdio MCP server process has exited")
            try:
                self.process.stdin.write(encoded)
                self.process.stdin.flush()
            except OSError as exc:
                raise McpError("failed to write MCP stdio message") from exc

    def request(self, message, *, initialized=False, timeout=None):
        self._write(message)
        deadline = time.monotonic()+(timeout or self.timeout_seconds)
        expected_id = message.get("id")
        while True:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise McpError("MCP stdio request timed out")
            try:
                response = self.incoming.get(timeout=remaining)
            except queue.Empty as exc:
                raise McpError("MCP stdio request timed out") from exc
            if response is None:
                raise McpError("MCP stdio server exited before responding")
            if isinstance(response, McpError):
                raise response
            if isinstance(response, dict) and response.get("id") == expected_id:
                return response

    def notify(self, message, *, initialized=False):
        self._write(message)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=2)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass


class McpClient:
    def __init__(self, transport, *, client_name="fabintel-p4", client_version="1.1.0"):
        self.transport = transport
        self.client_name = client_name
        self.client_version = client_version
        self._counter = 0
        self._counter_lock = threading.Lock()
        self._active_lock = threading.Lock()
        self._active_tool_request = None
        self.initialized = False
        self.negotiated_version = None
        self.tools = {}

    def _next_id(self):
        with self._counter_lock:
            self._counter += 1
            return self._counter

    def _rpc(self, method, params=None, *, request_id=None, initialized=None):
        request_id = self._next_id() if request_id is None else request_id
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        result = self.transport.request(message, initialized=self.initialized if initialized is None else initialized)
        responses = result if isinstance(result, list) else [result]
        response = next((item for item in responses if isinstance(item, dict) and item.get("id") == request_id), None)
        if response is None:
            raise McpError(f"MCP response for {method} did not match request id")
        if response.get("jsonrpc") != "2.0":
            raise McpError("MCP response is not JSON-RPC 2.0")
        if "error" in response:
            error = response["error"]
            raise McpError(f"MCP {method} failed ({error.get('code')}): {str(error.get('message', 'remote error'))[:240]}")
        if "result" not in response:
            raise McpError(f"MCP {method} response lacks result")
        return response["result"]

    def initialize(self):
        if self.initialized:
            return {"protocolVersion": self.negotiated_version}
        result = self._rpc("initialize", {"protocolVersion": PROTOCOL_VERSION,
            "capabilities": {}, "clientInfo": {"name": self.client_name, "version": self.client_version}}, initialized=False)
        version = result.get("protocolVersion") if isinstance(result, dict) else None
        if version != PROTOCOL_VERSION:
            raise McpError(f"MCP server negotiated unsupported protocol version: {version}")
        self.negotiated_version = version
        self.transport.notify({"jsonrpc": "2.0", "method": "notifications/initialized"}, initialized=True)
        self.initialized = True
        return result

    def list_tools(self):
        if not self.initialized:
            self.initialize()
        all_tools, cursor, seen_cursors = [], None, set()
        for _ in range(100):
            params = {"cursor": cursor} if cursor else {}
            result = self._rpc("tools/list", params)
            if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
                raise McpError("tools/list must return an object with a tools array")
            all_tools.extend(result["tools"])
            if len(all_tools) > MAX_TOOLS:
                raise McpError("MCP server exceeded the 10000-tool safety bound")
            cursor = result.get("nextCursor")
            if not cursor:
                break
            if not isinstance(cursor, str) or cursor in seen_cursors:
                raise McpError("MCP tools/list pagination cursor is invalid or repeated")
            seen_cursors.add(cursor)
        else:
            raise McpError("MCP tools/list exceeded the 100-page safety bound")
        mapping = {}
        for tool in all_tools:
            if not isinstance(tool, dict) or not isinstance(tool.get("name"), str) or not tool["name"]:
                raise McpError("MCP tool metadata contains an invalid name")
            if tool["name"] in mapping:
                raise McpError("MCP tools/list returned duplicate tool names")
            mapping[tool["name"]] = tool
        self.tools = mapping
        return list(mapping.values())

    def call_tool(self, name, arguments, *, timeout=None):
        if not self.initialized:
            self.initialize()
        if not self.tools:
            self.list_tools()
        if name not in self.tools:
            raise McpError("configured MCP tool name was not returned by tools/list")
        if not isinstance(arguments, dict):
            raise McpError("MCP tool arguments must be an object")
        request_id = self._next_id()
        with self._active_lock:
            self._active_tool_request = request_id
        try:
            result = self._rpc("tools/call", {"name": name, "arguments": arguments}, request_id=request_id)
        finally:
            with self._active_lock:
                if self._active_tool_request == request_id:
                    self._active_tool_request = None
        if not isinstance(result, dict):
            raise McpError("MCP tools/call must return a result object")
        if result.get("isError") is True:
            raise McpError("MCP tool reported an execution error")
        if "structuredContent" in result:
            return result["structuredContent"]
        content = result.get("content", [])
        texts = [item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"]
        if len(texts) == 1:
            try:
                return json.loads(texts[0])
            except json.JSONDecodeError:
                return {"content": content}
        return {"content": content}

    def cancel_current(self, reason="user requested cancellation"):
        with self._active_lock:
            request_id = self._active_tool_request
        if request_id is None:
            return False
        self.transport.notify({"jsonrpc": "2.0", "method": "notifications/cancelled",
                               "params": {"requestId": request_id, "reason": str(reason)[:240]}},
                              initialized=self.initialized)
        return True

    def close(self):
        self.transport.close()


def transport_from_config(config):
    transport = config.get("transport") if isinstance(config, dict) else None
    if not isinstance(transport, dict):
        raise McpError("site config transport must be an object")
    kind = transport.get("type")
    if kind == "stdio":
        cwd = transport.get("cwd")
        if cwd and not Path(cwd).is_absolute() and config.get("_config_dir"):
            cwd = str((Path(config["_config_dir"])/cwd).resolve())
        return StdioTransport(transport.get("command"), cwd=cwd,
                              env_from=transport.get("env_from"), timeout_seconds=transport.get("timeout_seconds", 10))
    if kind == "streamable_http":
        return StreamableHttpTransport(transport.get("endpoint"), allowed_hosts=transport.get("allowed_hosts"),
            timeout_seconds=transport.get("timeout_seconds", 10), bearer_token_env=transport.get("bearer_token_env"))
    raise McpError("transport.type must be stdio or streamable_http")


def load_site_config(path):
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise McpError("site MCP config could not be read as JSON") from exc
    if not isinstance(config, dict) or config.get("config_version") != "1.0.0":
        raise McpError("site MCP config version must be 1.0.0")
    config["_config_dir"] = str(Path(path).resolve().parent)
    return config


class ConfiguredSemanticAdapter:
    """Maps logical operations to explicitly configured discovered MCP tools."""
    def __init__(self, client, config, *, allow_synthetic_test=False, authorized_site_test=False):
        self.client = client
        self.config = config
        env = config.get("environment")
        if env == "SYNTHETIC_TEST_ONLY":
            if not allow_synthetic_test:
                raise McpPermissionError("synthetic MCP test config requires explicit test-only opt-in")
        elif env == "INTERNAL_APPROVED_ONLY":
            if config.get("qualification_status") != "QUALIFIED_INTERNAL" and not authorized_site_test:
                raise McpPermissionError("company MCP adapter is PENDING_INTERNAL until an explicitly authorized site qualification run")
            if not isinstance(config.get("site_approval_reference"), str) or not config["site_approval_reference"].strip():
                raise McpPermissionError("qualified internal config requires an explicit site_approval_reference")
        else:
            raise McpPermissionError("site config environment must be explicitly test-only or internally approved")
        self.source_ids = set(config.get("approved_source_ids", []))
        self.semantic_versions = set(config.get("approved_semantic_versions", []))
        self.operations = config.get("operations", {})
        self.contract = json.loads((Path(__file__).resolve().parent.parent/"contracts"/"adapter-operations.v1.json").read_text(encoding="utf-8"))
        self.contract_ops = {entry["name"]: entry for entry in self.contract["logical_operations"]}
        if not isinstance(self.operations, dict):
            raise McpError("site config operations must be an object")

    @staticmethod
    def _path(value, path):
        current = value
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                raise McpError(f"configured MCP result mapping is missing path: {path}")
            current = current[part]
        return current

    def call(self, operation, payload):
        if operation not in self.contract_ops:
            raise McpError("logical MCP operation is not in the frozen contract")
        if not isinstance(payload, dict):
            raise McpError("logical MCP operation payload must be an object")
        mapping = self.operations.get(operation)
        if not isinstance(mapping, dict) or not isinstance(mapping.get("tool_name"), str):
            raise McpError(f"logical operation {operation} has no explicit site tool mapping")
        if operation == "semantics":
            sources = payload.get("approved_source_ids")
            if not isinstance(sources, list) or any(source not in self.source_ids for source in sources):
                raise McpPermissionError("semantics request includes a source outside the explicit allowlist")
            if payload.get("semantic_version") not in self.semantic_versions:
                raise McpPermissionError("semantics request version is outside the explicit allowlist")
        if operation == "relationships":
            ids = payload.get("typed_entity_ids")
            if not isinstance(ids, list) or any(source not in self.source_ids for source in ids):
                raise McpPermissionError("relationship request includes an entity outside the explicit allowlist")
        if operation == "read_bounded":
            limits = payload.get("limits")
            if not isinstance(payload.get("approved_plan"), dict) or not isinstance(payload.get("permission_context"), dict) or not isinstance(limits, dict):
                raise McpPermissionError("bounded reads require the approved plan, permission context, and limits")
            max_rows = limits.get("max_rows")
            if not isinstance(max_rows, int) or isinstance(max_rows, bool) or not 1 <= max_rows <= 1000:
                raise McpPermissionError("bounded read limit must be an integer from 1 to 1000")
            if limits.get("read_only") is not True:
                raise McpPermissionError("read-only access must be explicit")
        if operation in ("semantics", "relationships", "read_bounded"):
            requested = payload.get("approved_source_ids") or payload.get("typed_entity_ids") or payload.get("approved_plan", {}).get("source_ids", [])
            if requested and any(source not in self.source_ids for source in requested):
                raise McpPermissionError("request includes a source outside the explicit allowlist")
        tool_name = mapping["tool_name"]
        tools = self.client.tools or {tool["name"]: tool for tool in self.client.list_tools()}
        tool = tools.get(tool_name)
        if not tool:
            raise McpError(f"configured tool is not discoverable: {tool_name}")
        if operation == "read_bounded":
            annotations = tool.get("annotations", {})
            if annotations.get("readOnlyHint") is not True or annotations.get("destructiveHint") is True:
                raise McpPermissionError("read_bounded tool is not explicitly marked read-only by MCP discovery")
        input_map = mapping.get("input_map", {})
        fixed_args = mapping.get("fixed_arguments", {})
        if not isinstance(input_map, dict) or not isinstance(fixed_args, dict):
            raise McpError("configured input_map/fixed_arguments must be objects")
        arguments = dict(fixed_args)
        for tool_key, logical_key in input_map.items():
            if logical_key not in payload:
                raise McpError(f"logical payload is missing mapped field: {logical_key}")
            arguments[tool_key] = payload[logical_key]
        raw = self.client.call_tool(tool_name, arguments)
        result_map = mapping.get("result_map", {})
        if not isinstance(result_map, dict):
            raise McpError("configured result_map must be an object")
        mapped = {logical_key: self._path(raw, remote_path) for logical_key, remote_path in result_map.items()}
        required = self.contract_ops[operation]["returns"]
        if any(field not in mapped for field in required):
            missing = sorted(set(required)-set(mapped))
            raise McpError(f"configured result mapping is incomplete for {operation}: {', '.join(missing)}")
        if operation == "read_bounded":
            rows = mapped["typed_rows"]
            limit = payload["limits"]["max_rows"]
            if not isinstance(rows, list) or len(rows) > limit or len(rows) > 1000:
                raise McpError("MCP result exceeded the authorized bounded-read row count")
            if mapped.get("truncation") not in (True, False):
                raise McpError("bounded-read result must disclose truncation as a boolean")
        return mapped


def configured_adapter(config, *, allow_synthetic_test=False, authorized_site_test=False):
    environment = config.get("environment") if isinstance(config, dict) else None
    if environment == "SYNTHETIC_TEST_ONLY" and not allow_synthetic_test:
        raise McpPermissionError("synthetic MCP test config requires explicit test-only opt-in")
    if (environment == "INTERNAL_APPROVED_ONLY" and config.get("qualification_status") != "QUALIFIED_INTERNAL"
            and not authorized_site_test):
        raise McpPermissionError("internal MCP transport remains PENDING_INTERNAL until site authorization is independently verified")
    if environment not in ("SYNTHETIC_TEST_ONLY", "INTERNAL_APPROVED_ONLY"):
        raise McpPermissionError("site config environment must be explicitly test-only or internally approved")
    client = McpClient(transport_from_config(config))
    try:
        client.initialize()
        client.list_tools()
        return ConfiguredSemanticAdapter(client, config, allow_synthetic_test=allow_synthetic_test,
                                         authorized_site_test=authorized_site_test)
    except Exception:
        client.close()
        raise
