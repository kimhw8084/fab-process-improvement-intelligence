"""Pinned MCP SDK client plus P4's fail-closed logical mapping adapter.

The MCP SDK owns JSON-RPC, session negotiation, stdio framing, and Streamable
HTTP. This module owns only local configuration checks and mapping between the
frozen FabSemanticsAdapter logical operations and explicitly supplied tools.
No company endpoint, tool name, permission, or source meaning is bundled here.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import ipaddress
import json
import os
import re
import threading
from pathlib import Path
from urllib.parse import urlsplit


PROTOCOL_VERSION = "SDK_NEGOTIATED"
MAX_RPC_BYTES = 4 * 1024 * 1024
MAX_TOOLS = 10_000
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class McpError(RuntimeError):
    """MCP SDK, transport, configuration, or logical-contract failure."""


class McpPermissionError(PermissionError):
    """A requested MCP operation is outside its explicit local authorization."""


def _json_size(value):
    try:
        encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False,
                             allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise McpError("MCP payload must be finite JSON") from exc
    if len(encoded) > MAX_RPC_BYTES:
        raise McpError("MCP payload exceeds the configured 4 MiB limit")
    return encoded


def _is_loopback(host):
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def transport_from_config(config):
    """Validate P4 transport settings and return SDK-ready parameters."""
    transport = config.get("transport") if isinstance(config, dict) else None
    if not isinstance(transport, dict):
        raise McpError("site config transport must be an object")
    kind = transport.get("type")
    timeout = transport.get("timeout_seconds", 10)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 30:
        raise McpError("MCP request timeout must be in (0, 30] seconds")
    timeout = float(timeout)
    if kind == "stdio":
        command = transport.get("command")
        if not isinstance(command, list) or not command or any(not isinstance(part, str) or not part for part in command):
            raise McpError("stdio MCP command must be an explicit nonempty argument list")
        cwd = transport.get("cwd")
        if cwd and not Path(cwd).is_absolute() and config.get("_config_dir"):
            cwd = str((Path(config["_config_dir"])/cwd).resolve())
        env_from = transport.get("env_from", {})
        if (not isinstance(env_from, dict)
                or any(not isinstance(child, str) or not _ENV_NAME.fullmatch(child)
                       or not isinstance(parent, str) or not _ENV_NAME.fullmatch(parent)
                       for child, parent in env_from.items())):
            raise McpError("stdio env_from must map valid child variable names to valid parent names")
        child_env = {}
        for child, parent in env_from.items():
            value = os.environ.get(parent)
            if value is None:
                raise McpPermissionError(f"configured stdio environment source is unset: {parent}")
            child_env[child] = value
        return {"type": "stdio", "command": command[0], "args": command[1:],
                "cwd": cwd, "env": child_env, "timeout": timeout}
    if kind == "streamable_http":
        endpoint = transport.get("endpoint")
        parsed = urlsplit(endpoint or "")
        allowed_hosts = transport.get("allowed_hosts")
        if (parsed.scheme not in ("https", "http") or not parsed.hostname
                or parsed.username or parsed.password or parsed.fragment):
            raise McpError("MCP endpoint must be an absolute HTTP(S) URL without embedded credentials or fragments")
        if (not isinstance(allowed_hosts, list) or not allowed_hosts
                or any(not isinstance(host, str) or not host for host in allowed_hosts)):
            raise McpError("an explicit exact allowed_hosts list is required")
        if parsed.hostname.lower() not in {host.lower() for host in allowed_hosts}:
            raise McpPermissionError("MCP endpoint host is not in the exact configured allowlist")
        if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
            raise McpPermissionError("cleartext HTTP is allowed only for loopback test servers")
        token_env = transport.get("bearer_token_env")
        if token_env is not None and (not isinstance(token_env, str) or not _ENV_NAME.fullmatch(token_env)):
            raise McpError("bearer_token_env must be a valid environment variable name")
        return {"type": "streamable_http", "endpoint": endpoint,
                "bearer_token_env": token_env, "timeout": timeout}
    raise McpError("transport.type must be stdio or streamable_http")


class McpClient:
    """Synchronous P4 facade over the official asynchronous MCP Python SDK.

    The private loop lets existing synchronous CLI and evidence workflows use
    the shared SDK without putting a second protocol implementation in P4.
    """

    def __init__(self, transport, *, client_name="fabintel-p4", client_version="1.2.0"):
        self.transport_config = transport
        self.client_name = client_name
        self.client_version = client_version
        self.timeout_seconds = transport["timeout"]
        self.tools = {}
        self.initialized = False
        self.negotiated_version = None
        self._client = None
        self._http_client = None
        self._loop = None
        self._closed = False
        self._loop_ready = threading.Event()
        self._thread = threading.Thread(target=self._serve_loop, name="p4-mcp-sdk-loop", daemon=True)
        self._thread.start()
        if not self._loop_ready.wait(timeout=5):
            raise McpError("MCP SDK event loop did not start")
        try:
            self._submit(self._connect(), timeout=self.timeout_seconds + 5)
        except Exception:
            self.close()
            raise

    def _serve_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._loop_ready.set()
        loop.run_forever()
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()

    async def _connect(self):
        try:
            from mcp import Client
            from mcp.client.stdio import StdioServerParameters
        except ImportError as exc:
            raise McpError("the pinned MCP SDK is optional; install the staged mcp-sdk.lock bundle") from exc
        config = self.transport_config
        if config["type"] == "stdio":
            server = StdioServerParameters(command=config["command"], args=config["args"],
                                           cwd=config["cwd"], env=config["env"] or None)
        else:
            try:
                import httpx2
                from mcp.client.streamable_http import streamable_http_client
            except ImportError as exc:
                raise McpError("the pinned MCP SDK bundle lacks its Streamable HTTP dependencies") from exc
            headers = {}
            token_env = config.get("bearer_token_env")
            if token_env:
                token = os.environ.get(token_env)
                if not token:
                    raise McpPermissionError("the configured bearer token environment variable is unset")
                headers["Authorization"] = f"Bearer {token}"
            self._http_client = httpx2.AsyncClient(headers=headers, timeout=config["timeout"],
                                                  follow_redirects=False)
            server = streamable_http_client(config["endpoint"], http_client=self._http_client,
                                            max_sse_event_size=MAX_RPC_BYTES)
        self._client = Client(server, read_timeout_seconds=config["timeout"])
        await self._client.__aenter__()
        version = getattr(self._client, "protocol_version", None)
        if not isinstance(version, str) or not version:
            raise McpError("MCP SDK did not negotiate a protocol version")
        self.negotiated_version = version
        self.initialized = True

    def _submit(self, coroutine, *, timeout=None):
        if self._closed or self._loop is None or not self._loop.is_running():
            raise McpError("MCP SDK session is closed")
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        try:
            return future.result(timeout=timeout or self.timeout_seconds + 1)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise McpError("MCP SDK request timed out") from exc
        except (McpError, McpPermissionError):
            raise
        except Exception as exc:
            raise McpError(f"MCP SDK operation failed: {type(exc).__name__}") from exc

    def initialize(self):
        if not self.initialized:
            raise McpError("MCP SDK session has not initialized")
        return {"protocolVersion": self.negotiated_version}

    @staticmethod
    def _plain(model):
        if hasattr(model, "model_dump"):
            return model.model_dump(mode="json", by_alias=True, exclude_none=True)
        if isinstance(model, dict):
            return model
        raise McpError("MCP SDK returned an unsupported structured value")

    async def _list_tools(self):
        all_tools, cursor, seen = [], None, set()
        for _ in range(100):
            page = await asyncio.wait_for(self._client.list_tools(cursor=cursor), timeout=self.timeout_seconds)
            if not isinstance(page.tools, list):
                raise McpError("MCP tools/list returned an invalid tools page")
            all_tools.extend(self._plain(tool) for tool in page.tools)
            if len(all_tools) > MAX_TOOLS:
                raise McpError("MCP server exceeded the 10000-tool safety bound")
            cursor = page.next_cursor
            if not cursor:
                break
            if not isinstance(cursor, str) or cursor in seen:
                raise McpError("MCP tools/list pagination cursor is invalid or repeated")
            seen.add(cursor)
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

    def list_tools(self):
        return self._submit(self._list_tools())

    async def _call_tool(self, name, arguments):
        result = await asyncio.wait_for(self._client.call_tool(name, arguments), timeout=self.timeout_seconds)
        is_error = getattr(result, "is_error", False)
        if is_error is True:
            raise McpError("MCP tool reported an execution error")
        structured = getattr(result, "structured_content", None)
        if structured is not None:
            raw = structured
        else:
            wire = self._plain(result)
            content = wire.get("content", [])
            texts = [item.get("text", "") for item in content
                     if isinstance(item, dict) and item.get("type") == "text"]
            if len(texts) == 1:
                try:
                    raw = json.loads(texts[0])
                except json.JSONDecodeError:
                    raw = {"content": content}
            else:
                raw = {"content": content}
        _json_size(raw)
        return raw

    def call_tool(self, name, arguments, *, timeout=None):
        if not isinstance(name, str) or name not in self.tools:
            raise McpError("configured MCP tool name was not returned by tools/list")
        if not isinstance(arguments, dict):
            raise McpError("MCP tool arguments must be an object")
        return self._submit(self._call_tool(name, arguments), timeout=timeout or self.timeout_seconds + 1)

    async def _close_async(self):
        client, self._client = self._client, None
        http_client, self._http_client = self._http_client, None
        try:
            if client is not None:
                await client.__aexit__(None, None, None)
        finally:
            if http_client is not None:
                await http_client.aclose()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._loop is not None and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._close_async(), self._loop)
            try:
                future.result(timeout=4)
            except Exception:
                future.cancel()
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=4)


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
    """Maps approved logical operations to explicitly configured MCP tools."""
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
