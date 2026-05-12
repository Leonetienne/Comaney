"""Scheduled expense CRUD via browser."""
import re
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support import expected_conditions as EC

from helpers import (
    _url, fill, submit, wait_url, wait_text, server_today,
    api_delete,
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
        driver.get(_url("/budget/scheduled/new/"))
        time.sleep(1)
        fill(w, By.ID, "id_title", "E2E Sched Full")
        fill(w, By.ID, "id_value", "123.45")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("income")
        fill(w, By.ID, "id_repeat_every_factor", "2")
        Select(driver.find_element(By.ID, "id_repeat_every_unit")).select_by_value("weeks")
        fill(w, By.ID, "id_payee", "Sched Payee")
        fill(w, By.ID, "id_note", "Sched note")
        driver.execute_script(
            f"document.getElementById('id_repeat_base_date').value = '{today}';"
            "document.getElementById('id_default_auto_settle_on_due_date').checked = true;"
        )
        submit(w)
        time.sleep(2)
        assert "E2E Sched Full" in driver.page_source
        # Find the edit link from the list and verify all fields round-trip
        link = driver.find_element(By.XPATH,
            "//span[contains(text(),'E2E Sched Full')]"
            "/ancestor::div[contains(@class,'exp-card')]"
            "//a[contains(@href,'/edit/')]"
        )
        sid = re.search(r"/scheduled/(\d+)/edit/", link.get_attribute("href")).group(1)
        driver.get(_url(f"/budget/scheduled/{sid}/edit/"))
        time.sleep(1)
        assert driver.find_element(By.ID, "id_title").get_attribute("value") == "E2E Sched Full"
        assert driver.find_element(By.ID, "id_value").get_attribute("value") == "123.45"
        assert driver.find_element(By.ID, "id_payee").get_attribute("value") == "Sched Payee"
        assert driver.find_element(By.ID, "id_note").get_attribute("value") == "Sched note"
        assert driver.find_element(By.ID, "id_default_auto_settle_on_due_date").is_selected()
        assert Select(driver.find_element(By.ID, "id_type")).first_selected_option.get_attribute("value") == "income"
        assert Select(driver.find_element(By.ID, "id_repeat_every_unit")).first_selected_option.get_attribute("value") == "weeks"
        api_delete(f"/api/v1/scheduled/{sid}/", ctx)
