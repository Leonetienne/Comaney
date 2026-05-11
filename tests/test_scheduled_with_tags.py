"""
Scheduled expenses with categories and tags:
- Create with category and multiple tags via browser form, verify in edit form
- Edit to change category and tags via browser, verify in edit form
- Generated expense inherits category and tags from the scheduled template (API check)
"""
import re
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from helpers import (
    _url, fill, submit,
    api_get, api_post, api_delete, run_cmd, server_today,
    setup_user, cleanup_user,
)


def _check_tag(driver, tag_title):
    """Select the tag checkbox for the given title if not already checked."""
    label = driver.find_element(
        By.XPATH,
        f"//div[contains(@class,'tag-cb-wrap')]//label[normalize-space()='{tag_title}']",
    )
    checkbox = driver.find_element(By.ID, label.get_attribute("for"))
    if not checkbox.is_selected():
        label.click()
        time.sleep(0.1)


def _uncheck_tag(driver, tag_title):
    """Deselect the tag checkbox for the given title if currently checked."""
    label = driver.find_element(
        By.XPATH,
        f"//div[contains(@class,'tag-cb-wrap')]//label[normalize-space()='{tag_title}']",
    )
    checkbox = driver.find_element(By.ID, label.get_attribute("for"))
    if checkbox.is_selected():
        label.click()
        time.sleep(0.1)


def _tag_is_checked(driver, tag_title) -> bool:
    label = driver.find_element(
        By.XPATH,
        f"//div[contains(@class,'tag-cb-wrap')]//label[normalize-space()='{tag_title}']",
    )
    return driver.find_element(By.ID, label.get_attribute("for")).is_selected()


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


@pytest.fixture(scope="module")
def cat_id(ctx):
    r = api_post("/api/v1/categories/", ctx, json={"title": "SchedCat"})
    assert r.status_code == 201
    cid = r.json()["id"]
    yield cid
    api_delete(f"/api/v1/categories/{cid}/", ctx)


@pytest.fixture(scope="module")
def cat2_id(ctx):
    r = api_post("/api/v1/categories/", ctx, json={"title": "SchedCatAlt"})
    assert r.status_code == 201
    cid = r.json()["id"]
    yield cid
    api_delete(f"/api/v1/categories/{cid}/", ctx)


@pytest.fixture(scope="module")
def tag_a_id(ctx):
    r = api_post("/api/v1/tags/", ctx, json={"title": "SchedTagA"})
    assert r.status_code == 201
    tid = r.json()["id"]
    yield tid
    api_delete(f"/api/v1/tags/{tid}/", ctx)


@pytest.fixture(scope="module")
def tag_b_id(ctx):
    r = api_post("/api/v1/tags/", ctx, json={"title": "SchedTagB"})
    assert r.status_code == 201
    tid = r.json()["id"]
    yield tid
    api_delete(f"/api/v1/tags/{tid}/", ctx)


