"""
Model Context Protocol over JSON-RPC 2.0, stateless (one response per request,
no server-side session). Django-free: the view supplies tools, resources and handlers.
"""
import json
from dataclasses import dataclass
from typing import Any, Callable

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
RESOURCE_NOT_FOUND = -32002


class ToolError(Exception):
    """A failed tool call; reported to the agent as an isError result."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    read_only: bool = False
    destructive: bool = False
    idempotent: bool = False

    def as_json(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {
                "readOnlyHint": self.read_only,
                "destructiveHint": self.destructive,
                "idempotentHint": self.idempotent,
                "openWorldHint": False,
            },
        }


@dataclass(frozen=True)
class Resource:
    uri: str
    name: str
    description: str
    mime_type: str = "text/markdown"

    def as_json(self) -> dict:
        return {"uri": self.uri, "name": self.name, "description": self.description, "mimeType": self.mime_type}


@dataclass
class Server:
    name: str
    version: str
    instructions: str
    tools: list
    call_tool: Callable[[str, dict], Any]
    resources: list
    read_resource: Callable[[str], str | None]
    # why a known but unlisted tool is refused, e.g. a missing permission; None if unknown
    refusal: Callable[[str], str | None] = lambda name: None

    def handle_body(self, body: bytes) -> Any:
        """A raw POST body -> JSON response payload, or None when there is nothing to answer."""
        try:
            payload = json.loads(body or b"null")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _error(None, PARSE_ERROR, "Parse error.")
        if isinstance(payload, list):
            if not payload:
                return _error(None, INVALID_REQUEST, "Empty batch.")
            answers = [a for a in (self.handle(m) for m in payload) if a is not None]
            return answers or None
        return self.handle(payload)

    def handle(self, message) -> dict | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return _error(message.get("id") if isinstance(message, dict) else None, INVALID_REQUEST, "Invalid request.")
        if "id" not in message:
            return None  # a notification, e.g. notifications/initialized
        msg_id, method = message["id"], message["method"]
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _error(msg_id, INVALID_PARAMS, "params must be an object.")
        handler = {
            "initialize": self._initialize,
            "ping": lambda p: {},
            "tools/list": lambda p: {"tools": [t.as_json() for t in self.tools]},
            "tools/call": self._tools_call,
            "resources/list": lambda p: {"resources": [r.as_json() for r in self.resources]},
            "resources/templates/list": lambda p: {"resourceTemplates": []},
            "resources/read": self._resources_read,
            "prompts/list": lambda p: {"prompts": []},
        }.get(method)
        if handler is None:
            return _error(msg_id, METHOD_NOT_FOUND, f"Method not found: {method}")
        try:
            return {"jsonrpc": "2.0", "id": msg_id, "result": handler(params)}
        except _RpcError as exc:
            return _error(msg_id, exc.code, str(exc))

    def _initialize(self, params):
        requested = params.get("protocolVersion")
        return {
            "protocolVersion": requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}, "resources": {"listChanged": False}},
            "serverInfo": {"name": self.name, "version": self.version},
            "instructions": self.instructions,
        }

    def _tools_call(self, params):
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            raise _RpcError(INVALID_PARAMS, "arguments must be an object.")
        if name not in {t.name for t in self.tools}:
            reason = self.refusal(name) if isinstance(name, str) else None
            if reason:
                return {"content": [{"type": "text", "text": reason}], "isError": True}
            raise _RpcError(INVALID_PARAMS, f"Unknown tool: {name}")
        try:
            result = self.call_tool(name, args)
        except ToolError as exc:
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        if result is None:
            result = {"ok": True}
        out = {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}], "isError": False}
        if isinstance(result, dict):
            out["structuredContent"] = result
        return out

    def _resources_read(self, params):
        uri = params.get("uri")
        text = self.read_resource(uri) if isinstance(uri, str) else None
        if text is None:
            raise _RpcError(RESOURCE_NOT_FOUND, f"Resource not found: {uri}")
        mime = next((r.mime_type for r in self.resources if r.uri == uri), "text/markdown")
        return {"contents": [{"uri": uri, "mimeType": mime, "text": text}]}


class _RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _error(msg_id, code, message) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}
