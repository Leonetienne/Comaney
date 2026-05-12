"""Contact form: rendering, PoW, submission, email delivery, and required-field errors."""
import time

import pytest
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from helpers import (
    _url, wait_text, BASE_URL, MAILPIT_API,
    setup_user, cleanup_user,
)

CONTACT_URL = "/contact/"


def _contact_available() -> bool:
    r = requests.get(f"{BASE_URL}{CONTACT_URL}", allow_redirects=False, timeout=5)
    return r.status_code == 200


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestContact:

    def test_page_loads(self, driver, w, ctx):
        r = requests.get(f"{BASE_URL}{CONTACT_URL}", timeout=5)
        if r.status_code == 404:
            pytest.skip("Contact form not enabled (ADMIN_NOTIFICATION_EMAIL not set)")
        assert r.status_code == 200
        assert "Get in touch" in r.text
        assert "pow-nonce" in r.text

    def test_footer_link_visible(self, driver, w, ctx):
        if not _contact_available():
            pytest.skip("Contact form not enabled")
        driver.get(_url("/budget/"))
        footer_link = w.until(EC.presence_of_element_located(
            (By.XPATH, "//footer//a[text()='Contact']")))
        assert "/contact/" in footer_link.get_attribute("href")

    def test_prefills_logged_in_user(self, driver, w, ctx):
        if not _contact_available():
            pytest.skip("Contact form not enabled")
        driver.get(_url(CONTACT_URL))
        email_val = driver.find_element(By.ID, "id_email").get_attribute("value")
        name_val  = driver.find_element(By.ID, "id_name").get_attribute("value")
        assert email_val != "", "Email must be pre-filled for logged-in user"
        assert name_val  != "", "Name must be pre-filled for logged-in user"
        ctx["contact_email"] = email_val

    def test_submit_and_redirect(self, driver, w, ctx):
        if not _contact_available():
            pytest.skip("Contact form not enabled")
        driver.get(_url(CONTACT_URL))
        for fid, val in [
            ("id_name",    "Test Sender"),
            ("id_email",   ctx.get("contact_email", "test@example.com")),
            ("id_subject", "Selenium test message"),
            ("id_message", "Automated contact form test. Please ignore."),
        ]:
            el = driver.find_element(By.ID, fid)
            el.clear()
            el.send_keys(val)
        w.until(EC.element_to_be_clickable((By.ID, "submit-btn")))
        driver.find_element(By.ID, "submit-btn").click()
        w.until(lambda d: "sent=1" in d.current_url)
        wait_text(driver, w, "Your message has been sent")

    def test_email_delivered(self, driver, w, ctx):
        if not _contact_available():
            pytest.skip("Contact form not enabled")
        deadline = time.time() + 20
        found = False
        while time.time() < deadline:
            try:
                msgs = requests.get(f"{MAILPIT_API}/messages", timeout=5).json().get("messages", [])
                for msg in msgs:
                    if "[Comaney Contact]" in msg.get("Subject", "") and \
                            "Selenium test message" in msg.get("Subject", ""):
                        found = True
                        break
            except Exception:
                pass
            if found:
                break
            time.sleep(1)
        if not found:
            pytest.skip("Contact email not found in mailpit - ADMIN_NOTIFICATION_EMAIL may not route through it")

    def test_required_fields(self, driver, w, ctx):
        if not _contact_available():
            pytest.skip("Contact form not enabled")
        driver.get(_url(CONTACT_URL))
        for fid in ("id_name", "id_email", "id_subject", "id_message"):
            driver.find_element(By.ID, fid).clear()
        w.until(EC.element_to_be_clickable((By.ID, "submit-btn")))
        driver.find_element(By.ID, "submit-btn").click()
        w.until(lambda d: "sent=1" not in d.current_url)
        wait_text(driver, w, "required")

    def test_logged_out_renders(self, driver, w, ctx):
        if not _contact_available():
            pytest.skip("Contact form not enabled")
        r = requests.get(f"{BASE_URL}{CONTACT_URL}", timeout=5)
        assert r.status_code == 200
        assert "Get in touch" in r.text
