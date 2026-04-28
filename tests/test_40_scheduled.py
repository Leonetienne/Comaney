"""Scheduled expense CRUD via browser."""
import re
from datetime import date

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support import expected_conditions as EC

from conftest import _url, fill, submit, wait_url, wait_text


class TestScheduled:

    # ── Basic CRUD (browser) ────────────────────────────────────────────────

    def test_13_create_scheduled(self, driver, w, ctx):
        today = date.today().isoformat()
        driver.get(_url("/budget/scheduled/new/"))
        fill(w, By.ID, "id_title", "Selenium Scheduled")
        fill(w, By.ID, "id_value", "99.00")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("expense")
        fill(w, By.ID, "id_repeat_every_factor", "1")
        Select(driver.find_element(By.ID, "id_repeat_every_unit")).select_by_value("months")
        driver.execute_script(
            f"document.getElementById('id_repeat_base_date').value = '{today}';"
        )
        submit(w)
        wait_url(w, "/budget/scheduled/")
        wait_text(driver, w, "Selenium Scheduled")

    def test_14_edit_scheduled(self, driver, w, ctx):
        link = w.until(EC.element_to_be_clickable(
            (By.XPATH, "//span[contains(text(),'Selenium Scheduled')]"
                       "/ancestor::div[contains(@class,'exp-card')]"
                       "//a[contains(@href,'/edit/')]")))
        href = link.get_attribute("href")
        ctx["scheduled_uid"] = re.search(r'/scheduled/(\d+)/edit/', href).group(1)
        link.click()
        fill(w, By.ID, "id_title", "Selenium Scheduled Edited")
        submit(w)
        wait_url(w, "/budget/scheduled/")
        wait_text(driver, w, "Selenium Scheduled Edited")

    def test_15_clone_scheduled(self, driver, w, ctx):
        clone_btn = w.until(EC.element_to_be_clickable(
            (By.XPATH, f"//form[contains(@action,'/scheduled/{ctx['scheduled_uid']}/clone/')]"
                       "//button")))
        clone_btn.click()
        wait_url(w, "/edit/")
        w.until(lambda d: "CLONE - Selenium Scheduled Edited" in
                d.find_element(By.ID, "id_title").get_attribute("value"))
        ctx["clone_scheduled_uid"] = re.search(r'/scheduled/(\d+)/edit/', driver.current_url).group(1)
        submit(w)
        wait_url(w, "/budget/scheduled/")

    def test_16_delete_cloned_scheduled(self, driver, w, ctx):
        delete_form = w.until(EC.presence_of_element_located(
            (By.XPATH, f"//form[contains(@action,'/scheduled/{ctx['clone_scheduled_uid']}/delete/')]")))
        driver.execute_script("arguments[0].querySelector('button').click()", delete_form)
        ok_btn = w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok")))
        ok_btn.click()
        w.until(lambda d: d.current_url.rstrip("/").endswith("/budget/scheduled"))

