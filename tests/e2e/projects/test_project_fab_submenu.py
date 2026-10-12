"""Project detail floating action button opens a submenu of small circular
bubbles ("Manual" / "AI"); "Manual" preserves the existing ?project=&back=
flow, and "AI" deep-links to Express Creation with the smart-input textarea
pre-filled with a prompt naming the project and a trailing space, with the
cursor placed after it so the user can type right away. The project's AI
preprompt is deliberately NOT part of that text: it reaches the AI through the
catalog instead (see test_express_project_preprompt.py).

The bubbles are hidden via opacity/pointer-events (not display:none) so the
open/close animation can transition, and looked up by their stable `title`
attribute rather than visible text -- Selenium treats zero-opacity elements
as "not displayed" and returns an empty `.text` for them, so a text-based
lookup silently fails while the menu is closed.
"""
import time
import urllib.parse

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import _create_group, _shell

PREPROMPT = "Put Robert and Mallory always at 0%, they're invited."


def _set_disable_ai_ui(email: str, value: bool) -> None:
    _shell(
        "from feusers.models import FeUser; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"u.disable_ai_ui = {value}; "
        "u.save(update_fields=['disable_ai_ui'])"
    )


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w, first_name="Frida", last_name="Fabber")
    group_id = int(_create_group(c["email"], "Fab Menu Project"))
    yield {**c, "group_id": group_id}
    cleanup_user(c["email"])


class TestProjectFabSubmenu:

    def _open(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)

    def _item_by_title(self, driver, title):
        els = driver.find_elements(By.CSS_SELECTOR, f'.fab-menu-item[title="{title}"]')
        return els[0] if els else None

    @pytest.mark.parametrize("path", ["", "insights/", "settings/"])
    def test_fab_present_on_every_project_tab(self, driver, w, ctx, path):
        driver.get(_url(f"/projects/{ctx['group_id']}/{path}"))
        time.sleep(1)
        assert driver.find_elements(By.CSS_SELECTOR, ".fab-wrap .fab-toggle"), \
            f"New expense FAB must be present on /projects/<id>/{path}"

    def test_create_manually_link_preserves_project_and_back(self, driver, w, ctx):
        self._open(driver, w, ctx)
        manual = self._item_by_title(driver, "Create manually")
        assert manual is not None
        href = manual.get_attribute("href")
        assert f"project={ctx['group_id']}" in href
        assert f"/projects/{ctx['group_id']}/" in urllib.parse.unquote(href)

    def test_ai_express_link_prefills_project_name(self, driver, w, ctx):
        self._open(driver, w, ctx)
        ai_link = self._item_by_title(driver, "AI Express")
        if ai_link is None:
            pytest.skip("AI Express not available for this test user (no trial key configured)")
        href = ai_link.get_attribute("href")
        assert "/budget/ai/express-creation/" in href
        prefill = urllib.parse.unquote(href.split("prefill=", 1)[1])
        assert prefill == "Create all expenses for project 'Fab Menu Project'"

    def test_clicking_ai_express_opens_prefilled_textarea(self, driver, w, ctx):
        self._open(driver, w, ctx)
        if self._item_by_title(driver, "AI Express") is None:
            pytest.skip("AI Express not available for this test user (no trial key configured)")
        driver.find_element(By.CSS_SELECTOR, ".fab-toggle").click()
        time.sleep(0.3)
        self._item_by_title(driver, "AI Express").click()
        time.sleep(1)
        textarea = driver.find_element(By.CSS_SELECTOR, ".smart-input")
        assert textarea.get_attribute("value") == "Create all expenses for project 'Fab Menu Project' "

    def test_cursor_placed_after_preset_prompt(self, driver, w, ctx):
        """Continues on the AI Express page opened by the previous test."""
        if "/budget/ai/express-creation/" not in driver.current_url:
            pytest.skip("AI Express not available for this test user (no trial key configured)")
        # A brand-new test user sees the one-time welcome modal; dismissing it
        # must hand focus back to the textarea.
        dismiss = driver.find_elements(By.ID, "intro-modal-dismiss")
        if dismiss and dismiss[0].is_displayed():
            dismiss[0].click()
            time.sleep(0.5)
        textarea = driver.find_element(By.CSS_SELECTOR, ".smart-input")
        state = driver.execute_script(
            "var t = arguments[0];"
            "return [document.activeElement === t, t.selectionStart, t.selectionEnd, t.value.length];",
            textarea,
        )
        focused, start, end, length = state
        assert focused, "The prefilled textarea must have focus"
        assert start == end == length, "The cursor must sit after the preset prompt"

    def test_preprompt_saved_from_settings(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['group_id']}/settings/"))
        time.sleep(1)
        textarea = driver.find_element(By.ID, "project-ai-preprompt")
        driver.execute_script("arguments[0].value = arguments[1];", textarea, PREPROMPT)
        driver.find_element(By.ID, "btn-rename-project").click()
        time.sleep(1)
        assert driver.find_element(By.ID, "project-ai-preprompt").get_attribute("value") == PREPROMPT

    def test_preprompt_not_in_ai_express_prefill(self, driver, w, ctx):
        self._open(driver, w, ctx)
        ai_link = self._item_by_title(driver, "AI Express")
        if ai_link is None:
            pytest.skip("AI Express not available for this test user (no trial key configured)")
        prefill = urllib.parse.unquote(ai_link.get_attribute("href").split("prefill=", 1)[1])
        assert prefill == "Create all expenses for project 'Fab Menu Project'"

    def test_preprompt_hidden_when_ai_ui_disabled(self, driver, w, ctx):
        _set_disable_ai_ui(ctx["email"], True)
        try:
            driver.get(_url(f"/projects/{ctx['group_id']}/settings/"))
            time.sleep(1)
            assert not driver.find_elements(By.ID, "project-ai-preprompt"), \
                "AI preprompt field must be hidden when 'Hide all AI features' is on"
            assert "AI preprompt" not in driver.page_source
        finally:
            _set_disable_ai_ui(ctx["email"], False)

    def test_rename_without_preprompt_field_keeps_preprompt(self, driver, w, ctx):
        """Saving the rename form while the preprompt field is hidden must not wipe it."""
        _set_disable_ai_ui(ctx["email"], True)
        try:
            driver.get(_url(f"/projects/{ctx['group_id']}/settings/"))
            time.sleep(1)
            driver.find_element(By.ID, "btn-rename-project").click()
            time.sleep(1)
        finally:
            _set_disable_ai_ui(ctx["email"], False)
        driver.get(_url(f"/projects/{ctx['group_id']}/settings/"))
        time.sleep(1)
        assert driver.find_element(By.ID, "project-ai-preprompt").get_attribute("value") == PREPROMPT
