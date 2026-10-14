"""
Record ids: uid=<id> and #<id> find one expense, and the opt-in "Show record IDs"
shows them in the expense and recurring expense lists without adding height.
Run with: pytest -v tests/e2e/expenses/test_record_ids.py | tee logfile.log
"""
import time

import pytest
from selenium.webdriver.common.by import By

from bhelpers import _login_as
from helpers import _url, api_get, api_patch, api_post, cleanup_user, setup_user

DATE = "2025-06-15"


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    ids = []
    for title in ("RecId Alpha", "RecId Beta"):
        r = api_post("/api/v2/expenses/", c, json={"title": title, "type": "expense", "value": "5.00", "date_due": DATE})
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    c["alpha"], c["beta"] = ids
    r = api_post("/api/v2/scheduled/", c, json={
        "title": "RecId Rent", "type": "expense", "value": "25.00",
        "repeat_base_date": DATE, "repeat_every_factor": 1, "repeat_every_unit": "months",
    })
    assert r.status_code == 201, r.text
    c["scheduled"] = r.json()["id"]
    _login_as(driver, c)
    yield c
    cleanup_user(c["email"])


def _titles(ctx, q):
    resp = api_get("/api/v2/expenses/", ctx, params={"q": q, "view": "year", "year": 2025})
    assert resp.status_code == 200, resp.text
    return [e["title"] for e in resp.json()["expenses"]]


def test_uid_filter_and_shorthand_find_exactly_one_expense(ctx):
    assert _titles(ctx, f"uid={ctx['alpha']}") == ["RecId Alpha"]
    assert _titles(ctx, f"#{ctx['beta']}") == ["RecId Beta"]
    assert _titles(ctx, f'"#{ctx["beta"]}"') == []


def _expense_card(driver, expense_id):
    driver.get(_url("/budget/expenses/?date_from=2025-01-01&date_to=2025-12-31"))
    time.sleep(2)
    return driver.find_element(By.ID, f"expense-{expense_id}")


def test_record_ids_show_only_when_opted_in_without_growing_the_card(ctx, driver):
    card = _expense_card(driver, ctx["alpha"])
    assert card.find_elements(By.CSS_SELECTOR, ".record-id") == []
    height_off = card.size["height"]

    assert api_patch("/api/v2/account/", ctx, {"show_record_ids": True}).status_code == 200
    card = _expense_card(driver, ctx["alpha"])
    assert card.find_element(By.CSS_SELECTOR, ".record-id").text == f"#{ctx['alpha']}"
    assert card.size["height"] == height_off

    driver.get(_url("/budget/scheduled/"))
    time.sleep(1)
    assert [e.text for e in driver.find_elements(By.CSS_SELECTOR, ".exp-card .record-id")] == [f"#{ctx['scheduled']}"]

    assert api_patch("/api/v2/account/", ctx, {"show_record_ids": False}).status_code == 200
    driver.get(_url("/budget/scheduled/"))
    time.sleep(1)
    assert driver.find_elements(By.CSS_SELECTOR, ".record-id") == []
