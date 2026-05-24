"""REST API CRUD: account, dashboard, categories, tags, expenses, scheduled."""
import pytest

from helpers import (
    api_get, api_post, api_patch, api_delete, server_today,
    setup_user, cleanup_user,
)


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestApiAccount:

    def test_patch_account(self, driver, w, ctx):
        resp = api_patch("/api/v1/account/", ctx, json={
            "currency": "EUR", "month_start_day": 1,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["currency"] == "EUR"
        assert data["month_start_day"] == 1

    def test_get_account(self, driver, w, ctx):
        resp = api_get("/api/v1/account/", ctx)
        assert resp.status_code == 200
        assert resp.json()["email"] == ctx["email"]

    def test_dashboard(self, driver, w, ctx):
        resp = api_get("/api/v1/dashboard/", ctx)
        assert resp.status_code == 200
        data = resp.json()
        for key in ("income", "expenses_paid", "expenses_outstanding", "balance", "month_range"):
            assert key in data


class TestApiCategories:

    def test_create(self, driver, w, ctx):
        resp = api_post("/api/v1/categories/", ctx, json={"title": "API Cat"})
        assert resp.status_code == 201
        assert resp.json()["title"] == "API Cat"
        ctx["cat_id"] = resp.json()["id"]

    def test_list(self, driver, w, ctx):
        resp = api_get("/api/v1/categories/", ctx)
        assert resp.status_code == 200
        ids = [c["id"] for c in resp.json()["categories"]]
        assert ctx["cat_id"] in ids

    def test_get(self, driver, w, ctx):
        resp = api_get(f"/api/v1/categories/{ctx['cat_id']}/", ctx)
        assert resp.status_code == 200
        assert resp.json()["title"] == "API Cat"

    def test_patch(self, driver, w, ctx):
        resp = api_patch(f"/api/v1/categories/{ctx['cat_id']}/", ctx, json={"title": "API Cat Renamed"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "API Cat Renamed"

    def test_delete(self, driver, w, ctx):
        resp = api_delete(f"/api/v1/categories/{ctx['cat_id']}/", ctx)
        assert resp.status_code == 204
        assert api_get(f"/api/v1/categories/{ctx['cat_id']}/", ctx).status_code == 404


class TestApiTags:

    def test_create(self, driver, w, ctx):
        resp = api_post("/api/v1/tags/", ctx, json={"title": "API Tag"})
        assert resp.status_code == 201
        ctx["tag_id"] = resp.json()["id"]

    def test_list(self, driver, w, ctx):
        resp = api_get("/api/v1/tags/", ctx)
        assert resp.status_code == 200
        ids = [t["id"] for t in resp.json()["tags"]]
        assert ctx["tag_id"] in ids

    def test_get(self, driver, w, ctx):
        resp = api_get(f"/api/v1/tags/{ctx['tag_id']}/", ctx)
        assert resp.status_code == 200
        assert resp.json()["title"] == "API Tag"

    def test_patch(self, driver, w, ctx):
        resp = api_patch(f"/api/v1/tags/{ctx['tag_id']}/", ctx, json={"title": "API Tag Renamed"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "API Tag Renamed"

    def test_delete(self, driver, w, ctx):
        resp = api_delete(f"/api/v1/tags/{ctx['tag_id']}/", ctx)
        assert resp.status_code == 204
        assert api_get(f"/api/v1/tags/{ctx['tag_id']}/", ctx).status_code == 404


class TestApiExpenses:

    def test_create(self, driver, w, ctx):
        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "API Expense", "type": "expense", "value": "12.34",
            "date_due": server_today(), "settled": True,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "API Expense"
        assert data["value"] == "12.34"
        ctx["exp_id"] = data["id"]

    def test_list(self, driver, w, ctx):
        resp = api_get("/api/v1/expenses/", ctx)
        assert resp.status_code == 200
        ids = [e["id"] for e in resp.json()["expenses"]]
        assert ctx["exp_id"] in ids

    def test_get(self, driver, w, ctx):
        resp = api_get(f"/api/v1/expenses/{ctx['exp_id']}/", ctx)
        assert resp.status_code == 200
        assert resp.json()["title"] == "API Expense"

    def test_patch(self, driver, w, ctx):
        resp = api_patch(f"/api/v1/expenses/{ctx['exp_id']}/", ctx,
                         json={"title": "API Expense Edited", "value": "99.99"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "API Expense Edited"
        assert resp.json()["value"] == "99.99"

    def test_delete(self, driver, w, ctx):
        resp = api_delete(f"/api/v1/expenses/{ctx['exp_id']}/", ctx)
        assert resp.status_code == 204
        assert api_get(f"/api/v1/expenses/{ctx['exp_id']}/", ctx).status_code == 404


class TestApiScheduled:

    def test_create(self, driver, w, ctx):
        resp = api_post("/api/v1/scheduled/", ctx, json={
            "title": "API Scheduled", "type": "expense", "value": "50.00",
            "repeat_every_factor": 1, "repeat_every_unit": "months",
            "repeat_base_date": server_today(),
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "API Scheduled"
        assert data["repeat_every_unit"] == "months"
        ctx["sched_id"] = data["id"]

    def test_list(self, driver, w, ctx):
        resp = api_get("/api/v1/scheduled/", ctx)
        assert resp.status_code == 200
        ids = [s["id"] for s in resp.json()["scheduled"]]
        assert ctx["sched_id"] in ids

    def test_get(self, driver, w, ctx):
        resp = api_get(f"/api/v1/scheduled/{ctx['sched_id']}/", ctx)
        assert resp.status_code == 200
        assert resp.json()["title"] == "API Scheduled"

    def test_patch(self, driver, w, ctx):
        resp = api_patch(f"/api/v1/scheduled/{ctx['sched_id']}/", ctx,
                         json={"title": "API Scheduled Edited", "repeat_every_unit": "weeks"})
        assert resp.status_code == 200
        assert resp.json()["repeat_every_unit"] == "weeks"

    def test_delete(self, driver, w, ctx):
        resp = api_delete(f"/api/v1/scheduled/{ctx['sched_id']}/", ctx)
        assert resp.status_code == 204
        assert api_get(f"/api/v1/scheduled/{ctx['sched_id']}/", ctx).status_code == 404
