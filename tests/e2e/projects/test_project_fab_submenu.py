"""Project detail floating action button opens a submenu of small circular
bubbles ("Manual" / "AI"); "Manual" preserves the existing ?project=&back=
flow, and "AI" deep-links to Express Creation with the smart-input textarea
pre-filled with a prompt naming the project.

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
from bhelpers import _create_group


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
        assert textarea.get_attribute("value") == "Create all expenses for project 'Fab Menu Project'"
