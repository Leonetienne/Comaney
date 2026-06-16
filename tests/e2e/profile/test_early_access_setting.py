"""
Early access settings toggle (FeUser.enable_early_access, default False).

Covers:
  - Sankey Studio's sidebar link and direct-URL access are gated on it
  - the profile "Early access" checkbox turns it on/off
  - demo users cannot change it (server + UI)
"""
import time
import uuid

import pytest
import requests
from selenium.webdriver.common.by import By

from helpers import (
    _url, fill, click, run_cmd, session_cookies,
    setup_user, cleanup_user, DOCKER_WEB,
)

SANKEY_URL          = _url("/budget/sankey/")
SANKEY_SAVE_URL     = _url("/budget/sankey/save/")
SANKEY_GENERATE_URL = _url("/budget/sankey/generate/")
DASHBOARD_URL       = _url("/budget/")

DEMO_PASSWORD = "D3m0Ea1yAcc3ss!"


def _submit_form(driver, action_value):
    """Submit the profile form whose hidden action input has the given value."""
    driver.execute_script(
        f"document.querySelector(\"input[name='action'][value='{action_value}']\").closest('form').submit()"
    )


def _set_early_access(email: str, value: bool) -> None:
    run_cmd(
        "shell", "-c",
        f"from feusers.models import FeUser; u = FeUser.objects.get(email='{email}'); "
        f"u.enable_early_access = {value}; "
        f"u.save(update_fields=['enable_early_access'])",
    )


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


@pytest.fixture(scope="module")
def sess(driver, ctx):
    driver.get(DASHBOARD_URL)
    s = requests.Session()
    s.cookies.update(session_cookies(driver))
    return s


class TestDisabledByDefault:

    def test_sidebar_link_absent(self, driver, w, ctx):
        driver.get(DASHBOARD_URL)
        time.sleep(1)
        links = driver.find_elements(By.LINK_TEXT, "Sankey Studio")
        assert not links, "Sankey Studio must be hidden until early access is enabled"

    def test_direct_hit_redirects_to_dashboard(self, driver, w, ctx):
        driver.get(SANKEY_URL)
        time.sleep(1)
        assert "/budget/dash/" in driver.current_url, \
            f"Expected redirect to the dashboard, got {driver.current_url}"

    def test_save_api_returns_404(self, ctx, sess):
        csrf = sess.cookies.get("csrftoken", "")
        r = sess.post(SANKEY_SAVE_URL, json={"nodes": {}, "edges": []},
                      headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
                      timeout=10)
        assert r.status_code == 404

    def test_generate_api_returns_404(self, ctx, sess):
        csrf = sess.cookies.get("csrftoken", "")
        r = sess.post(SANKEY_GENERATE_URL, json={"date_from": "2026-01-01", "date_to": "2026-01-31", "sharing": ""},
                      headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
                      timeout=10)
        assert r.status_code == 404


