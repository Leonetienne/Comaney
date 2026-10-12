"""
AI Express image input follows the active provider's supports_vision():
- vision: upload zone shown, photo wording in the tip, pasting an image
  previews it, a POST with an image goes through
- no vision: upload zone and paste handling absent, no photo wording, a
  direct POST with an image gets "The configured AI cannot read images."
  and makes no AI call (trial spend unchanged)

Each test asserts the branch of the provider the stack runs, asked via run_cmd.
Run with: pytest -v tests/e2e/express/test_express_vision_flag.py | tee logfile.log
"""
import base64
import io
import re
import time

import pytest
import requests
from PIL import Image
from selenium.webdriver.common.by import By

from helpers import (
    BASE_URL, _url, cleanup_user, get_ai_user_config, run_cmd, session_cookies,
    set_ai_user_config, setup_user,
)

EXPRESS = "/budget/ai/express-creation/"
ERROR = "The configured AI cannot read images."
AI_TIMEOUT = 120

# a 4x4 red PNG, small enough for a cheap AI call
_PNG = io.BytesIO()
Image.new("RGB", (4, 4), (220, 30, 30)).save(_PNG, "PNG")
PNG_BYTES = _PNG.getvalue()


@pytest.fixture(scope="module")
def vision() -> bool:
    out = run_cmd("shell", "-c", "from ai_providers import get_provider; print(get_provider().supports_vision())")
    return out.strip().splitlines()[-1] == "True"


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


def _session(driver):
    s = requests.Session()
    s.cookies.update(session_cookies(driver))
    return s


def _post_with_image(s):
    page = s.get(_url(EXPRESS), timeout=10).text
    csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page).group(1)
    return s.post(
        _url(EXPRESS),
        data={"csrfmiddlewaretoken": csrf, "action": "parse", "description": "Coffee 3 EUR"},
        files={"image_file": ("receipt.png", PNG_BYTES, "image/png")},
        headers={"Referer": BASE_URL + EXPRESS}, timeout=AI_TIMEOUT,
    )


def _spent(email) -> str:
    out = run_cmd(
        "shell", "-c",
        f"from feusers.models import FeUser; print(FeUser.objects.get(email={email!r}).ai_trial_budget_spent)",
    )
    return out.strip().splitlines()[-1]


class TestVisionFlag:

    def test_upload_zone_and_tip(self, driver, w, ctx, vision):
        driver.get(_url(EXPRESS))
        time.sleep(1)
        tip = driver.find_element(By.CSS_SELECTOR, ".add-buddy-panel .page-tip").text
        zones = driver.find_elements(By.ID, "image-zone")
        if vision:
            assert zones and zones[0].is_displayed()
            assert "photo" in tip
        else:
            assert not zones
            assert "photo" not in tip and "image" not in tip.lower()

    def test_paste_image(self, driver, w, ctx, vision):
        driver.get(_url(EXPRESS))
        time.sleep(1)
        driver.execute_script(
            "const bytes = Uint8Array.from(atob(arguments[0]), c => c.charCodeAt(0));"
            "const dt = new DataTransfer();"
            "dt.items.add(new File([bytes], 'paste.png', {type: 'image/png'}));"
            "document.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt}));",
            base64.b64encode(PNG_BYTES).decode(),
        )
        time.sleep(1)
        previews = driver.find_elements(By.ID, "preview-img")
        try:
            if vision:
                assert previews and previews[0].is_displayed()
                assert previews[0].get_attribute("src").startswith("data:image/")
            else:
                assert not previews
        finally:
            driver.execute_script("try { sessionStorage.removeItem('express_creation_img'); } catch (_) {}")

    def test_direct_post_with_image(self, driver, w, ctx, vision):
        if vision:
            r = _post_with_image(_session(driver))
            assert r.status_code == 200
            assert ERROR not in r.text
            return
        # shared access, so a call would show up in the trial spend
        original = get_ai_user_config(ctx["email"])
        set_ai_user_config(ctx["email"], {})
        try:
            before = _spent(ctx["email"])
            r = _post_with_image(_session(driver))
            assert r.status_code == 200
            assert ERROR in r.text
            assert _spent(ctx["email"]) == before
        finally:
            set_ai_user_config(ctx["email"], original)
