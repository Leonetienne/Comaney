"""
Agent keys (MCP) card on the profile page: create a key whose secret shows once,
restrict it per data area with Read/Write checkboxes (write includes read),
revoke it, and no agent keys for demo accounts.
Run with: pytest -v tests/e2e/profile/test_agent_keys.py | tee logfile.log
"""
import time

import pytest
import requests
from selenium.webdriver.common.by import By

from bhelpers import _confirm, _shell
from helpers import BASE_URL, _url, cleanup_user, form_login, form_post, http_session, setup_user


def _ping(key):
    return requests.post(
        f"{BASE_URL}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Authorization": f"Bearer {key}"}, timeout=10,
    ).status_code


def _card(driver):
    driver.get(_url("/profile/"))
    time.sleep(1)
    return driver.find_element(By.ID, "section-agent-keys")


def _stored_permissions(email, label):
    return _shell(
        "import json; from mcp_server.models import AgentKey; "
        f"print(json.dumps(AgentKey.objects.get(feuser__email='{email}', label='{label}').effective_permissions(), sort_keys=True))"
    )


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestAgentKeys:

    def test_create_shows_the_secret_once(self, driver, w, ctx):
        card = _card(driver)
        assert card.find_element(By.ID, "mcp-url-display").get_attribute("value").endswith("/mcp")
        name = card.find_element(By.CSS_SELECTOR, ".agent-key-create input[name=label]")
        driver.execute_script("arguments[0].value = 'Laptop';", name)
        card.find_element(By.XPATH, ".//button[normalize-space()='Create agent key']").click()
        time.sleep(2)
        secret = driver.find_element(By.ID, "agent-key-secret").get_attribute("value")
        assert secret.startswith("cmy_")
        assert _ping(secret) == 200
        ctx["secret"] = secret
        assert "Laptop" in _card(driver).text
        assert not driver.find_elements(By.ID, "agent-key-secret")

    def test_restrict_with_write_including_read(self, driver, w, ctx):
        card = _card(driver)
        row = card.find_element(By.CSS_SELECTOR, ".agent-key-row")
        row.find_element(By.CSS_SELECTOR, ".agent-key-restrict-toggle").click()
        time.sleep(0.3)
        for box in row.find_elements(By.CSS_SELECTOR, ".agent-key-permissions input[type=checkbox]"):
            if box.is_selected():
                driver.execute_script("arguments[0].click();", box)
        driver.execute_script("arguments[0].click();", row.find_element(By.NAME, "write_projects"))
        assert row.find_element(By.NAME, "read_projects").is_selected()
        row.find_element(By.XPATH, ".//button[normalize-space()='Save permissions']").click()
        time.sleep(2)
        stored = _stored_permissions(ctx["email"], "Laptop")
        assert '"projects": {"read": true, "write": true}' in stored
        assert '"expenses": {"read": false, "write": false}' in stored
        assert "Restricted" in _card(driver).find_element(By.CSS_SELECTOR, ".agent-key-row").text

    def test_revoke(self, driver, w, ctx):
        card = _card(driver)
        card.find_element(By.XPATH, ".//button[normalize-space()='Revoke']").click()
        _confirm(driver)
        time.sleep(1)
        assert "Laptop" not in _card(driver).text
        assert _ping(ctx["secret"]) == 401


class TestDemoAccounts:

    def test_no_agent_keys_for_demo_users(self, driver, w, ctx):
        _shell(f"from feusers.models import FeUser; FeUser.objects.filter(email='{ctx['email']}').update(is_demo=True)")
        try:
            session = http_session()
            form_login(session, ctx["email"], ctx["password"])
            form_post(session, "/agent-keys/", {"label": "Sneaky"}, csrf_path="/profile/")
            count = _shell(f"from mcp_server.models import AgentKey; print(AgentKey.objects.filter(feuser__email='{ctx['email']}').count())")
            assert count == "0"
            button = _card(driver).find_element(By.XPATH, ".//button[normalize-space()='Create agent key']")
            assert button.get_attribute("disabled")
        finally:
            _shell(f"from feusers.models import FeUser; FeUser.objects.filter(email='{ctx['email']}').update(is_demo=False)")
