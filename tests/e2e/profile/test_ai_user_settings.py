"""
Own AI settings on the profile page (FeUser.ai_user_config), generated from
the active provider's user fields:
- each field's label comes from the provider; secret fields are masked
  ("********" + last 4) after saving
- re-saving the masked value keeps the stored secret; clearing removes it
- saving drops entries of other providers; purge_inactive_ai_config deletes
  them for every user and keeps the active provider's entry
- create_user --ai-config KEY=VALUE sets them (bad input rejected)
- demo users can neither see an editable form nor save via a direct POST
- a provider without user fields (e.g. local): no own-settings field, saving
  still drops other providers' entries, create_user refuses --ai-config

Provider-neutral: the expected labels and field keys are asked from the stack,
and each test asserts the branch of the active provider (secret api_key user
field, or no user fields at all).
Run with: pytest -v tests/e2e/profile/test_ai_user_settings.py | tee logfile.log
"""
import json
import re
import subprocess
import time
import uuid

import pytest
import requests
from selenium.webdriver.common.by import By

from helpers import (
    BASE_URL, DOCKER_WEB, PASSWORD, _url, cleanup_user, click, fill,
    get_ai_user_config, run_cmd, set_ai_user_config, setup_user,
)

KEY = "sk-e2e-own-settings-4321"


def _user_fields() -> list[dict]:
    out = run_cmd(
        "shell", "-c",
        "import json; from ai_providers import get_provider; p = get_provider(); "
        "print(json.dumps([dict(key=f.key, label=f.label, secret=f.secret) for f in (p.get_user_fields() if p else [])]))",
    )
    return json.loads(out.strip().splitlines()[-1])


def _raw_config(email: str) -> dict:
    out = run_cmd(
        "shell", "-c",
        f"import json; from feusers.models import FeUser; "
        f"print(json.dumps(FeUser.objects.get(email={email!r}).ai_user_config))",
    )
    return json.loads(out.strip().splitlines()[-1])


def _set_raw_config(email: str, config: dict) -> None:
    run_cmd(
        "shell", "-c",
        f"from feusers.models import FeUser; u = FeUser.objects.get(email={email!r}); "
        f"u.ai_user_config = {config!r}; u.save(update_fields=['ai_user_config'])",
    )


def _active_provider() -> str:
    out = run_cmd("shell", "-c", "from ai_providers import get_provider; print(get_provider().get_name())")
    return out.strip().splitlines()[-1]


def _submit_ai_form(driver):
    driver.execute_script(
        "document.querySelector(\"input[name='action'][value='ai']\").closest('form').submit()"
    )
    time.sleep(2)


@pytest.fixture(scope="module")
def fields():
    f = _user_fields()
    assert not f or any(x["key"] == "api_key" and x["secret"] for x in f), (
        "These tests cover providers with a secret api_key user field or with no user fields"
    )
    return f


@pytest.fixture(scope="module")
def takes_key(fields) -> bool:
    return bool(fields)


def _own_settings_inputs(driver) -> list:
    return [el for el in driver.find_elements(By.CSS_SELECTOR, "#section-ai [id^='id_ai_']")
            if el.get_attribute("id") != "id_ai_custom_instructions"]


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestProfileForm:

    def test_labels_come_from_provider(self, driver, w, ctx, fields):
        driver.get(_url("/profile/#section-ai"))
        time.sleep(1)
        if not fields:
            assert _own_settings_inputs(driver) == []
            assert driver.find_element(By.ID, "id_ai_custom_instructions").is_displayed()
            return
        for f in fields:
            label = driver.find_element(By.CSS_SELECTOR, f"label[for='id_ai_{f['key']}']")
            assert label.text.strip() == f["label"]
            el = driver.find_element(By.ID, f"id_ai_{f['key']}")
            if f["secret"]:
                assert el.get_attribute("type") == "password"

    def test_save_shows_masked_value(self, driver, w, ctx, takes_key):
        driver.get(_url("/profile/#section-ai"))
        time.sleep(1)
        if not takes_key:
            fill(w, By.ID, "id_ai_custom_instructions", "No-key provider save")
            _submit_ai_form(driver)
            assert "Saved." in driver.page_source
            assert _own_settings_inputs(driver) == []
            assert _raw_config(ctx["email"]) == {}
            return
        fill(w, By.ID, "id_ai_api_key", KEY)
        _submit_ai_form(driver)
        assert "Saved." in driver.page_source
        value = driver.find_element(By.ID, "id_ai_api_key").get_attribute("value")
        assert value == "********4321"
        assert KEY not in driver.page_source
        assert get_ai_user_config(ctx["email"]) == {"api_key": KEY}

    def test_resave_without_change_keeps_key(self, driver, w, ctx, takes_key):
        driver.get(_url("/profile/#section-ai"))
        time.sleep(1)
        fill(w, By.ID, "id_ai_custom_instructions", "Re-save test")
        _submit_ai_form(driver)
        assert "Saved." in driver.page_source
        assert get_ai_user_config(ctx["email"]) == ({"api_key": KEY} if takes_key else {})

    def test_saving_drops_other_providers_entries(self, driver, w, ctx, takes_key):
        _set_raw_config(ctx["email"], {**_raw_config(ctx["email"]), "retired": {"api_key": "sk-old"}})
        driver.get(_url("/profile/#section-ai"))
        time.sleep(1)
        _submit_ai_form(driver)
        assert "Saved." in driver.page_source
        expected = {_active_provider(): {"api_key": KEY}} if takes_key else {}
        assert _raw_config(ctx["email"]) == expected

    def test_clearing_removes_key(self, driver, w, ctx, takes_key):
        if not takes_key:
            # provider without user settings
            assert _raw_config(ctx["email"]) == {}
            return
        driver.get(_url("/profile/#section-ai"))
        time.sleep(1)
        fill(w, By.ID, "id_ai_api_key", "")
        _submit_ai_form(driver)
        assert "Saved." in driver.page_source
        assert driver.find_element(By.ID, "id_ai_api_key").get_attribute("value") == ""
        assert _raw_config(ctx["email"]) == {}


