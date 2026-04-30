"""
Detailed scheduled expense field validation and list view checks.
Requires the API key set up in test_50_profile.py.
"""
from conftest import _url, wait_text, server_today, api_post, api_get


class TestScheduledAdvanced:

    def test_61_scheduled_all_fields_stored(self, driver, w, ctx):
        """All scheduled expense fields should round-trip correctly through the API."""
        today = server_today()
        resp = api_post("/api/v1/scheduled/", ctx, json={
            "title": "Full Field Scheduled",
            "type": "income",
            "value": "123.45",
            "payee": "Scheduled Payee",
            "note": "Scheduled note",
            "repeat_every_factor": 2,
            "repeat_every_unit": "weeks",
            "repeat_base_date": today,
            "default_auto_settle_on_due_date": True,
        })
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["title"] == "Full Field Scheduled"
        assert data["type"] == "income"
        assert data["value"] == "123.45"
        assert data["payee"] == "Scheduled Payee"
        assert data["note"] == "Scheduled note"
        assert data["repeat_every_factor"] == 2
        assert data["repeat_every_unit"] == "weeks"
        assert data["repeat_base_date"] == today
        assert data["default_auto_settle_on_due_date"] is True
        ctx["full_field_scheduled_id"] = data["id"]

        resp2 = api_get(f"/api/v1/scheduled/{data['id']}/", ctx)
        assert resp2.status_code == 200
        d2 = resp2.json()
        assert d2["repeat_every_factor"] == 2
        assert d2["default_auto_settle_on_due_date"] is True

    def test_62_scheduled_list_view_shows_entry(self, driver, w, ctx):
        driver.get(_url("/budget/scheduled/"))
        wait_text(driver, w, "Selenium Scheduled Edited")
