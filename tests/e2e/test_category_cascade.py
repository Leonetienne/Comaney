"""
Category and tag cascade behavior:
- Deleting a category via UI sets expense.category to NULL (verified in expense edit form)
- Deleting a tag via UI removes it from expense.tags (verified in expense edit form)
- API confirms the same for scheduled expenses
"""
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from helpers import (
    _url,
    api_post, api_get, api_delete, server_today,
    setup_user, cleanup_user,
)


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestCategoryCascade:

    def test_delete_category_nullifies_expense_category(self, driver, w, ctx):
        # Setup via API: create category and expense assigned to it
        cat = api_post("/api/v1/categories/", ctx, json={"title": "CascadeCat"})
        assert cat.status_code == 201
        cat_id = cat.json()["id"]

        exp = api_post("/api/v1/expenses/", ctx, json={
            "title": "CascadeExpense", "type": "expense",
            "value": "10.00", "date_due": server_today(), "settled": True,
            "category_id": cat_id,
        })
        assert exp.status_code == 201
        eid = exp.json()["id"]

        # Action via UI: delete category from categories/tags page
        driver.get(_url("/budget/categories-tags/"))
        time.sleep(1)
        btn = w.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, f"#category-{cat_id} .ct-delete")))
        btn.click()
        w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok"))).click()
        time.sleep(1)

        # Verify via UI: expense edit form shows no category selected
        driver.get(_url(f"/budget/expenses/{eid}/edit/"))
        time.sleep(1)
        cat_select = driver.find_element(By.ID, "id_category")
        selected_value = cat_select.find_element(By.CSS_SELECTOR, "option:checked").get_attribute("value")
        assert selected_value == "", (
            f"Expense category must be blank after deleting the category; got: {selected_value!r}"
        )

        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_delete_tag_removes_from_expense(self, driver, w, ctx):
        # Setup via API: create tag and expense with that tag
        tag = api_post("/api/v1/tags/", ctx, json={"title": "CascadeTagUI"})
        assert tag.status_code == 201
        tag_id = tag.json()["id"]

        exp = api_post("/api/v1/expenses/", ctx, json={
            "title": "TagCascadeExpenseUI", "type": "expense",
            "value": "5.00", "date_due": server_today(), "settled": True,
            "tag_ids": [tag_id],
        })
        assert exp.status_code == 201
        eid = exp.json()["id"]

        # Action via UI: delete tag from categories/tags page
        driver.get(_url("/budget/categories-tags/"))
        time.sleep(1)
        btn = w.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, f"#tag-{tag_id} .ct-delete")))
        btn.click()
        w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok"))).click()
        time.sleep(1)

        # Verify via UI: the tag no longer appears in the expense edit form
        driver.get(_url(f"/budget/expenses/{eid}/edit/"))
        time.sleep(1)
        tag_wrap_text = driver.find_element(By.CSS_SELECTOR, ".tag-cb-wrap").text
        assert "CascadeTagUI" not in tag_wrap_text, (
            "Deleted tag must not appear as a checkbox in the expense edit form"
        )

        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_delete_category_nullifies_scheduled_category(self, driver, w, ctx):
        # Setup via API
        cat = api_post("/api/v1/categories/", ctx, json={"title": "CascadeSchedCat"})
        assert cat.status_code == 201
        cat_id = cat.json()["id"]

        sched = api_post("/api/v1/scheduled/", ctx, json={
            "title": "CascadeSchedExp", "type": "expense", "value": "20.00",
            "repeat_every_factor": 1, "repeat_every_unit": "months",
            "repeat_base_date": server_today(),
            "category_id": cat_id,
        })
        assert sched.status_code == 201
        sid = sched.json()["id"]

        # Action via UI: delete category
        driver.get(_url("/budget/categories-tags/"))
        time.sleep(1)
        btn = w.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, f"#category-{cat_id} .ct-delete")))
        btn.click()
        w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok"))).click()
        time.sleep(1)

        # Verify via UI: scheduled expense edit form shows no category
        driver.get(_url(f"/budget/scheduled/{sid}/edit/"))
        time.sleep(1)
        cat_select = driver.find_element(By.ID, "id_category")
        selected_value = cat_select.find_element(By.CSS_SELECTOR, "option:checked").get_attribute("value")
        assert selected_value == "", (
            "Scheduled expense category must be blank after deleting the category"
        )

        api_delete(f"/api/v1/scheduled/{sid}/", ctx)

    def test_delete_tag_removes_from_scheduled(self, driver, w, ctx):
        # Setup via API
        tag = api_post("/api/v1/tags/", ctx, json={"title": "SchedTagCascadeUI"})
        assert tag.status_code == 201
        tag_id = tag.json()["id"]

        sched = api_post("/api/v1/scheduled/", ctx, json={
            "title": "TagCascadeSchedUI", "type": "expense", "value": "15.00",
            "repeat_every_factor": 1, "repeat_every_unit": "months",
            "repeat_base_date": server_today(),
            "tag_ids": [tag_id],
        })
        assert sched.status_code == 201
        sid = sched.json()["id"]

        # Action via UI: delete tag
        driver.get(_url("/budget/categories-tags/"))
        time.sleep(1)
        btn = w.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, f"#tag-{tag_id} .ct-delete")))
        btn.click()
        w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok"))).click()
        time.sleep(1)

        # Verify via UI: scheduled expense edit form no longer shows the tag
        driver.get(_url(f"/budget/scheduled/{sid}/edit/"))
        time.sleep(1)
        tag_wrap_text = driver.find_element(By.CSS_SELECTOR, ".tag-cb-wrap").text
        assert "SchedTagCascadeUI" not in tag_wrap_text, (
            "Deleted tag must not appear as a checkbox in the scheduled expense edit form"
        )

        api_delete(f"/api/v1/scheduled/{sid}/", ctx)
