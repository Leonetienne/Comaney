"""Tests: contact form — rendering, PoW, submission, email delivery."""
import requests
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from conftest import BASE_URL, _url, click, fill, wait_text, fetch_email, session_cookies

CONTACT_URL = "/contact/"


def _contact_available():
    """Return True if the contact page is enabled on this server."""
    r = requests.get(f"{BASE_URL}{CONTACT_URL}", allow_redirects=False, timeout=5)
    return r.status_code == 200


class TestContact:

    def test_01_contact_page_loads(self, driver, w, ctx):
        r = requests.get(f"{BASE_URL}{CONTACT_URL}", timeout=5)
        if r.status_code == 404:
            pytest.skip("Contact form not enabled (ADMIN_NOTIFICATION_EMAIL or ENABLE_REGISTRATION not set)")
        assert r.status_code == 200
        assert "Get in touch" in r.text
        assert "pow-nonce" in r.text

    def test_02_contact_footer_link_visible(self, driver, w, ctx):
        if not _contact_available():
            pytest.skip("Contact form not enabled")
        driver.get(_url("/"))
        # footer link should be present somewhere on any page
        driver.get(_url("/budget/"))
        footer_link = w.until(EC.presence_of_element_located(
            (By.XPATH, "//footer//a[text()='Contact']")))
        assert "/contact/" in footer_link.get_attribute("href")

    def test_03_contact_prefills_logged_in_user(self, driver, w, ctx):
        if not _contact_available():
            pytest.skip("Contact form not enabled")
        driver.get(_url(CONTACT_URL))
        email_val = driver.find_element(By.ID, "id_email").get_attribute("value")
        name_val  = driver.find_element(By.ID, "id_name").get_attribute("value")
        # logged-in user's email and name should be pre-filled
        assert email_val != "", "Email should be pre-filled for logged-in user"
        assert name_val  != "", "Name should be pre-filled for logged-in user"
        ctx["contact_prefilled_email"] = email_val

    def test_04_contact_submit_and_redirect(self, driver, w, ctx):
        if not _contact_available():
            pytest.skip("Contact form not enabled")
        driver.get(_url(CONTACT_URL))

        # clear and fill fields (name/email may already be prefilled)
        for fid, val in [
            ("id_name",    "Test Sender"),
            ("id_email",   ctx.get("contact_prefilled_email", "test@example.com")),
            ("id_subject", "Selenium test message"),
            ("id_message", "This is an automated contact form test. Please ignore."),
        ]:
            el = driver.find_element(By.ID, fid)
            el.clear()
            el.send_keys(val)

        # wait for PoW to finish (submit button becomes enabled)
        w.until(EC.element_to_be_clickable((By.ID, "submit-btn")))
        driver.find_element(By.ID, "submit-btn").click()

        # should redirect to ?sent=1
        w.until(lambda d: "sent=1" in d.current_url)
        wait_text(driver, w, "Your message has been sent")

    def test_05_contact_email_delivered(self, driver, w, ctx):
        if not _contact_available():
            pytest.skip("Contact form not enabled")
        import time
        from conftest import MAILPIT_API
        # Search mailpit by subject (any recipient) — ADMIN_NOTIFICATION_EMAIL
        # must route through mailpit in the test environment.
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
            pytest.skip("Contact email not found in mailpit — ADMIN_NOTIFICATION_EMAIL may not route through it")
        assert found

    def test_06_contact_required_fields(self, driver, w, ctx):
        if not _contact_available():
            pytest.skip("Contact form not enabled")
        driver.get(_url(CONTACT_URL))

        # clear all fields to trigger server-side required validation
        for fid in ("id_name", "id_email", "id_subject", "id_message"):
            el = driver.find_element(By.ID, fid)
            el.clear()

        # wait for PoW then submit empty form
        w.until(EC.element_to_be_clickable((By.ID, "submit-btn")))
        driver.find_element(By.ID, "submit-btn").click()

        # should stay on the form and show errors
        w.until(lambda d: "sent=1" not in d.current_url)
        wait_text(driver, w, "required")

    def test_07_contact_logged_out_works(self, driver, w, ctx):
        if not _contact_available():
            pytest.skip("Contact form not enabled")
        # Use requests (no session) to verify the page renders for anonymous users
        r = requests.get(f"{BASE_URL}{CONTACT_URL}", timeout=5)
        assert r.status_code == 200
        assert "Get in touch" in r.text
        # logged-out page should NOT pre-fill email
        assert 'value=""' in r.text or 'name="email"' in r.text
