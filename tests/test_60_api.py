"""API CRUD tests for account, categories, tags, expenses, and scheduled expenses."""
from conftest import BASE_URL, api_get, api_post, api_patch, api_delete, server_today
import requests


class TestApi:

    # ── Account ──────────────────────────────────────────────────────────────

    def test_20_api_account_patch(self, driver, w, ctx):
        resp = api_patch("/api/v1/account/", ctx, json={"currency": "€", "month_start_day": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert data["currency"] == "€"
        assert data["month_start_day"] == 1

    def test_21_api_dashboard(self, driver, w, ctx):
        resp = api_get("/api/v1/dashboard/", ctx)
        assert resp.status_code == 200
        data = resp.json()
        assert "income" in data
        assert "expenses_paid" in data
        assert "expenses_outstanding" in data
        assert "balance" in data
        assert "month_range" in data

    # ── Categories ───────────────────────────────────────────────────────────

    def test_22_api_category_create(self, driver, w, ctx):
        resp = api_post("/api/v1/categories/", ctx, json={"title": "API Category"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "API Category"
        ctx["api_cat_id"] = data["id"]

    def test_23_api_category_list(self, driver, w, ctx):
        resp = api_get("/api/v1/categories/", ctx)
        assert resp.status_code == 200
        ids = [c["id"] for c in resp.json()["categories"]]
        assert ctx["api_cat_id"] in ids

    def test_24_api_category_get(self, driver, w, ctx):
        resp = api_get(f"/api/v1/categories/{ctx['api_cat_id']}/", ctx)
        assert resp.status_code == 200
        assert resp.json()["title"] == "API Category"

    def test_25_api_category_patch(self, driver, w, ctx):
        resp = api_patch(f"/api/v1/categories/{ctx['api_cat_id']}/", ctx, json={"title": "API Category Renamed"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "API Category Renamed"

    def test_26_api_category_delete(self, driver, w, ctx):
        resp = api_delete(f"/api/v1/categories/{ctx['api_cat_id']}/", ctx)
        assert resp.status_code == 204
        assert api_get(f"/api/v1/categories/{ctx['api_cat_id']}/", ctx).status_code == 404

    # ── Tags ─────────────────────────────────────────────────────────────────

    def test_27_api_tag_create(self, driver, w, ctx):
        resp = api_post("/api/v1/tags/", ctx, json={"title": "API Tag"})
        assert resp.status_code == 201
        assert resp.json()["title"] == "API Tag"
        ctx["api_tag_id"] = resp.json()["id"]

    def test_28_api_tag_list(self, driver, w, ctx):
        resp = api_get("/api/v1/tags/", ctx)
        assert resp.status_code == 200
        ids = [t["id"] for t in resp.json()["tags"]]
        assert ctx["api_tag_id"] in ids

    def test_29_api_tag_get(self, driver, w, ctx):
        resp = api_get(f"/api/v1/tags/{ctx['api_tag_id']}/", ctx)
        assert resp.status_code == 200
        assert resp.json()["title"] == "API Tag"

    def test_30_api_tag_patch(self, driver, w, ctx):
        resp = api_patch(f"/api/v1/tags/{ctx['api_tag_id']}/", ctx, json={"title": "API Tag Renamed"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "API Tag Renamed"

    def test_31_api_tag_delete(self, driver, w, ctx):
        resp = api_delete(f"/api/v1/tags/{ctx['api_tag_id']}/", ctx)
        assert resp.status_code == 204
        assert api_get(f"/api/v1/tags/{ctx['api_tag_id']}/", ctx).status_code == 404

    # ── Expenses ─────────────────────────────────────────────────────────────

    def test_32_api_expense_create(self, driver, w, ctx):
        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "API Expense", "type": "expense", "value": "12.34",
            "date_due": server_today(), "settled": True,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "API Expense"
        assert data["value"] == "12.34"
        ctx["api_expense_id"] = data["id"]

    def test_33_api_expense_list(self, driver, w, ctx):
        resp = api_get("/api/v1/expenses/", ctx)
        assert resp.status_code == 200
        ids = [e["id"] for e in resp.json()["expenses"]]
        assert ctx["api_expense_id"] in ids

    def test_34_api_expense_get(self, driver, w, ctx):
        resp = api_get(f"/api/v1/expenses/{ctx['api_expense_id']}/", ctx)
        assert resp.status_code == 200
        assert resp.json()["title"] == "API Expense"

    def test_35_api_expense_patch(self, driver, w, ctx):
        resp = api_patch(f"/api/v1/expenses/{ctx['api_expense_id']}/", ctx,
                         json={"title": "API Expense Edited", "value": "99.99"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "API Expense Edited"
        assert data["value"] == "99.99"

    def test_36_api_expense_delete(self, driver, w, ctx):
        resp = api_delete(f"/api/v1/expenses/{ctx['api_expense_id']}/", ctx)
        assert resp.status_code == 204
        assert api_get(f"/api/v1/expenses/{ctx['api_expense_id']}/", ctx).status_code == 404

    # ── Scheduled expenses ────────────────────────────────────────────────────

    def test_37_api_scheduled_create(self, driver, w, ctx):
        resp = api_post("/api/v1/scheduled/", ctx, json={
            "title": "API Scheduled", "type": "expense", "value": "50.00",
            "repeat_every_factor": 1, "repeat_every_unit": "months",
            "repeat_base_date": server_today(),
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "API Scheduled"
        assert data["repeat_every_unit"] == "months"
        ctx["api_scheduled_id"] = data["id"]

    def test_38_api_scheduled_list(self, driver, w, ctx):
        resp = api_get("/api/v1/scheduled/", ctx)
        assert resp.status_code == 200
        ids = [s["id"] for s in resp.json()["scheduled"]]
        assert ctx["api_scheduled_id"] in ids

    def test_39_api_scheduled_get(self, driver, w, ctx):
        resp = api_get(f"/api/v1/scheduled/{ctx['api_scheduled_id']}/", ctx)
        assert resp.status_code == 200
        assert resp.json()["title"] == "API Scheduled"

    def test_40_api_scheduled_patch(self, driver, w, ctx):
        resp = api_patch(f"/api/v1/scheduled/{ctx['api_scheduled_id']}/", ctx,
                         json={"title": "API Scheduled Edited", "repeat_every_unit": "weeks"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "API Scheduled Edited"
        assert data["repeat_every_unit"] == "weeks"

    def test_41_api_scheduled_delete(self, driver, w, ctx):
        resp = api_delete(f"/api/v1/scheduled/{ctx['api_scheduled_id']}/", ctx)
        assert resp.status_code == 204
        assert api_get(f"/api/v1/scheduled/{ctx['api_scheduled_id']}/", ctx).status_code == 404
