"""Field-length and choice validation tests for the API."""
from conftest import api_get, api_post, api_patch, server_today


LONG_128 = "x" * 129
LONG_1024 = "x" * 1025


class TestApiValidation:

    # ── Account ──────────────────────────────────────────────────────────────

    def test_v01_account_first_name_too_long(self, driver, w, ctx):
        resp = api_patch("/api/v1/account/", ctx, json={"first_name": LONG_128})
        assert resp.status_code == 400

    def test_v02_account_last_name_too_long(self, driver, w, ctx):
        resp = api_patch("/api/v1/account/", ctx, json={"last_name": LONG_128})
        assert resp.status_code == 400

    def test_v03_account_currency_too_long(self, driver, w, ctx):
        resp = api_patch("/api/v1/account/", ctx, json={"currency": "TOOLONGVALUE"})
        assert resp.status_code == 400

    def test_v04_account_month_start_day_too_high(self, driver, w, ctx):
        resp = api_patch("/api/v1/account/", ctx, json={"month_start_day": 32})
        assert resp.status_code == 400

    def test_v05_account_month_start_day_zero(self, driver, w, ctx):
        resp = api_patch("/api/v1/account/", ctx, json={"month_start_day": 0})
        assert resp.status_code == 400

    def test_v06_account_invalid_allowance_action(self, driver, w, ctx):
        resp = api_patch("/api/v1/account/", ctx, json={"unspent_allowance_action": "drop_it"})
        assert resp.status_code == 400

    # ── Categories ───────────────────────────────────────────────────────────

    def test_v07_category_title_too_long(self, driver, w, ctx):
        resp = api_post("/api/v1/categories/", ctx, json={"title": LONG_128})
        assert resp.status_code == 400

    def test_v08_category_patch_title_too_long(self, driver, w, ctx):
        cat = api_post("/api/v1/categories/", ctx, json={"title": "Val Cat"}).json()
        resp = api_patch(f"/api/v1/categories/{cat['id']}/", ctx, json={"title": LONG_128})
        assert resp.status_code == 400

    # ── Tags ─────────────────────────────────────────────────────────────────

    def test_v09_tag_title_too_long(self, driver, w, ctx):
        resp = api_post("/api/v1/tags/", ctx, json={"title": LONG_128})
        assert resp.status_code == 400

    def test_v10_tag_patch_title_too_long(self, driver, w, ctx):
        tag = api_post("/api/v1/tags/", ctx, json={"title": "Val Tag"}).json()
        resp = api_patch(f"/api/v1/tags/{tag['id']}/", ctx, json={"title": LONG_128})
        assert resp.status_code == 400

    # ── Expenses ─────────────────────────────────────────────────────────────

    def test_v11_expense_title_too_long(self, driver, w, ctx):
        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": LONG_128, "type": "expense", "value": "1.00",
            "date_due": server_today(), "settled": True,
        })
        assert resp.status_code == 400

    def test_v12_expense_payee_too_long(self, driver, w, ctx):
        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "Val Expense", "type": "expense", "value": "1.00",
            "date_due": server_today(), "settled": True, "payee": LONG_128,
        })
        assert resp.status_code == 400

    def test_v13_expense_note_too_long(self, driver, w, ctx):
        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "Val Expense", "type": "expense", "value": "1.00",
            "date_due": server_today(), "settled": True, "note": LONG_1024,
        })
        assert resp.status_code == 400

    def test_v14_expense_invalid_type(self, driver, w, ctx):
        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "Val Expense", "type": "carry_over", "value": "1.00",
            "date_due": server_today(), "settled": True,
        })
        assert resp.status_code == 400

    def test_v15_expense_patch_title_too_long(self, driver, w, ctx):
        exp = api_post("/api/v1/expenses/", ctx, json={
            "title": "Val Expense", "type": "expense", "value": "1.00",
            "date_due": server_today(), "settled": True,
        }).json()
        resp = api_patch(f"/api/v1/expenses/{exp['id']}/", ctx, json={"title": LONG_128})
        assert resp.status_code == 400

    def test_v16_expense_patch_invalid_type(self, driver, w, ctx):
        exp = api_post("/api/v1/expenses/", ctx, json={
            "title": "Val Expense", "type": "expense", "value": "1.00",
            "date_due": server_today(), "settled": True,
        }).json()
        resp = api_patch(f"/api/v1/expenses/{exp['id']}/", ctx, json={"type": "nope"})
        assert resp.status_code == 400

    # ── Scheduled expenses ────────────────────────────────────────────────────

    def test_v17_scheduled_title_too_long(self, driver, w, ctx):
        resp = api_post("/api/v1/scheduled/", ctx, json={
            "title": LONG_128, "type": "expense", "value": "1.00",
            "repeat_every_factor": 1, "repeat_every_unit": "months",
            "repeat_base_date": server_today(),
        })
        assert resp.status_code == 400

    def test_v18_scheduled_payee_too_long(self, driver, w, ctx):
        resp = api_post("/api/v1/scheduled/", ctx, json={
            "title": "Val Sched", "type": "expense", "value": "1.00",
            "repeat_every_factor": 1, "repeat_every_unit": "months",
            "repeat_base_date": server_today(), "payee": LONG_128,
        })
        assert resp.status_code == 400

    def test_v19_scheduled_note_too_long(self, driver, w, ctx):
        resp = api_post("/api/v1/scheduled/", ctx, json={
            "title": "Val Sched", "type": "expense", "value": "1.00",
            "repeat_every_factor": 1, "repeat_every_unit": "months",
            "repeat_base_date": server_today(), "note": LONG_1024,
        })
        assert resp.status_code == 400

    def test_v20_scheduled_invalid_type(self, driver, w, ctx):
        resp = api_post("/api/v1/scheduled/", ctx, json={
            "title": "Val Sched", "type": "carry_over", "value": "1.00",
            "repeat_every_factor": 1, "repeat_every_unit": "months",
            "repeat_base_date": server_today(),
        })
        assert resp.status_code == 400

    def test_v21_scheduled_invalid_repeat_unit(self, driver, w, ctx):
        resp = api_post("/api/v1/scheduled/", ctx, json={
            "title": "Val Sched", "type": "expense", "value": "1.00",
            "repeat_every_factor": 1, "repeat_every_unit": "decades",
            "repeat_base_date": server_today(),
        })
        assert resp.status_code == 400
