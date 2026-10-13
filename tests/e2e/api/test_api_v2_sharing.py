"""
REST API v2 for the sharing side: projects, contacts, pending decisions, settlements,
shared expenses through `assignment`, overlays, totals, two-step bulk delete and
Catalog Partnership onboarding. Every write goes through the same services as the
web app, so approval resets and notifications behave the same.
Run with: pytest -v tests/e2e/api/test_api_v2_sharing.py | tee logfile.log
"""
import pytest

from bhelpers import _create_contact_link, _get_pk, _shell
from helpers import api, api_get, api_patch, api_post, cleanup_user, setup_user


@pytest.fixture(scope="module")
def ctx():
    a = setup_user(None, None, "Ann", "Alpha")
    b = setup_user(None, None, "Bob", "Beta")
    c = {"a": a, "b": b}
    c["link"] = int(_create_contact_link(a["email"], b["email"]))
    c["a_pk"], c["b_pk"] = int(_get_pk(a["email"])), int(_get_pk(b["email"]))
    yield c
    cleanup_user(a["email"])
    cleanup_user(b["email"])


def _approval_of(expense_id, feuser_pk):
    return int(_shell(
        f"from buddies.models import BuddySpending; "
        f"print(BuddySpending.objects.get(expense_id={expense_id}, participant_feuser_id={feuser_pk}).approval_state)"
    ))


class TestContacts:

    def test_list_shows_link_and_balance(self, ctx):
        data = api_get("/api/v2/contacts/", ctx["a"]).json()
        bob = next(c for c in data["contacts"] if c["id"] == ctx["b_pk"])
        assert bob["link_id"] == ctx["link"]
        assert bob["balance"] == "0.00"

    def test_offline_contact_lifecycle(self, ctx):
        resp = api_post("/api/v2/contacts/offline/", ctx["a"], {"name": "Bojak"})
        assert resp.status_code == 201
        oid = resp.json()["id"]
        resp = api_patch(f"/api/v2/contacts/offline/{oid}/", ctx["a"], {"name": "Bojak Jr"})
        assert resp.json()["name"] == "Bojak Jr"
        resp = api("DELETE", f"/api/v2/contacts/offline/{oid}/", ctx["a"])
        assert resp.status_code == 200 and resp.json()["removed"] is True

    def test_someone_elses_link_is_not_found(self, ctx):
        other = setup_user(None, None)
        try:
            resp = api("PUT", f"/api/v2/contacts/{ctx['link']}/auto-accept/", other, json={"enabled": True})
            assert resp.status_code == 404
        finally:
            cleanup_user(other["email"])


class TestProjects:

    def test_create(self, ctx):
        resp = api_post("/api/v2/projects/", ctx["a"], {"name": "Ibiza", "description": "trip"})
        assert resp.status_code == 201
        ctx["pid"] = resp.json()["id"]

    def test_invite_contact_and_accept_via_pending(self, ctx):
        resp = api_post(f"/api/v2/projects/{ctx['pid']}/invites/", ctx["a"], {"feuser_id": ctx["b_pk"]})
        assert resp.status_code == 201 and resp.json()["outcome"] == "invite"
        invites = api_get("/api/v2/pending/", ctx["b"]).json()["project_invites"]
        assert len(invites) == 1
        resp = api_post(f"/api/v2/projects/invites/{invites[0]['id']}/respond/", ctx["b"], {"accept": True})
        assert resp.json()["accepted"] is True

    def test_member_cannot_change_admin_settings(self, ctx):
        resp = api_patch(f"/api/v2/projects/{ctx['pid']}/", ctx["b"], {"archived": True})
        assert resp.status_code == 403

    def test_details_and_members(self, ctx):
        resp = api_post(f"/api/v2/projects/{ctx['pid']}/offline-members/", ctx["a"], {"name": "Berta"})
        assert resp.status_code == 201
        data = api_get(f"/api/v2/projects/{ctx['pid']}/", ctx["a"]).json()
        names = {m["name"] for m in data["members"]}
        assert {"Ann Alpha", "Bob Beta", "Berta"} <= names
        assert data["permission_laxity"] == "admin_only"


