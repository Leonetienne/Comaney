"""
REST API v2 invitation flows: contact invites (invite, pending list, accept,
decline, revoke) and Catalog Partnership (invite, decline, cancel, onboarding,
remove partner, leave). Run with:
pytest -v tests/e2e/api/test_api_invites.py | tee logfile.log
"""
import pytest

from bhelpers import _create_contact_link, _get_pk
from helpers import api_get, api_post, api_delete, setup_user, cleanup_user


@pytest.fixture(scope="module")
def ctx():
    a = setup_user(None, None, "Iris", "Invite")
    b = setup_user(None, None, "Otto", "Offer")
    c = setup_user(None, None, "Carla", "Decline")
    cctx = {
        "a": a, "b": b, "c": c,
        "a_pk": int(_get_pk(a["email"])),
        "b_pk": int(_get_pk(b["email"])),
        "c_pk": int(_get_pk(c["email"])),
    }
    yield cctx
    for u in (a, b, c):
        cleanup_user(u["email"])


def _contact_invite_id(ctx, invitee):
    invites = api_get("/api/v2/pending/", invitee).json()["contact_invites"]
    assert len(invites) == 1
    return invites[0]["id"]


def _join_partnership(ctx, invitee):
    """Run the invitee's onboarding (state, preview, apply) against the open invite."""
    state = api_get("/api/v2/partnership/onboarding/", invitee).json()
    tag_map = {t: None for t in state["unmatched_tags"]}
    cat_map = {c: None for c in state["unmatched_categories"]}
    preview = api_post(
        "/api/v2/partnership/onboarding/preview/", invitee,
        {"tag_map": tag_map, "category_map": cat_map},
    ).json()
    resp = api_post(
        "/api/v2/partnership/onboarding/apply/", invitee,
        {"tag_map": tag_map, "category_map": cat_map, "confirm_token": preview["confirm_token"]},
    )
    assert resp.status_code == 200 and resp.json()["joined"] is True


class TestContactInvites:

    def test_invite(self, ctx):
        resp = api_post("/api/v2/contacts/invites/", ctx["a"], {"feuser_id": ctx["b_pk"]})
        assert resp.status_code == 201
        assert resp.json()["outcome"] == "invite"

    def test_pending_shows_invite(self, ctx):
        invites = api_get("/api/v2/pending/", ctx["b"]).json()["contact_invites"]
        assert len(invites) == 1
        assert "Iris" in invites[0]["from"]

    def test_revoke(self, ctx):
        inv = _contact_invite_id(ctx, ctx["b"])
        resp = api_delete(f"/api/v2/contacts/invites/{inv}/", ctx["a"])
        assert resp.status_code == 204
        assert api_get("/api/v2/pending/", ctx["b"]).json()["contact_invites"] == []

    def test_respond_accept(self, ctx):
        resp = api_post("/api/v2/contacts/invites/", ctx["a"], {"feuser_id": ctx["b_pk"]})
        assert resp.status_code == 201
        inv = _contact_invite_id(ctx, ctx["b"])
        resp = api_post(f"/api/v2/contacts/invites/{inv}/respond/", ctx["b"], {"accept": True})
        assert resp.status_code == 200 and resp.json()["accepted"] is True
        assert resp.json()["contact"]["id"] == ctx["a_pk"]
        contacts = api_get("/api/v2/contacts/", ctx["b"]).json()["contacts"]
        me = next(c for c in contacts if c["id"] == ctx["a_pk"])
        assert me["link_id"]

    def test_respond_requires_the_invitee(self, ctx):
        assert api_post("/api/v2/contacts/invites/", ctx["a"], {"feuser_id": ctx["c_pk"]}).status_code == 201
        inv = _contact_invite_id(ctx, ctx["c"])
        resp = api_post(f"/api/v2/contacts/invites/{inv}/respond/", ctx["a"], {"accept": True})
        assert resp.status_code == 404

    def test_respond_decline(self, ctx):
        inv = _contact_invite_id(ctx, ctx["c"])
        resp = api_post(f"/api/v2/contacts/invites/{inv}/respond/", ctx["c"], {"accept": False})
        assert resp.status_code == 200 and resp.json()["declined"] is True
        ids = [c["id"] for c in api_get("/api/v2/contacts/", ctx["c"]).json()["contacts"]]
        assert ctx["a_pk"] not in ids
        assert api_get("/api/v2/pending/", ctx["c"]).json()["contact_invites"] == []


