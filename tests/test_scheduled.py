"""Scheduled expense CRUD via browser."""
import re

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support import expected_conditions as EC

from helpers import (
    _url, fill, submit, wait_url, wait_text, server_today,
    api_get, api_post, api_delete,
    setup_user, cleanup_user,
)


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestScheduled:

    def test_create(self, driver, w, ctx):
        today = server_today()
        driver.get(_url("/budget/scheduled/new/"))
        fill(w, By.ID, "id_title", "E2E Scheduled")
        fill(w, By.ID, "id_value", "99.00")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("expense")
        fill(w, By.ID, "id_repeat_every_factor", "1")
        Select(driver.find_element(By.ID, "id_repeat_every_unit")).select_by_value("months")
        driver.execute_script(
            f"document.getElementById('id_repeat_base_date').value = '{today}';")
        submit(w)
        wait_url(w, "/budget/scheduled/")
        wait_text(driver, w, "E2E Scheduled")

    def test_edit(self, driver, w, ctx):
        link = w.until(EC.element_to_be_clickable(
            (By.XPATH, "//span[contains(text(),'E2E Scheduled')]"
                       "/ancestor::div[contains(@class,'exp-card')]"
                       "//a[contains(@href,'/edit/')]")))
        ctx["sched_uid"] = re.search(r'/scheduled/(\d+)/edit/', link.get_attribute("href")).group(1)
        link.click()
        fill(w, By.ID, "id_title", "E2E Scheduled Edited")
        submit(w)
        wait_url(w, "/budget/scheduled/")
        wait_text(driver, w, "E2E Scheduled Edited")

    def test_clone(self, driver, w, ctx):
        clone_btn = w.until(EC.element_to_be_clickable(
            (By.XPATH,
             f"//form[contains(@action,'/scheduled/{ctx['sched_uid']}/clone/')]//button")))
        clone_btn.click()
        wait_url(w, "/edit/")
        w.until(lambda d: "CLONE - E2E Scheduled Edited" in
                d.find_element(By.ID, "id_title").get_attribute("value"))
        ctx["clone_uid"] = re.search(r'/scheduled/(\d+)/edit/', driver.current_url).group(1)
        submit(w)
        wait_url(w, "/budget/scheduled/")

    def test_delete_clone(self, driver, w, ctx):
        delete_form = w.until(EC.presence_of_element_located(
            (By.XPATH, f"//form[contains(@action,'/scheduled/{ctx['clone_uid']}/delete/')]")))
        driver.execute_script("arguments[0].querySelector('button').click()", delete_form)
        w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok"))).click()
        wait_url(w, "/budget/scheduled/")
        wait_text(driver, w, "E2E Scheduled Edited")


class TestScheduledAllFields:

    def test_all_fields_round_trip(self, driver, w, ctx):
        today = server_today()
        resp = api_post("/api/v1/scheduled/", ctx, json={
            "title": "E2E Sched Full", "type": "income", "value": "123.45",
            "payee": "Sched Payee", "note": "Sched note",
            "repeat_every_factor": 2, "repeat_every_unit": "weeks",
            "repeat_base_date": today, "default_auto_settle_on_due_date": True,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "E2E Sched Full"
        assert data["type"] == "income"
        assert data["value"] == "123.45"
        assert data["payee"] == "Sched Payee"
        assert data["note"] == "Sched note"
        assert data["repeat_every_factor"] == 2
        assert data["repeat_every_unit"] == "weeks"
        assert data["repeat_base_date"] == today
        assert data["default_auto_settle_on_due_date"] is True

        r2 = api_get(f"/api/v1/scheduled/{data['id']}/", ctx)
        assert r2.status_code == 200
        assert r2.json()["default_auto_settle_on_due_date"] is True

        api_delete(f"/api/v1/scheduled/{data['id']}/", ctx)
