"""
mcp_server/protocol.py: JSON-RPC handling of the MCP server without Django.
Run with: venv/bin/pytest tests/unit/test_mcp_protocol.py -v
"""
import json

from mcp_server.protocol import (
    INVALID_PARAMS, INVALID_REQUEST, METHOD_NOT_FOUND, PARSE_ERROR, RESOURCE_NOT_FOUND,
    Resource, Server, Tool, ToolError,
)


def _server(call=None, refusal=lambda name: None):
    tools = [
        Tool("echo", "Echo arguments.", {"type": "object"}, read_only=True, idempotent=True),
        Tool("wipe", "Delete things.", {"type": "object"}, destructive=True),
    ]

    def default_call(name, args):
        if name == "wipe":
            raise ToolError("nothing to wipe")
        return args or None

    return Server(
        name="comaney", version="1.0", instructions="Use docs_search first.",
        tools=tools, call_tool=call or default_call,
        resources=[Resource("comaney://docs/user-manual/expenses.md", "Expenses", "Manual page")],
        read_resource=lambda uri: "# Expenses" if uri == "comaney://docs/user-manual/expenses.md" else None,
        refusal=refusal,
    )


def _rpc(method, params=None, msg_id=1):
    return {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}


class TestInitialize:

    def test_echoes_supported_version_and_sends_instructions(self):
        result = _server().handle(_rpc("initialize", {"protocolVersion": "2025-03-26"}))["result"]
        assert result["protocolVersion"] == "2025-03-26"
        assert result["instructions"] == "Use docs_search first."
        assert result["serverInfo"]["name"] == "comaney"
        assert "tools" in result["capabilities"] and "resources" in result["capabilities"]

    def test_unknown_version_gets_latest(self):
        result = _server().handle(_rpc("initialize", {"protocolVersion": "1999-01-01"}))["result"]
        assert result["protocolVersion"] == "2025-06-18"


class TestEnvelope:

    def test_notification_gets_no_answer(self):
        assert _server().handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

    def test_parse_error(self):
        assert _server().handle_body(b"{nope")["error"]["code"] == PARSE_ERROR

    def test_invalid_request(self):
        assert _server().handle({"id": 1, "method": "ping"})["error"]["code"] == INVALID_REQUEST

    def test_unknown_method(self):
        assert _server().handle(_rpc("sampling/createMessage"))["error"]["code"] == METHOD_NOT_FOUND

    def test_batch_answers_requests_only(self):
        body = json.dumps([_rpc("ping", msg_id=7), {"jsonrpc": "2.0", "method": "notifications/initialized"}]).encode()
        answers = _server().handle_body(body)
        assert [a["id"] for a in answers] == [7]

    def test_batch_of_notifications_gets_no_answer(self):
        body = json.dumps([{"jsonrpc": "2.0", "method": "notifications/initialized"}]).encode()
        assert _server().handle_body(body) is None


class TestTools:

    def test_list_carries_hints(self):
        tools = {t["name"]: t for t in _server().handle(_rpc("tools/list"))["result"]["tools"]}
        assert tools["echo"]["annotations"]["readOnlyHint"] is True
        assert tools["wipe"]["annotations"]["destructiveHint"] is True
        assert tools["wipe"]["annotations"]["openWorldHint"] is False

    def test_call_returns_text_and_structured_content(self):
        result = _server().handle(_rpc("tools/call", {"name": "echo", "arguments": {"a": 1}}))["result"]
        assert result["isError"] is False
        assert result["structuredContent"] == {"a": 1}
        assert json.loads(result["content"][0]["text"]) == {"a": 1}

    def test_empty_result_becomes_ok(self):
        result = _server().handle(_rpc("tools/call", {"name": "echo"}))["result"]
        assert result["structuredContent"] == {"ok": True}

    def test_tool_error_is_an_error_result(self):
        result = _server().handle(_rpc("tools/call", {"name": "wipe"}))["result"]
        assert result["isError"] is True
        assert result["content"][0]["text"] == "nothing to wipe"

    def test_unknown_tool_is_invalid_params(self):
        assert _server().handle(_rpc("tools/call", {"name": "nope"}))["error"]["code"] == INVALID_PARAMS

    def test_refused_tool_names_the_reason(self):
        server = _server(refusal=lambda name: "lacks Expenses write permission" if name == "expenses_create" else None)
        result = server.handle(_rpc("tools/call", {"name": "expenses_create"}))["result"]
        assert result["isError"] is True
        assert "Expenses write" in result["content"][0]["text"]

    def test_arguments_must_be_an_object(self):
        response = _server().handle(_rpc("tools/call", {"name": "echo", "arguments": [1]}))
        assert response["error"]["code"] == INVALID_PARAMS


class TestResources:

    def test_list_and_read(self):
        server = _server()
        uris = [r["uri"] for r in server.handle(_rpc("resources/list"))["result"]["resources"]]
        assert uris == ["comaney://docs/user-manual/expenses.md"]
        content = server.handle(_rpc("resources/read", {"uri": uris[0]}))["result"]["contents"][0]
        assert content["text"] == "# Expenses" and content["mimeType"] == "text/markdown"

    def test_unknown_resource(self):
        response = _server().handle(_rpc("resources/read", {"uri": "comaney://nope"}))
        assert response["error"]["code"] == RESOURCE_NOT_FOUND