class TestSharedExpense:

    def test_create_with_assignment(self, ctx):
        resp = api_post("/api/v2/expenses/", ctx["a"], {
            "title": "Groceries", "type": "expense", "value": "15", "payee": "Edeka",
            "assignment": {"mode": "project", "project_id": ctx["pid"],
                           "participants": [{"type": "feuser", "id": ctx["b_pk"], "share_percent": 50}]},
        })
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["effective_value"] == "7.50"
        assert data["assignment"]["participants"] == [{"type": "feuser", "id": ctx["b_pk"], "share_percent": 50.0}]
        ctx["eid"] = data["id"]

    def test_assignment_to_unconnected_person_is_rejected(self, ctx):
        stranger = setup_user(None, None)
        try:
            resp = api_post("/api/v2/expenses/", ctx["a"], {
                "title": "x", "type": "expense", "value": "1",
                "assignment": {"mode": "contact", "participants": [
                    {"type": "feuser", "id": int(_get_pk(stranger["email"])), "share_percent": 50}]},
            })
            assert resp.status_code == 400 and "Invalid assignment" in resp.json()["error"]
        finally:
            cleanup_user(stranger["email"])

    def test_participant_approves(self, ctx):
        resp = api_post("/api/v2/pending/decide/", ctx["b"], {"kind": "consent", "expense_id": ctx["eid"], "approve": True})
        assert resp.status_code == 200
        assert _approval_of(ctx["eid"], ctx["b_pk"]) == 1

    def test_value_change_resets_approval(self, ctx):
        resp = api_patch(f"/api/v2/expenses/{ctx['eid']}/", ctx["a"], {"value": "13"})
        assert resp.status_code == 200
        assert resp.json()["assignment"]["participants"][0]["id"] == ctx["b_pk"]
        assert _approval_of(ctx["eid"], ctx["b_pk"]) == 0

    def test_payee_change_keeps_approval(self, ctx):
        api_post("/api/v2/pending/decide/", ctx["b"], {"kind": "consent", "expense_id": ctx["eid"], "approve": True})
        api_patch(f"/api/v2/expenses/{ctx['eid']}/", ctx["a"], {"payee": "EDEKA Center"})
        assert _approval_of(ctx["eid"], ctx["b_pk"]) == 1

    def test_participant_sets_own_overlay(self, ctx):
        tag = api_get("/api/v2/tags/", ctx["b"]).json()["tags"][0]
        resp = api("PUT", f"/api/v2/expenses/{ctx['eid']}/overlay/", ctx["b"], json={"tag_ids": [tag["id"]], "note": "mine"})
        assert resp.status_code == 200 and resp.json()["tags"] == [tag]
        foreign = api_get(f"/api/v2/expenses/{ctx['eid']}/", ctx["b"]).json()
        assert foreign["is_foreign"] is True and foreign["tags"] == [tag]

    def test_totals_count_own_share_in_shared_mode(self, ctx):
        mine = api_get("/api/v2/expenses/totals/", ctx["b"], params={"sharing": "shared"}).json()
        assert mine["total"] == "6.50"
        by_payee = api_get("/api/v2/expenses/totals/", ctx["a"], params={"q": "payee=edeka", "group_by": "payee"}).json()
        assert by_payee["groups"][0]["total"] == "13.00"


class TestSettlement:

    def test_member_pays_and_creditor_confirms(self, ctx):
        resp = api_post("/api/v2/settlements/", ctx["b"], {
            "project_id": ctx["pid"], "creditor": {"type": "feuser", "id": ctx["a_pk"]}, "amount": "6.50",
        })
        assert resp.status_code == 201, resp.text
        items = api_get("/api/v2/pending/", ctx["a"]).json()["confirm_settlement_received"]["items"]
        assert len(items) == 1
        resp = api_post("/api/v2/pending/decide/", ctx["a"], {"kind": "settlement", "expense_id": items[0]["id"], "approve": True})
        assert resp.status_code == 200
        assert api_get("/api/v2/pending/", ctx["a"]).json()["confirm_settlement_received"]["items"] == []