class TestPurgeCommand:

    def test_purge_removes_only_inactive_providers(self, ctx):
        active = _active_provider()
        _set_raw_config(ctx["email"], {active: {"api_key": KEY}, "retired": {"api_key": "sk-old"}})
        try:
            out = run_cmd("purge_inactive_ai_config")
            assert "Purged" in out
            assert _raw_config(ctx["email"]) == {active: {"api_key": KEY}}
            # idempotent
            run_cmd("purge_inactive_ai_config")
            assert _raw_config(ctx["email"]) == {active: {"api_key": KEY}}
        finally:
            set_ai_user_config(ctx["email"], {})


class TestCreateUserAiConfig:

    def _create(self, *args):
        email = f"sel.{uuid.uuid4().hex[:8]}@example.com"
        r = subprocess.run(
            ["docker", "exec", DOCKER_WEB, "python", "manage.py", "create_user", email, "-p", PASSWORD, *args],
            capture_output=True, text=True, timeout=15,
        )
        return email, r

    def test_sets_active_provider_entry(self, takes_key):
        email, r = self._create("--ai-config", "api_key=sk-a=b-cli1")
        try:
            if not takes_key:
                assert r.returncode != 0
                assert "Unknown AI setting" in r.stderr and "sk-a=b-cli1" not in r.stderr
                return
            assert r.returncode == 0, r.stderr
            assert _raw_config(email) == {_active_provider(): {"api_key": "sk-a=b-cli1"}}
        finally:
            cleanup_user(email)

    @pytest.mark.parametrize("arg", ["sk-no-key-name", "nonsense_field=1"])
    def test_rejects_bad_input_without_echoing_it(self, arg):
        email, r = self._create("--ai-config", arg)
        try:
            assert r.returncode != 0
            assert "sk-no-key-name" not in r.stderr
            exists = run_cmd(
                "shell", "-c",
                f"from feusers.models import FeUser; print(FeUser.objects.filter(email={email!r}).exists())",
            )
            assert exists.strip().endswith("False")
        finally:
            cleanup_user(email)


class TestDemoUser:

    @pytest.fixture(scope="class")
    def demo(self):
        enabled = run_cmd("shell", "-c", "from django.conf import settings; print(settings.ENABLE_DEMO_USERS)")
        if not enabled.strip().endswith("True"):
            pytest.skip("ENABLE_DEMO_USERS is not set on this stack")
        email = f"sel.demo.{uuid.uuid4().hex[:8]}@example.com"
        run_cmd("create_user", email, "-p", PASSWORD, "--demo", "--first-name", "Dean", "--last-name", "Demo")
        yield {"email": email, "password": PASSWORD}
        cleanup_user(email)

    def test_form_disabled_for_demo(self, driver, w, demo):
        driver.delete_all_cookies()
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", demo["email"])
        fill(w, By.ID, "id_password", demo["password"])
        click(w, By.CSS_SELECTOR, "button[type=submit]")
        time.sleep(2)
        if "/demo-banner/" in driver.current_url:
            click(w, By.ID, "btn-demo-accept")
            time.sleep(2)
        driver.get(_url("/profile/#section-ai"))
        time.sleep(1)
        card = driver.find_element(By.ID, "section-ai")
        assert "Not available on demo accounts." in card.text
        assert not driver.find_element(By.ID, "id_ai_custom_instructions").is_enabled()
        assert all(not el.is_enabled() for el in _own_settings_inputs(driver))

    def test_server_rejects_demo_post(self, driver, demo):
        s = requests.Session()
        s.cookies.update({c["name"]: c["value"] for c in driver.get_cookies()})
        page = s.get(_url("/profile/"), timeout=10).text
        csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page).group(1)
        r = s.post(_url("/profile/"), data={
            "csrfmiddlewaretoken": csrf, "action": "ai",
            "ai_api_key": "sk-demo-hacked-1111", "ai_custom_instructions": "",
        }, headers={"Referer": BASE_URL + "/profile/"}, timeout=10)
        # the view processed the POST and refused it
        assert r.status_code == 200 and "success=ai" in r.url, (r.status_code, r.url)
        assert _raw_config(demo["email"]) == {}