class TestPartnership:

    def test_invite_requires_a_connection(self, ctx):
        resp = api_post("/api/v2/partnership/invites/", ctx["a"], {"feuser_id": ctx["c_pk"]})
        assert resp.status_code == 403
        assert "No mutual connection" in resp.json()["error"]

    def test_get_initially_empty(self, ctx):
        data = api_get("/api/v2/partnership/", ctx["a"]).json()
        assert data["in_partnership"] is False
        assert data["partners"] == [] and data["outgoing_invites"] == []

    def test_invite(self, ctx):
        _create_contact_link(ctx["a"]["email"], ctx["b"]["email"])
        resp = api_post("/api/v2/partnership/invites/", ctx["a"], {"feuser_id": ctx["b_pk"]})
        assert resp.status_code == 201
        ctx["invite_id"] = resp.json()["id"]
        assert "Otto" in resp.json()["invited"]

    def test_get_shows_open_invite(self, ctx):
        a = api_get("/api/v2/partnership/", ctx["a"]).json()
        assert [i["email"] for i in a["outgoing_invites"]] == [ctx["b"]["email"]]
        assert a["outgoing_invites"][0]["id"] == ctx["invite_id"]
        b = api_get("/api/v2/partnership/", ctx["b"]).json()
        assert [i["id"] for i in b["incoming_invites"]] == [ctx["invite_id"]]
        assert "Iris" in b["incoming_invites"][0]["from"]

    def test_onboarding_decline(self, ctx):
        resp = api_post("/api/v2/partnership/onboarding/decline/", ctx["b"], {})
        assert resp.status_code == 200 and resp.json()["declined"] is True
        assert api_get("/api/v2/partnership/", ctx["b"]).json()["incoming_invites"] == []

    def test_invite_cancel(self, ctx):
        inv = api_post("/api/v2/partnership/invites/", ctx["a"], {"feuser_id": ctx["b_pk"]}).json()["id"]
        resp = api_delete(f"/api/v2/partnership/invites/{inv}/", ctx["a"])
        assert resp.status_code == 204
        assert api_get("/api/v2/partnership/", ctx["a"]).json()["outgoing_invites"] == []
        assert api_get("/api/v2/partnership/", ctx["b"]).json()["incoming_invites"] == []

    def test_join_via_onboarding(self, ctx):
        assert api_post("/api/v2/partnership/invites/", ctx["a"], {"feuser_id": ctx["b_pk"]}).status_code == 201
        _join_partnership(ctx, ctx["b"])

    def test_get_shows_partnership(self, ctx):
        a = api_get("/api/v2/partnership/", ctx["a"]).json()
        assert a["in_partnership"] is True
        assert [p["id"] for p in a["partners"]] == [ctx["b_pk"]]
        b = api_get("/api/v2/partnership/", ctx["b"]).json()
        assert [p["id"] for p in b["partners"]] == [ctx["a_pk"]]

    def test_remove_partner(self, ctx):
        resp = api_delete(f"/api/v2/partnership/partners/{ctx['b_pk']}/", ctx["a"])
        assert resp.status_code == 204
        assert api_get("/api/v2/partnership/", ctx["b"]).json()["in_partnership"] is False
        assert api_get("/api/v2/partnership/", ctx["a"]).json()["partners"] == []

    def test_leave(self, ctx):
        assert api_post("/api/v2/partnership/invites/", ctx["a"], {"feuser_id": ctx["b_pk"]}).status_code == 201
        _join_partnership(ctx, ctx["b"])
        resp = api_post("/api/v2/partnership/leave/", ctx["b"], {})
        assert resp.status_code == 200 and resp.json()["left"] is True
        assert api_get("/api/v2/partnership/", ctx["b"]).json()["in_partnership"] is False
