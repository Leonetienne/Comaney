"""
AI wording visible to users is provider-neutral:
- the landing page is static: it names AI vendors only in the FAQ answer on
  configurable AI services and claims nothing about where data goes
- the profile AI card tip names the active provider (when it has user
  fields), so "Anthropic" appears only with the claude provider

Provider-neutral: the active provider is asked from the stack.
Run with: pytest -v tests/e2e/test_landing_page_ai_wording.py | tee logfile.log
"""
import json
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, cleanup_user, run_cmd, setup_user


def _provider() -> dict:
    out = run_cmd(
        "shell", "-c",
        "import json; from ai_providers import get_provider; p = get_provider(); "
        "print(json.dumps(dict(name=p.get_name(), display=p.get_display_name(), user_fields=bool(p.get_user_fields())) if p else {}))",
    )
    return json.loads(out.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def provider():
    p = _provider()
    assert p, "These tests need an active AI provider"
    return p


class TestLandingPage:

    def test_names_no_vendor_and_no_data_location_claim(self, driver):
        driver.delete_all_cookies()
        driver.get(_url("/"))
        time.sleep(1)
        # textContent: FAQ answers sit in collapsed <details>
        text = " ".join(driver.execute_script("return document.body.textContent").split())
        lower = text.lower()
        without_providers_faq = " ".join(driver.execute_script(
            "const body = document.body.cloneNode(true);"
            "body.querySelectorAll('.lp-faq-item').forEach(d => {"
            "  if (d.querySelector('summary').textContent.includes('What AI services')) d.remove();"
            "});"
            "return body.textContent;"
        ).split()).lower()
        assert without_providers_faq != lower, "AI services FAQ item missing"
        for word in ("anthropic", "claude", "sonnet", "deepseek"):
            assert word not in without_providers_faq, word
        assert "never leaves" not in lower
        assert "processed by the AI model this instance uses" in text


class TestProfileTip:

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w)
        yield c
        cleanup_user(c["email"])

    def test_tip_names_active_provider(self, driver, ctx, provider):
        driver.get(_url("/profile/#section-ai"))
        time.sleep(1)
        tip = driver.find_element(By.CSS_SELECTOR, "#section-ai .in-page-tip").text
        if provider["user_fields"]:
            assert f"Use your own {provider['display']} settings" in tip
        else:
            assert tip == "Define custom instructions for how expenses are classified."
        assert ("anthropic" in tip.lower()) == (provider["name"] == "claude")
