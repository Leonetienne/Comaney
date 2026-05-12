"""
Account data export (ZIP):
- Returns application/zip
- Contains all expected CSV files
- Expense and category data appears in the correct CSV
- anthropic_api_key is masked (only last 4 chars visible)
- Unauthenticated request is redirected
"""
import io
import time
import zipfile

import pytest
import requests
from selenium.webdriver.common.by import By

from helpers import (
    _url, fill,
    api_post, api_delete, server_today,
    session_cookies, setup_user, cleanup_user,
)


def _get_export(driver):
    """Download the export ZIP using the browser's session cookies."""
    cookies = session_cookies(driver)
    return requests.get(_url("/account/export/"), cookies=cookies, timeout=30)


def _submit_form(driver, action_value):
    driver.execute_script(
        f"document.querySelector(\"input[name='action'][value='{action_value}']\").closest('form').submit()"
    )


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestDataExport:

    def test_export_returns_zip(self, driver, w, ctx):
        resp = _get_export(driver)
        assert resp.status_code == 200
        assert "application/zip" in resp.headers.get("Content-Type", "")
        assert resp.content[:2] == b"PK", "Response must be a valid ZIP file"

    def test_export_contains_all_csvs(self, driver, w, ctx):
        resp = _get_export(driver)
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            names = zf.namelist()
        for expected in (
            "profile.csv",
            "categories.csv",
            "tags.csv",
            "expenses.csv",
            "scheduled_expenses.csv",
            "dashboard_cards.csv",
        ):
            assert expected in names, f"{expected} missing from export ZIP"

    def test_expense_appears_in_export(self, driver, w, ctx):
        r = api_post("/api/v1/expenses/", ctx, json={
            "title": "ExportTestExpense",
            "type": "expense",
            "value": "99.99",
            "date_due": server_today(),
            "settled": True,
        })
        assert r.status_code == 201
        eid = r.json()["id"]

        resp = _get_export(driver)
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            expenses_csv = zf.read("expenses.csv").decode()
        assert "ExportTestExpense" in expenses_csv

        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_profile_email_in_export(self, driver, w, ctx):
        resp = _get_export(driver)
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            profile_csv = zf.read("profile.csv").decode()
        assert ctx["email"] in profile_csv

    def test_anthropic_key_masked_in_export(self, driver, w, ctx):
        fake_key = "sk-ant-api03-exporttest9999"
        driver.get(_url("/profile/"))
        time.sleep(1)
        fill(w, By.ID, "id_anthropic_api_key", fake_key)
        fill(w, By.ID, "id_ai_custom_instructions", "")
        _submit_form(driver, "ai")
        time.sleep(2)
        assert "Saved." in driver.page_source

        resp = _get_export(driver)
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            profile_csv = zf.read("profile.csv").decode()

        assert fake_key not in profile_csv, "Full API key must not appear in export"
        assert "9999" in profile_csv, "Last 4 chars of key must be visible in export"

        # Clear the key
        driver.get(_url("/profile/"))
        time.sleep(1)
        driver.find_element(By.ID, "id_anthropic_api_key").clear()
        fill(w, By.ID, "id_ai_custom_instructions", "")
        _submit_form(driver, "ai")
        time.sleep(2)

    def test_category_appears_in_export(self, driver, w, ctx):
        r = api_post("/api/v1/categories/", ctx, json={"title": "ExportCat"})
        assert r.status_code == 201
        cat_id = r.json()["id"]

        resp = _get_export(driver)
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            cats_csv = zf.read("categories.csv").decode()
        assert "ExportCat" in cats_csv

        api_delete(f"/api/v1/categories/{cat_id}/", ctx)

    def test_export_requires_authentication(self, driver, w, ctx):
        resp = requests.get(_url("/account/export/"), timeout=10, allow_redirects=False)
        assert resp.status_code in (302, 403), (
            f"Unauthenticated export must redirect or deny, got {resp.status_code}"
        )
