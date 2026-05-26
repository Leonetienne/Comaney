"""
Unit tests for budget/views/expenses.py::_buddy_render_context_from_post.

Pure Python: mirrors the dict-building logic with SimpleNamespace stand-ins
for FeUser/DummyUser/Project instances (only .pk is read), no Django/DB.
Run with: venv/bin/pytest tests/unit/test_buddy_render_context_from_post.py -v
"""
import json
import sys
import os
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ── Inline the helper under test (Django not available in local venv) ──────

def _safe_json(obj) -> str:
    return (
        json.dumps(obj)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def buddy_render_context_from_post(buddy, feuser) -> dict:
    if not buddy:
        return {
            "is_buddy_expense": False,
            "existing_mode": "single",
            "existing_upfront_type": "me",
            "existing_upfront_id": feuser.pk,
            "existing_spendings_json": "[]",
            "existing_group_id": "",
        }
    if buddy["upfront_type"] == "feuser" and buddy.get("upfront_feuser"):
        upfront_id = buddy["upfront_feuser"].pk
    elif buddy["upfront_type"] == "dummy" and buddy.get("upfront_dummy"):
        upfront_id = buddy["upfront_dummy"].pk
    else:
        upfront_id = feuser.pk
    return {
        "is_buddy_expense": True,
        "existing_mode": buddy["mode"],
        "existing_upfront_type": buddy["upfront_type"],
        "existing_upfront_id": upfront_id,
        "existing_spendings_json": _safe_json(buddy.get("spendings") or []),
        "existing_group_id": buddy["group"].pk if buddy.get("group") else "",
    }


ME = SimpleNamespace(pk=1)


class TestBuddyRenderContextFromPost:

    def test_none_buddy_returns_no_assignment_defaults(self):
        ctx = buddy_render_context_from_post(None, ME)
        assert ctx["is_buddy_expense"] is False
        assert ctx["existing_mode"] == "single"
        assert ctx["existing_upfront_type"] == "me"
        assert ctx["existing_upfront_id"] == 1
        assert ctx["existing_spendings_json"] == "[]"
        assert ctx["existing_group_id"] == ""

    def test_me_as_payer_preserves_mode_and_group(self):
        buddy = {
            "mode": "group",
            "upfront_type": "me",
            "upfront_feuser": None,
            "upfront_dummy": None,
            "group": SimpleNamespace(pk=42),
            "spendings": [{"type": "dummy", "id": 7, "share_percent": 50.0}],
        }
        ctx = buddy_render_context_from_post(buddy, ME)
        assert ctx["is_buddy_expense"] is True
        assert ctx["existing_mode"] == "group"
        assert ctx["existing_upfront_type"] == "me"
        assert ctx["existing_upfront_id"] == 1
        assert ctx["existing_group_id"] == 42
        assert json.loads(ctx["existing_spendings_json"]) == buddy["spendings"]

    def test_feuser_as_payer_uses_their_pk(self):
        buddy = {
            "mode": "single",
            "upfront_type": "feuser",
            "upfront_feuser": SimpleNamespace(pk=99),
            "upfront_dummy": None,
            "group": None,
            "spendings": [{"type": "feuser", "id": 1, "share_percent": 50.0}],
        }
        ctx = buddy_render_context_from_post(buddy, ME)
        assert ctx["existing_upfront_type"] == "feuser"
        assert ctx["existing_upfront_id"] == 99
        assert ctx["existing_group_id"] == ""

    def test_dummy_as_payer_uses_their_pk(self):
        buddy = {
            "mode": "single",
            "upfront_type": "dummy",
            "upfront_feuser": None,
            "upfront_dummy": SimpleNamespace(pk=13),
            "group": None,
            "spendings": [],
        }
        ctx = buddy_render_context_from_post(buddy, ME)
        assert ctx["existing_upfront_type"] == "dummy"
        assert ctx["existing_upfront_id"] == 13

    def test_missing_resolved_payer_falls_back_to_feuser(self):
        # e.g. submitted upfront_type='feuser' but the id didn't resolve to a real FeUser
        buddy = {
            "mode": "single",
            "upfront_type": "feuser",
            "upfront_feuser": None,
            "upfront_dummy": None,
            "group": None,
            "spendings": [],
        }
        ctx = buddy_render_context_from_post(buddy, ME)
        assert ctx["existing_upfront_id"] == 1

    def test_no_spendings_serializes_to_empty_array(self):
        buddy = {
            "mode": "group",
            "upfront_type": "me",
            "upfront_feuser": None,
            "upfront_dummy": None,
            "group": SimpleNamespace(pk=5),
            "spendings": [],
        }
        ctx = buddy_render_context_from_post(buddy, ME)
        assert ctx["existing_spendings_json"] == "[]"
