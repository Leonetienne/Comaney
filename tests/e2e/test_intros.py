"""
Intro modal tests.

Covers:
  - New user sees the getting-started intro modal
  - Intro modal is not shown a second time after dismissal
  - Upgrade intro is shown when intro_seen_at is older than 30 days
    and app_v_created_at differs from the current APP_VERSION
  - Upgrade intro is not shown a second time after dismissal
"""
import subprocess
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import (
    _url, setup_user, cleanup_user, browser_login,
    DOCKER_WEB, PASSWORD,
)

INTRO_MODAL_ID        = "intro-modal"
UPGRADE_MODAL_ID      = "upgrade-intro-modal"
VISIBLE_CLASS         = "cdialog-visible"
FAKE_OLD_VERSION      = "0.0.0"


def _shell(code: str, timeout: int = 15) -> str:
    r = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c", code],
        capture_output=True, text=True, timeout=timeout,
    )
    assert r.returncode == 0, f"shell failed:\n{r.stderr}"
    return r.stdout.strip()


def _modal_visible(driver, modal_id: str) -> bool:
    els = driver.find_elements(By.ID, modal_id)
    if not els:
        return False
    return VISIBLE_CLASS in els[0].get_attribute("class")


def _set_intro_seen_at(email: str, days_ago: int):
    _shell(
        f"from django.utils import timezone; from datetime import timedelta;"
        f" from feusers.models import FeUser;"
        f" u = FeUser.objects.get(email='{email}');"
        f" u.intro_seen_at = timezone.now() - timedelta(days={days_ago});"
        f" u.save(update_fields=['intro_seen_at'])"
    )


def _set_app_v_created_at(email: str, version: str):
    _shell(
        f"from feusers.models import FeUser;"
        f" u = FeUser.objects.get(email='{email}');"
        f" u.app_v_created_at = '{version}';"
        f" u.save(update_fields=['app_v_created_at'])"
    )


def _clear_upgrade_intro_seen(email: str):
    _shell(
        f"from feusers.models import FeUser;"
        f" u = FeUser.objects.get(email='{email}');"
        f" u.last_upgrade_intro_v_seen = None;"
        f" u.save(update_fields=['last_upgrade_intro_v_seen'])"
    )


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestIntroModal:

    def test_new_user_sees_intro(self, driver, w, ctx):
        # setup_user already logged us in; navigate to dashboard to trigger context
        driver.get(_url("/budget/"))
        time.sleep(1)
        assert _modal_visible(driver, INTRO_MODAL_ID), \
            "Intro modal should be visible for a brand-new user"

    def test_dismiss_intro_marks_seen(self, driver, w, ctx):
        # Click "No, thank you" to dismiss without opening docs
        btn = driver.find_element(By.ID, "intro-modal-dismiss")
        btn.click()
        time.sleep(1)
        assert not _modal_visible(driver, INTRO_MODAL_ID), \
            "Intro modal should close after dismissal"

    def test_intro_not_shown_again(self, driver, w, ctx):
        # Re-login and re-visit to confirm intro_seen_at is persisted
        driver.delete_all_cookies()
        browser_login(driver, w, ctx["email"], PASSWORD)
        driver.get(_url("/budget/"))
        time.sleep(1)
        assert not _modal_visible(driver, INTRO_MODAL_ID), \
            "Intro modal must not reappear after it was dismissed"


class TestUpgradeIntroModal:

    def test_upgrade_intro_requires_old_enough_intro(self, driver, w, ctx):
        # intro_seen_at is recent (just dismissed above); upgrade intro must be suppressed
        _set_app_v_created_at(ctx["email"], FAKE_OLD_VERSION)
        _clear_upgrade_intro_seen(ctx["email"])
        driver.delete_all_cookies()
        browser_login(driver, w, ctx["email"], PASSWORD)
        driver.get(_url("/budget/"))
        time.sleep(1)
        assert not _modal_visible(driver, UPGRADE_MODAL_ID), \
            "Upgrade intro must be suppressed when intro_seen_at is within the 30-day cooldown"

    def test_upgrade_intro_shown_after_cooldown(self, driver, w, ctx):
        # Push intro_seen_at back 31 days and use an old creation version
        _set_intro_seen_at(ctx["email"], days_ago=31)
        _set_app_v_created_at(ctx["email"], FAKE_OLD_VERSION)
        _clear_upgrade_intro_seen(ctx["email"])
        driver.delete_all_cookies()
        browser_login(driver, w, ctx["email"], PASSWORD)
        driver.get(_url("/budget/"))
        time.sleep(1)
        assert _modal_visible(driver, UPGRADE_MODAL_ID), \
            "Upgrade intro must be shown when intro_seen_at > 30 days and app_v_created_at differs from current version"

    def test_upgrade_intro_suppressed_for_same_version(self, driver, w, ctx):
        # If the user was created on the current APP_VERSION, the upgrade intro is irrelevant
        current_version = _shell(
            "from django.conf import settings; print(settings.APP_VERSION)"
        )
        _set_intro_seen_at(ctx["email"], days_ago=31)
        _set_app_v_created_at(ctx["email"], current_version)
        _clear_upgrade_intro_seen(ctx["email"])
        driver.delete_all_cookies()
        browser_login(driver, w, ctx["email"], PASSWORD)
        driver.get(_url("/budget/"))
        time.sleep(1)
        assert not _modal_visible(driver, UPGRADE_MODAL_ID), \
            "Upgrade intro must not show when user was created on the current APP_VERSION"

    def test_upgrade_intro_not_shown_again(self, driver, w, ctx):
        # Restore old version so the upgrade intro would normally show,
        # then dismiss it and confirm it doesn't reappear
        _set_app_v_created_at(ctx["email"], FAKE_OLD_VERSION)
        _clear_upgrade_intro_seen(ctx["email"])
        driver.delete_all_cookies()
        browser_login(driver, w, ctx["email"], PASSWORD)
        driver.get(_url("/budget/"))
        time.sleep(1)
        assert _modal_visible(driver, UPGRADE_MODAL_ID), "Precondition: upgrade modal must be visible"
        driver.find_element(By.ID, "upgrade-intro-ok").click()
        time.sleep(1)
        assert not _modal_visible(driver, UPGRADE_MODAL_ID), \
            "Upgrade intro should close after dismissal"

        driver.delete_all_cookies()
        browser_login(driver, w, ctx["email"], PASSWORD)
        driver.get(_url("/budget/"))
        time.sleep(1)
        assert not _modal_visible(driver, UPGRADE_MODAL_ID), \
            "Upgrade intro must not reappear after it was dismissed for this version"
