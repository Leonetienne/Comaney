"""
API key permissions: the REST API key is limited per data area with Read/Write
(same concerns as agent keys), refusals are 403 and change nothing, the browser
session keeps full access, and revoking the key and generating a new one keeps its permissions.
Run with: pytest -v tests/e2e/api/test_api_key_permissions.py | tee logfile.log
"""
import json
import time

import pytest
import requests
from selenium.webdriver.common.by import By

from bhelpers import _shell
from helpers import BASE_URL, _url, api_get, api_post, cleanup_user, session_cookies, setup_user


def _set_permissions(email, perms):
    _shell(
        "from feusers.models import FeUser; "
        f"FeUser.objects.filter(email='{email}').update(api_key_permissions={perms!r})"
    )


def _stored_permissions(email):
    return json.loads(_shell(
        "import json; from feusers.models import FeUser; "
        f"print(json.dumps(FeUser.objects.get(email='{email}').api_key_access.perms))"
    ))


def _card(driver):
    driver.get(_url("/profile/"))
    time.sleep(1)
    return driver.find_element(By.ID, "section-apikey")


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    _set_permissions(c["email"], {"expenses": {"read": True, "write": False}})
    yield c
    cleanup_user(c["email"])


class TestEnforcement:

    def test_allowed_read_works(self, ctx):
        assert api_get("/api/v2/expenses/", ctx).status_code == 200

    def test_other_area_is_refused(self, ctx):
        r = api_get("/api/v2/projects/", ctx)
        assert r.status_code == 403
        assert "Projects read" in r.json()["error"]

    def test_refused_write_changes_nothing(self, ctx):
        before = len(api_get("/api/v2/expenses/", ctx).json()["expenses"])
        r = api_post("/api/v2/expenses/", ctx, {"title": "No", "type": "expense", "value": 1})
        assert r.status_code == 403
        assert "Expenses write" in r.json()["error"]
        assert len(api_get("/api/v2/expenses/", ctx).json()["expenses"]) == before

    def test_browser_session_keeps_full_access(self, driver, ctx):
        r = requests.get(f"{BASE_URL}/api/v2/projects/", cookies=session_cookies(driver), timeout=10)
        assert r.status_code == 200


class TestRestrictPanel:

    def test_save_permissions(self, driver, ctx):
        card = _card(driver)
        card.find_element(By.CSS_SELECTOR, ".key-restrict-toggle").click()
        time.sleep(0.3)
        for box in card.find_elements(By.CSS_SELECTOR, ".key-permissions input[type=checkbox]"):
            if box.is_selected():
                driver.execute_script("arguments[0].click();", box)
        driver.execute_script("arguments[0].click();", card.find_element(By.NAME, "write_projects"))
        assert card.find_element(By.NAME, "read_projects").is_selected()
        card.find_element(By.XPATH, ".//button[normalize-space()='Save permissions']").click()
        time.sleep(2)
        stored = _stored_permissions(ctx["email"])
        assert stored["projects"] == {"read": True, "write": True}
        assert stored["expenses"] == {"read": False, "write": False}

    def test_new_key_after_revoke_keeps_permissions(self, driver, ctx):
        before = _stored_permissions(ctx["email"])
        _card(driver).find_element(By.XPATH, ".//button[normalize-space()='Revoke']").click()
        time.sleep(2)
        _card(driver).find_element(By.XPATH, ".//button[normalize-space()='Generate API key']").click()
        time.sleep(2)
        assert _stored_permissions(ctx["email"]) == before
