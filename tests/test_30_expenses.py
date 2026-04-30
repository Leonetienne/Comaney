"""Expense CRUD via browser."""
import re
from datetime import date

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support import expected_conditions as EC

from conftest import _url, fill, server_today, submit, wait_url, wait_text


class TestExpenses:

    # ── Basic CRUD (browser) ────────────────────────────────────────────────

    def test_09_create_expense(self, driver, w, ctx):
        today = server_today()
        driver.get(_url("/budget/expenses/new/"))
        fill(w, By.ID, "id_title", "Selenium Expense")
        fill(w, By.ID, "id_value", "42.00")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("expense")
        driver.execute_script(f"""
            document.getElementById('id_date_due').value = '{today}';
            document.getElementById('id_settled').checked = true;
        """)
        submit(w)
        w.until(lambda d: d.current_url.rstrip("/").endswith("/budget/expenses"))
        wait_text(driver, w, "Selenium Expense")

    def test_10_edit_expense(self, driver, w, ctx):
        link = w.until(EC.element_to_be_clickable(
            (By.XPATH, "//span[contains(text(),'Selenium Expense')]"
                       "/ancestor::div[contains(@class,'exp-card')]"
                       "//a[contains(@href,'/edit/')]")))
        href = link.get_attribute("href")
        ctx["expense_uid"] = re.search(r'/expenses/(\d+)/edit/', href).group(1)
        link.click()
        fill(w, By.ID, "id_title", "Selenium Expense Edited")
        submit(w)
        wait_url(w, "/budget/expenses/")
        wait_text(driver, w, "Selenium Expense Edited")

    def test_11_clone_expense(self, driver, w, ctx):
        clone_btn = w.until(EC.element_to_be_clickable(
            (By.XPATH, f"//form[contains(@action,'/expenses/{ctx['expense_uid']}/clone/')]"
                       "//button")))
        clone_btn.click()
        wait_url(w, "/edit/")
        w.until(lambda d: "CLONE - Selenium Expense Edited" in
                d.find_element(By.ID, "id_title").get_attribute("value"))
        ctx["clone_expense_uid"] = re.search(r'/expenses/(\d+)/edit/', driver.current_url).group(1)
        submit(w)
        wait_url(w, "/budget/expenses/")

    def test_12_delete_cloned_expense(self, driver, w, ctx):
        delete_form = w.until(EC.presence_of_element_located(
            (By.XPATH, f"//form[contains(@action,'/expenses/{ctx['clone_expense_uid']}/delete/')]")))
        driver.execute_script("arguments[0].querySelector('button').click()", delete_form)
        ok_btn = w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok")))
        ok_btn.click()
        w.until(lambda d: d.current_url.rstrip("/").endswith("/budget/expenses"))
        wait_text(driver, w, "Selenium Expense Edited")
        w.until(lambda d: "CLONE - Selenium Expense Edited" not in d.page_source)

