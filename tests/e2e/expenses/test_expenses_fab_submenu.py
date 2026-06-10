"""Expense list floating action button opens a submenu with two small
circular bubbles ("Manual" / "AI") instead of navigating straight to the
manual expense form.

The bubbles are hidden via opacity/pointer-events (not display:none) so the
open/close animation can transition, and looked up by their stable `title`
attribute rather than visible text -- Selenium treats zero-opacity elements
as "not displayed" and returns an empty `.text` for them, so a text-based
lookup silently fails while the menu is closed.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestExpensesFabSubmenu:

    def _open(self, driver, w):
        driver.get(_url("/budget/expenses/"))
        time.sleep(1)

    def _menu_items(self, driver):
        return driver.find_elements(By.CSS_SELECTOR, ".fab-menu-item")

    def _item_by_title(self, driver, title):
        els = driver.find_elements(By.CSS_SELECTOR, f'.fab-menu-item[title="{title}"]')
        return els[0] if els else None

    def test_menu_items_hidden_by_default(self, driver, w, ctx):
        self._open(driver, w)
        items = self._menu_items(driver)
        assert items, "Expected at least the 'Create manually' bubble in the DOM"
        assert not any(i.is_displayed() for i in items)

    def test_click_toggles_menu_open(self, driver, w, ctx):
        self._open(driver, w)
        driver.find_element(By.CSS_SELECTOR, ".fab-toggle").click()
        # The 3rd bubble's open transition (transform 0.22s) starts after a
        # 0.1s cascade delay, so it isn't fully settled until ~0.32s -- too
        # close to a 0.3s wait under any system load. Give it real headroom.
        time.sleep(0.6)
        items = self._menu_items(driver)
        assert items and all(i.is_displayed() for i in items)

    def test_outside_click_closes_menu(self, driver, w, ctx):
        self._open(driver, w)
        driver.find_element(By.CSS_SELECTOR, ".fab-toggle").click()
        time.sleep(0.3)
        driver.find_element(By.TAG_NAME, "h1").click()
        time.sleep(0.3)
        items = self._menu_items(driver)
        assert not any(i.is_displayed() for i in items)

    def test_create_manually_link_target(self, driver, w, ctx):
        self._open(driver, w)
        manual = self._item_by_title(driver, "Create manually")
        assert manual is not None
        assert manual.get_attribute("href").endswith("/budget/expenses/new/")

    def test_create_manually_navigates_to_plain_form(self, driver, w, ctx):
        self._open(driver, w)
        driver.find_element(By.CSS_SELECTOR, ".fab-toggle").click()
        time.sleep(0.3)
        self._item_by_title(driver, "Create manually").click()
        time.sleep(1)
        assert "/budget/expenses/new/" in driver.current_url

    def test_ai_express_link_present_when_available(self, driver, w, ctx):
        self._open(driver, w)
        ai_link = self._item_by_title(driver, "AI Express")
        if ai_link is None:
            pytest.skip("AI Express not available for this test user (no trial key configured)")
        assert ai_link.get_attribute("href").endswith("/budget/ai/express-creation/")