class TestBulkDelete:

    def test_preview_then_confirm(self, ctx):
        ids = [api_post("/api/v2/expenses/", ctx["a"], {"title": f"Lovelyplace {i}", "type": "expense", "value": "3", "payee": "Lovelyplace"}).json()["id"] for i in range(2)]
        preview = api_post("/api/v2/expenses/bulk/", ctx["a"], {"action": "delete", "ids": ids}).json()
        assert preview["preview"] is True and preview["count"] == 2 and preview["total"] == "6.00"
        assert all(api_get(f"/api/v2/expenses/{i}/", ctx["a"]).status_code == 200 for i in ids)
        done = api_post("/api/v2/expenses/bulk/", ctx["a"], {"action": "delete", "ids": ids, "confirm_token": preview["confirm_token"]}).json()
        assert done["updated"] == 2
        assert all(api_get(f"/api/v2/expenses/{i}/", ctx["a"]).status_code == 404 for i in ids)

    def test_token_goes_stale_when_an_expense_changes(self, ctx):
        eid = api_post("/api/v2/expenses/", ctx["a"], {"title": "Stale", "type": "expense", "value": "3"}).json()["id"]
        preview = api_post("/api/v2/expenses/bulk/", ctx["a"], {"action": "delete", "ids": [eid]}).json()
        api_patch(f"/api/v2/expenses/{eid}/", ctx["a"], {"title": "Changed"})
        resp = api_post("/api/v2/expenses/bulk/", ctx["a"], {"action": "delete", "ids": [eid], "confirm_token": preview["confirm_token"]})
        assert resp.status_code == 400 and "changed" in resp.json()["error"]
        assert api_get(f"/api/v2/expenses/{eid}/", ctx["a"]).status_code == 200

    def test_token_is_bound_to_its_feuser(self, ctx):
        eid = api_post("/api/v2/expenses/", ctx["a"], {"title": "Mine", "type": "expense", "value": "3"}).json()["id"]
        preview = api_post("/api/v2/expenses/bulk/", ctx["a"], {"action": "delete", "ids": [eid]}).json()
        resp = api_post("/api/v2/expenses/bulk/", ctx["b"], {"action": "delete", "ids": [eid], "confirm_token": preview["confirm_token"]})
        assert resp.status_code == 400
        assert api_get(f"/api/v2/expenses/{eid}/", ctx["a"]).status_code == 200


class TestCatalogSync:

    def test_category_created_via_api_reaches_partner(self, ctx):
        """Partnership onboarding via API, then a catalog write by one partner shows up for the other."""
        assert api_post("/api/v2/partnership/invites/", ctx["a"], {"feuser_id": ctx["b_pk"]}).status_code == 201
        state = api_get("/api/v2/partnership/onboarding/", ctx["b"]).json()
        incomplete = api_post("/api/v2/partnership/onboarding/preview/", ctx["b"], {})
        if state["unmatched_tags"] or state["unmatched_categories"]:
            assert incomplete.status_code == 400 and "Incomplete mapping" in incomplete.json()["error"]
        tag_map = {t: None for t in state["unmatched_tags"]}
        cat_map = {c: None for c in state["unmatched_categories"]}
        preview = api_post("/api/v2/partnership/onboarding/preview/", ctx["b"], {"tag_map": tag_map, "category_map": cat_map}).json()
        resp = api_post("/api/v2/partnership/onboarding/apply/", ctx["b"], {
            "tag_map": tag_map, "category_map": cat_map, "confirm_token": preview["confirm_token"],
        })
        assert resp.status_code == 200, resp.text
        assert api_post("/api/v2/categories/", ctx["a"], {"title": "Synced via API"}).status_code == 201
        titles = [c["title"] for c in api_get("/api/v2/categories/", ctx["b"]).json()["categories"]]
        assert "Synced via API" in titles


class TestProjectDelete:

    def test_needs_matching_name(self, ctx):
        resp = api("DELETE", f"/api/v2/projects/{ctx['pid']}/", ctx["a"], params={"confirm_name": "nope"})
        assert resp.status_code == 400
        resp = api("DELETE", f"/api/v2/projects/{ctx['pid']}/", ctx["a"], params={"confirm_name": "Ibiza"})
        assert resp.status_code == 204
        assert api_get(f"/api/v2/projects/{ctx['pid']}/", ctx["a"]).status_code == 404
