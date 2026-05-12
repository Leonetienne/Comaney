"""
User data isolation: one user cannot read or modify another user's data via the REST API.

Two users (ctx_a and ctx_b) are created. All tests verify that user B's API key
returns 404 when trying to access or modify user A's resources.
"""
import pytest

from helpers import (
    api_get, api_post, api_patch, api_delete, server_today,
    setup_user, cleanup_user,
)


@pytest.fixture(scope="module")
def ctx_a(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


@pytest.fixture(scope="module")
def ctx_b(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestUserIsolation:

    def test_cannot_read_other_users_expense(self, driver, w, ctx_a, ctx_b):
        r = api_post("/api/v1/expenses/", ctx_a, json={
            "title": "Isolation Expense", "type": "expense",
            "value": "1.00", "date_due": server_today(), "settled": True,
        })
        assert r.status_code == 201
        eid = r.json()["id"]

        assert api_get(f"/api/v1/expenses/{eid}/", ctx_b).status_code == 404
        api_delete(f"/api/v1/expenses/{eid}/", ctx_a)

    def test_cannot_patch_other_users_expense(self, driver, w, ctx_a, ctx_b):
        r = api_post("/api/v1/expenses/", ctx_a, json={
            "title": "Isolation Patch", "type": "expense",
            "value": "2.00", "date_due": server_today(), "settled": True,
        })
        assert r.status_code == 201
        eid = r.json()["id"]

        resp = api_patch(f"/api/v1/expenses/{eid}/", ctx_b, json={"title": "Hacked"})
        assert resp.status_code == 404
        api_delete(f"/api/v1/expenses/{eid}/", ctx_a)

    def test_cannot_delete_other_users_expense(self, driver, w, ctx_a, ctx_b):
        r = api_post("/api/v1/expenses/", ctx_a, json={
            "title": "Isolation Delete", "type": "expense",
            "value": "3.00", "date_due": server_today(), "settled": True,
        })
        assert r.status_code == 201
        eid = r.json()["id"]

        assert api_delete(f"/api/v1/expenses/{eid}/", ctx_b).status_code == 404
        assert api_get(f"/api/v1/expenses/{eid}/", ctx_a).status_code == 200
        api_delete(f"/api/v1/expenses/{eid}/", ctx_a)

    def test_cannot_read_other_users_category(self, driver, w, ctx_a, ctx_b):
        r = api_post("/api/v1/categories/", ctx_a, json={"title": "Isolation Cat"})
        assert r.status_code == 201
        cid = r.json()["id"]

        assert api_get(f"/api/v1/categories/{cid}/", ctx_b).status_code == 404
        api_delete(f"/api/v1/categories/{cid}/", ctx_a)

    def test_cannot_patch_other_users_category(self, driver, w, ctx_a, ctx_b):
        r = api_post("/api/v1/categories/", ctx_a, json={"title": "Isolation Cat Patch"})
        assert r.status_code == 201
        cid = r.json()["id"]

        assert api_patch(f"/api/v1/categories/{cid}/", ctx_b, json={"title": "Hacked"}).status_code == 404
        api_delete(f"/api/v1/categories/{cid}/", ctx_a)

    def test_cannot_delete_other_users_category(self, driver, w, ctx_a, ctx_b):
        r = api_post("/api/v1/categories/", ctx_a, json={"title": "Isolation Cat Del"})
        assert r.status_code == 201
        cid = r.json()["id"]

        assert api_delete(f"/api/v1/categories/{cid}/", ctx_b).status_code == 404
        api_delete(f"/api/v1/categories/{cid}/", ctx_a)

    def test_cannot_read_other_users_tag(self, driver, w, ctx_a, ctx_b):
        r = api_post("/api/v1/tags/", ctx_a, json={"title": "Isolation Tag"})
        assert r.status_code == 201
        tid = r.json()["id"]

        assert api_get(f"/api/v1/tags/{tid}/", ctx_b).status_code == 404
        api_delete(f"/api/v1/tags/{tid}/", ctx_a)

    def test_cannot_delete_other_users_tag(self, driver, w, ctx_a, ctx_b):
        r = api_post("/api/v1/tags/", ctx_a, json={"title": "Isolation Tag Del"})
        assert r.status_code == 201
        tid = r.json()["id"]

        assert api_delete(f"/api/v1/tags/{tid}/", ctx_b).status_code == 404
        api_delete(f"/api/v1/tags/{tid}/", ctx_a)

    def test_cannot_read_other_users_scheduled(self, driver, w, ctx_a, ctx_b):
        r = api_post("/api/v1/scheduled/", ctx_a, json={
            "title": "Isolation Sched", "type": "expense",
            "value": "5.00", "repeat_every_factor": 1, "repeat_every_unit": "months",
            "repeat_base_date": server_today(),
        })
        assert r.status_code == 201
        sid = r.json()["id"]

        assert api_get(f"/api/v1/scheduled/{sid}/", ctx_b).status_code == 404
        api_delete(f"/api/v1/scheduled/{sid}/", ctx_a)

    def test_expense_list_does_not_leak_across_users(self, driver, w, ctx_a, ctx_b):
        """User B's expense list must not contain user A's expenses."""
        title = "IsolationListLeak"
        r = api_post("/api/v1/expenses/", ctx_a, json={
            "title": title, "type": "expense",
            "value": "7.00", "date_due": server_today(), "settled": True,
        })
        assert r.status_code == 201
        eid = r.json()["id"]

        resp_b = api_get("/api/v1/expenses/", ctx_b)
        assert resp_b.status_code == 200
        titles = [e["title"] for e in resp_b.json().get("expenses", [])]
        assert title not in titles

        api_delete(f"/api/v1/expenses/{eid}/", ctx_a)
