"""
Teardown: API key revoke, full account export, category/tag cleanup, account deletion.
Must run last.
"""
import time
import zipfile
import io

import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from conftest import _url, click, fill, wait_url, wait_text, BASE_URL, PASSWORD, session_cookies


class TestTeardown:

    def test_42_revoke_api_key(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        wait_text(driver, w, "Personal info")
        click(w, By.XPATH, "//form[contains(@action,'api-key/revoke')]//button")
        wait_url(w, "/profile/")
        time.sleep(1)  # give the server a beat before testing the key is dead
        resp = requests.get(
            f"{BASE_URL}/api/v1/account/",
            headers={"Authorization": f"Bearer {ctx['api_key']}"},
            timeout=10,
        )
        assert resp.status_code == 401, "Revoked key should return 401"

    def test_91_account_export_csv_zip(self, driver, w, ctx):
        """The account export should return a valid ZIP containing expected CSVs."""
        cookies = session_cookies(driver)
        resp = requests.get(_url("/account/export/"), cookies=cookies, timeout=15)
        assert resp.status_code == 200
        assert "application/zip" in resp.headers.get("Content-Type", ""), (
            f"Expected zip, got {resp.headers.get('Content-Type')}")
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        names = zf.namelist()
        for expected in ("profile.csv", "categories.csv", "tags.csv",
                         "expenses.csv", "scheduled_expenses.csv"):
            assert expected in names, f"Missing {expected} in export zip"

        # expenses.csv should contain the selenium expense we created
        expenses_csv = zf.read("expenses.csv").decode("utf-8")
        assert "Selenium Expense Edited" in expenses_csv

    def _delete_ct_item(self, driver, w, item_id):
        btn = w.until(EC.element_to_be_clickable((By.CSS_SELECTOR, f"#{item_id} .ct-delete")))
        btn.click()
        ok_btn = w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok")))
        ok_btn.click()
        w.until(EC.invisibility_of_element_located((By.ID, item_id)))

    def test_46_delete_category(self, driver, w, ctx):
        driver.get(_url("/budget/categories-tags/"))
        self._delete_ct_item(driver, w, f"category-{ctx['category_uid']}")

    def test_47_delete_tag(self, driver, w, ctx):
        self._delete_ct_item(driver, w, f"tag-{ctx['tag_uid']}")

    def test_48_delete_account(self, driver, w, ctx):
        driver.get(_url("/account/delete/"))
        fill(w, By.ID, "id_password", PASSWORD)
        click(w, By.CSS_SELECTOR, "button[type=submit]")
        w.until(lambda d: "/budget/" not in d.current_url)