class TestScheduledWithCategoryAndTags:

    def test_create_with_category_and_tags(
        self, driver, w, ctx, cat_id, tag_a_id, tag_b_id
    ):
        today = server_today()
        driver.get(_url("/budget/scheduled/new/"))
        time.sleep(1)
        fill(w, By.ID, "id_title", "SchedWithMeta")
        fill(w, By.ID, "id_value", "30.00")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("expense")
        fill(w, By.ID, "id_repeat_every_factor", "1")
        Select(driver.find_element(By.ID, "id_repeat_every_unit")).select_by_value("months")
        driver.execute_script(
            f"document.getElementById('id_repeat_base_date').value = '{today}';"
        )
        Select(driver.find_element(By.ID, "id_category")).select_by_visible_text("SchedCat")
        _check_tag(driver, "SchedTagA")
        _check_tag(driver, "SchedTagB")
        submit(w)
        time.sleep(2)

        assert "/budget/scheduled/" in driver.current_url
        assert "SchedWithMeta" in driver.page_source

        link = driver.find_element(
            By.XPATH,
            "//span[contains(text(),'SchedWithMeta')]"
            "/ancestor::div[contains(@class,'exp-card')]"
            "//a[contains(@href,'/edit/')]",
        )
        ctx["sched_meta_uid"] = re.search(
            r"/scheduled/(\d+)/edit/", link.get_attribute("href")
        ).group(1)

    def test_edit_form_shows_category_and_tags(
        self, driver, w, ctx, cat_id, tag_a_id, tag_b_id
    ):
        driver.get(_url(f"/budget/scheduled/{ctx['sched_meta_uid']}/edit/"))
        time.sleep(1)

        selected_val = driver.find_element(By.ID, "id_category").find_element(
            By.CSS_SELECTOR, "option:checked"
        ).get_attribute("value")
        assert selected_val == str(cat_id), "Category must be selected after creation"
        assert _tag_is_checked(driver, "SchedTagA"), "SchedTagA must be checked"
        assert _tag_is_checked(driver, "SchedTagB"), "SchedTagB must be checked"

    def test_edit_changes_category_and_tags(
        self, driver, w, ctx, cat2_id, tag_a_id, tag_b_id
    ):
        driver.get(_url(f"/budget/scheduled/{ctx['sched_meta_uid']}/edit/"))
        time.sleep(1)
        Select(driver.find_element(By.ID, "id_category")).select_by_visible_text("SchedCatAlt")
        _uncheck_tag(driver, "SchedTagA")
        _uncheck_tag(driver, "SchedTagB")
        submit(w)
        time.sleep(2)

        driver.get(_url(f"/budget/scheduled/{ctx['sched_meta_uid']}/edit/"))
        time.sleep(1)
        selected_val = driver.find_element(By.ID, "id_category").find_element(
            By.CSS_SELECTOR, "option:checked"
        ).get_attribute("value")
        assert selected_val == str(cat2_id), "Category must reflect edit"
        assert not _tag_is_checked(driver, "SchedTagA"), "SchedTagA must be unchecked"
        assert not _tag_is_checked(driver, "SchedTagB"), "SchedTagB must be unchecked"

    def test_clear_category(self, driver, w, ctx):
        driver.get(_url(f"/budget/scheduled/{ctx['sched_meta_uid']}/edit/"))
        time.sleep(1)
        Select(driver.find_element(By.ID, "id_category")).select_by_value("")
        submit(w)
        time.sleep(2)

        driver.get(_url(f"/budget/scheduled/{ctx['sched_meta_uid']}/edit/"))
        time.sleep(1)
        selected_val = driver.find_element(By.ID, "id_category").find_element(
            By.CSS_SELECTOR, "option:checked"
        ).get_attribute("value")
        assert selected_val == "", "Category must be blank after clearing"

    def test_cleanup(self, driver, w, ctx):
        uid = ctx.pop("sched_meta_uid", None)
        if uid:
            api_delete(f"/api/v1/scheduled/{uid}/", ctx)


class TestGeneratedExpenseInheritsMetadata:

    def test_generated_expense_inherits_category_and_tags(self, driver, w, ctx):
        """
        Background job behavior: generate via cron, verify inheritance via API.
        The API is independently covered by test_api.py; generation is not a UI action.
        """
        today = server_today()
        cat = api_post("/api/v1/categories/", ctx, json={"title": "InheritCat"})
        tag = api_post("/api/v1/tags/",       ctx, json={"title": "InheritTag"})
        assert cat.status_code == 201 and tag.status_code == 201
        cat_id = cat.json()["id"]
        tag_id = tag.json()["id"]

        sched = api_post("/api/v1/scheduled/", ctx, json={
            "title": "InheritSched", "type": "expense", "value": "25.00",
            "repeat_every_factor": 1, "repeat_every_unit": "months",
            "repeat_base_date": today,
            "category_id": cat_id,
            "tag_ids": [tag_id],
        })
        assert sched.status_code == 201
        sched_id = sched.json()["id"]

        run_cmd("generate_scheduled_expenses")
        time.sleep(2)

        expenses = api_get("/api/v1/expenses/", ctx, params={"q": "InheritSched"})
        assert expenses.status_code == 200
        matches = expenses.json().get("expenses", [])
        assert matches, "Cron must have generated an expense from the scheduled template"

        generated = matches[0]
        assert generated["category"] is not None
        assert generated["category"]["id"] == cat_id
        assert any(t["id"] == tag_id for t in generated["tags"])

        api_delete(f"/api/v1/expenses/{generated['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sched_id}/", ctx)
        api_delete(f"/api/v1/categories/{cat_id}/", ctx)
        api_delete(f"/api/v1/tags/{tag_id}/", ctx)
