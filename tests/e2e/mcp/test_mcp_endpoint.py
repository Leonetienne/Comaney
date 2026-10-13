"""
MCP server at /mcp: agent key authentication, the JSON-RPC handshake, tools generated
from the API registry, per-key permissions, the user manual tools and resources.
Run with: pytest -v tests/e2e/mcp/test_mcp_endpoint.py | tee logfile.log
"""
import pytest
import requests

from bhelpers import _shell
from helpers import BASE_URL, api_get, cleanup_user, setup_user


def _new_key(email, label="Test"):
    return _shell(
        "from feusers.models import FeUser; from mcp_server.models import AgentKey; "
        f"k, raw = AgentKey.create(FeUser.objects.get(email='{email}'), '{label}'); print(raw)"
    )


def _restrict(email, label, perms):
    _shell(
        "from mcp_server.models import AgentKey; "
        f"k = AgentKey.objects.get(feuser__email='{email}', label='{label}'); k.permissions = {perms!r}; k.save()"
    )


def _post(key, payload, **headers):
    return requests.post(
        f"{BASE_URL}/mcp", json=payload, timeout=20,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json, text/event-stream", **headers},
    )


def _rpc(key, method, params=None):
    resp = _post(key, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _call(key, name, arguments=None):
    return _rpc(key, "tools/call", {"name": name, "arguments": arguments or {}})["result"]


@pytest.fixture(scope="module")
def ctx():
    user = setup_user(None, None, "Mia", "Mcp")
    user["key"] = _new_key(user["email"])
    yield user
    cleanup_user(user["email"])


class TestTransport:

    def test_initialize_returns_instructions_pointing_to_the_manual(self, ctx):
        result = _rpc(ctx["key"], "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})["result"]
        assert result["protocolVersion"] == "2025-06-18"
        assert "docs_search" in result["instructions"]

    def test_notification_is_accepted_without_body(self, ctx):
        resp = _post(ctx["key"], {"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert resp.status_code == 202 and resp.text == ""

    def test_missing_or_unknown_key_is_rejected(self, ctx):
        assert requests.post(f"{BASE_URL}/mcp", json={}, timeout=10).status_code == 401
        assert _post("cmy_wrong", {"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401

    def test_rest_api_key_does_not_open_mcp_and_vice_versa(self, ctx):
        assert _post(ctx["api_key"], {"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401
        resp = requests.get(f"{BASE_URL}/api/v2/account/", headers={"Authorization": f"Bearer {ctx['key']}"}, timeout=10)
        assert resp.status_code == 401

    def test_get_is_not_allowed(self, ctx):
        resp = requests.get(f"{BASE_URL}/mcp", headers={"Authorization": f"Bearer {ctx['key']}"}, timeout=10)
        assert resp.status_code == 405

    def test_foreign_browser_origin_is_rejected(self, ctx):
        resp = _post(ctx["key"], {"jsonrpc": "2.0", "id": 1, "method": "ping"}, Origin="https://evil.example")
        assert resp.status_code == 403

    def test_last_use_is_recorded(self, ctx):
        used = _shell(
            "from mcp_server.models import AgentKey; "
            f"print(AgentKey.objects.get(feuser__email='{ctx['email']}', label='Test').last_used_at is not None)"
        )
        assert used == "True"


class TestTools:

    def test_full_key_lists_every_operation_plus_docs(self, ctx):
        tools = {t["name"]: t for t in _rpc(ctx["key"], "tools/list")["result"]["tools"]}
        assert {"docs_search", "docs_read", "expenses_create", "projects_create", "pending_list"} <= set(tools)
        assert tools["expenses_list"]["annotations"]["readOnlyHint"] is True
        assert tools["expenses_bulk"]["annotations"]["destructiveHint"] is True
        assert tools["expenses_create"]["inputSchema"]["required"] == ["title", "type", "value"]

    def test_create_then_total(self, ctx):
        created = _call(ctx["key"], "expenses_create", {"title": "Groceries", "type": "expense", "value": 15, "payee": "Edeka"})
        assert created["isError"] is False
        totals = _call(ctx["key"], "expenses_totals", {"q": "payee=edeka"})["structuredContent"]
        assert totals["total"] == "15.00"
        assert api_get(f"/api/v2/expenses/{created['structuredContent']['id']}/", ctx).status_code == 200

    def test_invalid_arguments_come_back_as_tool_errors(self, ctx):
        result = _call(ctx["key"], "expenses_create", {"title": "x", "type": "nope", "value": 1})
        assert result["isError"] is True and "'type' must be one of" in result["content"][0]["text"]
        result = _call(ctx["key"], "expenses_list", {"bogus": 1})
        assert result["isError"] is True and "Unknown argument 'bogus'" in result["content"][0]["text"]

    def test_account_secrets_are_out_of_reach(self, ctx):
        tools = {t["name"] for t in _rpc(ctx["key"], "tools/list")["result"]["tools"]}
        assert not {n for n in tools if "password" in n or "api_key" in n or "delete_account" in n}
        result = _call(ctx["key"], "account_update", {"email": "x@example.com"})
        assert result["isError"] is True


class TestPermissions:

    def test_restricted_key_lists_only_allowed_tools(self, ctx):
        key = _new_key(ctx["email"], "ReadOnly")
        _restrict(ctx["email"], "ReadOnly", {"expenses": {"read": True, "write": False}})
        names = {t["name"] for t in _rpc(key, "tools/list")["result"]["tools"]}
        assert names == {"docs_search", "docs_read", "expenses_list", "expenses_get", "expenses_totals", "expenses_overlay_get"}
        ctx["readonly_key"] = key

    def test_refused_call_names_the_missing_permission_and_changes_nothing(self, ctx):
        before = api_get("/api/v2/expenses/", ctx).json()["expenses"]
        result = _call(ctx["readonly_key"], "expenses_create", {"title": "No", "type": "expense", "value": 1})
        assert result["isError"] is True and "Expenses write" in result["content"][0]["text"]
        assert len(api_get("/api/v2/expenses/", ctx).json()["expenses"]) == len(before)

    def test_bulk_delete_token_is_bound_to_the_key(self, ctx):
        eid = _call(ctx["key"], "expenses_create", {"title": "Bound", "type": "expense", "value": 2})["structuredContent"]["id"]
        preview = _call(ctx["key"], "expenses_bulk", {"action": "delete", "ids": [eid]})["structuredContent"]
        other = _new_key(ctx["email"], "Other")
        result = _call(other, "expenses_bulk", {"action": "delete", "ids": [eid], "confirm_token": preview["confirm_token"]})
        assert result["isError"] is True
        done = _call(ctx["key"], "expenses_bulk", {"action": "delete", "ids": [eid], "confirm_token": preview["confirm_token"]})
        assert done["structuredContent"]["updated"] == 1

    def test_demo_accounts_cannot_use_agent_keys(self, ctx):
        _shell(f"from feusers.models import FeUser; FeUser.objects.filter(email='{ctx['email']}').update(is_demo=True)")
        try:
            assert _post(ctx["key"], {"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401
        finally:
            _shell(f"from feusers.models import FeUser; FeUser.objects.filter(email='{ctx['email']}').update(is_demo=False)")


class TestManual:

    def test_search_and_read(self, ctx):
        hits = _call(ctx["key"], "docs_search", {"query": "settle up contact"})["structuredContent"]["results"]
        assert "contacts/settling-up.md" in [h["path"] for h in hits]
        page = _call(ctx["key"], "docs_read", {"path": "contacts/settling-up.md"})["structuredContent"]
        assert page["url"].endswith("/docs/user-manual/contacts/settling-up/")
        assert page["content"].startswith("#")

    def test_manual_stays_available_to_a_key_without_permissions(self, ctx):
        key = _new_key(ctx["email"], "Nothing")
        _restrict(ctx["email"], "Nothing", {})
        names = {t["name"] for t in _rpc(key, "tools/list")["result"]["tools"]}
        assert names == {"docs_search", "docs_read"}

    def test_manual_pages_are_resources(self, ctx):
        resources = _rpc(ctx["key"], "resources/list")["result"]["resources"]
        uris = {r["uri"] for r in resources}
        assert "comaney://docs/user-manual/expenses.md" in uris
        assert "comaney://reference/dashboard-cards" in uris
        text = _rpc(ctx["key"], "resources/read", {"uri": "comaney://docs/user-manual/expenses.md"})["result"]["contents"][0]["text"]
        assert text.startswith("# Expenses")
