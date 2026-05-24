"""
Notification bell – "Mark all read" button tests.

Creates several dummy notifications directly in the DB, then verifies that
clicking "Mark all read" clears the unread badge and removes the unread
highlight from every item in the dropdown.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inject_notifs(email: str, count: int) -> None:
    """Insert `count` unread notifications directly into the DB."""
    _shell(
        f"from feusers.models import FeUser, Notification; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"[Notification.objects.create("
        f"  owning_feuser=u, type='expense_reminders', "
        f"  subject='Test', message='Mark-all-read test notif ' + str(i)"
        f") for i in range({count})]"
    )


def _open_dropdown(driver):
    driver.find_element(By.ID, "notif-bell").click()
    time.sleep(2)


def _badge_count(driver) -> int:
    els = driver.find_elements(By.ID, "notif-badge")
    if not els:
        return 0
    badge = els[0]
    style = badge.get_attribute("style") or ""
    if "display: none" in style or not badge.is_displayed():
        return 0
    text = badge.text.strip()
    return int(text) if text.isdigit() else (99 if text else 0)


def _unread_items(driver) -> list:
    return driver.find_elements(By.CSS_SELECTOR, "#notif-list .notif-item--unread")


# ---------------------------------------------------------------------------
# Module fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ctx(driver, w):
    user = setup_user(driver, w, first_name="Marky", last_name="ReadTest")
    yield {"user": user}
    cleanup_user(user["email"])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMarkAllRead:

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        _inject_notifs(ctx["user"]["email"], 5)

    def test_badge_shows_before_mark_all(self, driver, w, ctx):
        _login_as(driver, ctx["user"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        assert _badge_count(driver) >= 5, \
            "Expected at least 5 unread before mark-all-read"

    def test_mark_all_read_clears_badge(self, driver, w, ctx):
        _login_as(driver, ctx["user"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        _open_dropdown(driver)
        assert len(_unread_items(driver)) > 0, "Dropdown has no unread items before marking"
        driver.find_element(By.ID, "notif-mark-all-read").click()
        time.sleep(1)
        assert _badge_count(driver) == 0, \
            f"Badge should be gone after mark-all-read, got {_badge_count(driver)}"

    def test_mark_all_read_removes_unread_highlights(self, driver, w, ctx):
        # Re-use the session from the previous test (dropdown still open).
        # The items should have lost the --unread modifier class.
        unread = _unread_items(driver)
        assert len(unread) == 0, \
            f"{len(unread)} item(s) still show as unread in the dropdown"

    def test_badge_stays_gone_after_page_reload(self, driver, w, ctx):
        driver.get(_url("/budget/"))
        time.sleep(1)
        assert _badge_count(driver) == 0, \
            "Badge reappeared after page reload – notifications were not persisted as read"