class TestToggleViaProfileForm:

    def test_enabling_shows_sidebar_link(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        checkbox = driver.find_element(By.ID, "id_enable_early_access")
        if not checkbox.is_selected():
            checkbox.click()
            time.sleep(0.2)
        _submit_form(driver, "early_access")
        time.sleep(2)
        assert "Saved." in driver.page_source

        driver.get(DASHBOARD_URL)
        time.sleep(1)
        link = driver.find_element(By.LINK_TEXT, "Sankey Studio")
        assert link.get_attribute("href").endswith("/budget/sankey/")

    def test_enabled_direct_hit_loads_page(self, driver, w, ctx):
        driver.get(SANKEY_URL)
        time.sleep(1)
        assert "/budget/sankey/" in driver.current_url
        assert "Sankey Studio" in driver.page_source

    def test_disabling_hides_sidebar_link_again(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        checkbox = driver.find_element(By.ID, "id_enable_early_access")
        if checkbox.is_selected():
            checkbox.click()
            time.sleep(0.2)
        _submit_form(driver, "early_access")
        time.sleep(2)
        assert "Saved." in driver.page_source

        driver.get(DASHBOARD_URL)
        time.sleep(1)
        links = driver.find_elements(By.LINK_TEXT, "Sankey Studio")
        assert not links

        driver.get(SANKEY_URL)
        time.sleep(1)
        assert "/budget/dash/" in driver.current_url


# ---------------------------------------------------------------------------
# Demo users cannot toggle this setting (see CLAUDE.md "Demo users" rules:
# it would let one visitor permanently alter what the next visitor sees).
# ---------------------------------------------------------------------------

def _demo_users_enabled() -> bool:
    return run_cmd("shell", "-c", "from django.conf import settings; print(settings.ENABLE_DEMO_USERS)").strip() == "True"


def _create_demo_user(email: str) -> None:
    import subprocess
    r = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py",
         "create_user", email, "-p", DEMO_PASSWORD, "--demo",
         "--first-name", "Dean", "--last-name", "Demo"],
        capture_output=True, text=True, timeout=15,
    )
    assert r.returncode == 0, f"create_user --demo failed:\n{r.stderr}"


def _http_session_for_demo(email: str, password: str) -> requests.Session:
    import re
    s = requests.Session()
    r = s.get(_url("/login/"), timeout=10)
    m = re.search(r'csrfmiddlewaretoken.*?value="([^"]+)"', r.text)
    s.post(_url("/login/"), data={
        "csrfmiddlewaretoken": m.group(1),
        "email": email,
        "password": password,
    }, allow_redirects=True, timeout=10)
    r = s.get(_url("/demo-banner/"), timeout=10)
    if "btn-demo-accept" in r.text or "Okay, I understand" in r.text:
        m2 = re.search(r'csrfmiddlewaretoken.*?value="([^"]+)"', r.text)
        s.post(_url("/demo-banner/"), data={
            "csrfmiddlewaretoken": m2.group(1),
            "action": "accept",
        }, allow_redirects=True, timeout=10)
    return s


@pytest.fixture(scope="module")
def demo_ctx():
    if not _demo_users_enabled():
        pytest.skip("ENABLE_DEMO_USERS is not set on this server")
    email = f"earlyaccess.{uuid.uuid4().hex[:8]}@example.com"
    _create_demo_user(email)
    yield {"email": email, "password": DEMO_PASSWORD}
    cleanup_user(email)


class TestDemoUserCannotToggle:

    def test_server_blocks_early_access_action(self, demo_ctx):
        s = _http_session_for_demo(demo_ctx["email"], demo_ctx["password"])
        r = s.get(_url("/profile/"), timeout=10)
        import re
        m = re.search(r'csrfmiddlewaretoken.*?value="([^"]+)"', r.text)
        s.post(_url("/profile/"), data={
            "csrfmiddlewaretoken": m.group(1),
            "action": "early_access",
            "enable_early_access": "on",
        }, allow_redirects=True, timeout=10)
        value = run_cmd(
            "shell", "-c",
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{demo_ctx['email']}').enable_early_access)",
        ).strip()
        assert value == "False", "Demo user's early access setting was changed despite restriction"

    def test_ui_early_access_section_is_disabled(self, driver, w, demo_ctx):
        driver.delete_all_cookies()
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", demo_ctx["email"])
        fill(w, By.ID, "id_password", demo_ctx["password"])
        click(w, By.CSS_SELECTOR, "button[type=submit]")
        time.sleep(2)
        if "/demo-banner/" in driver.current_url:
            click(w, By.ID, "btn-demo-accept")
            time.sleep(2)
        driver.get(_url("/profile/"))
        time.sleep(1)
        fs = driver.find_elements(By.XPATH, "//div[@id='section-early-access']//fieldset[@disabled]")
        assert fs, "Early access section does not have a disabled fieldset for demo user"
