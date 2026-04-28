"""Registration, email confirmation, and login."""
import uuid
import requests
import pytest
from selenium.webdriver.common.by import By

from conftest import _url, fill, click, submit, fetch_email, extract_link, wait_url, wait_text, PASSWORD, MAILPIT_API


class TestAuth:

    def test_01_register(self, driver, w, ctx):
        ctx["email"] = f"selenium.{uuid.uuid4().hex[:8]}@example.com"
        try:
            requests.delete(f"{MAILPIT_API}/messages", timeout=5)
        except Exception:
            pass

        driver.get(_url("/register/"))
        fill(w, By.ID, "id_first_name", "Selenium")
        fill(w, By.ID, "id_last_name", "Tester")
        fill(w, By.ID, "id_email", ctx["email"])
        fill(w, By.ID, "id_password", PASSWORD)
        fill(w, By.ID, "id_password_confirm", PASSWORD)

        w.until(lambda d: not d.find_element(By.ID, "submit-btn").get_attribute("disabled"))
        driver.find_element(By.ID, "submit-btn").click()
        wait_url(w, "/register/success/")

    def test_02_confirm_email(self, driver, w, ctx):
        body = fetch_email(ctx["email"], "confirm")
        driver.get(extract_link(body))
        wait_text(driver, w, "confirmed")

    def test_03_login(self, driver, w, ctx):
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", ctx["email"])
        fill(w, By.ID, "id_password", PASSWORD)
        click(w, By.CSS_SELECTOR, "button[type=submit]")
        wait_url(w, "/budget/")
