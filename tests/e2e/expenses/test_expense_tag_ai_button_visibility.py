"""
The "Let AI select tags" button (expense_form.html / scheduled_form.html)
must be gated the same way every other AI entry point in the app is:
present when ai_smart_create_available is true, gone entirely when the user
has ticked "Hide all AI features" (FeUser.disable_ai_ui) in their profile --
which short-circuits ai_smart_create_available regardless of an own/trial key
(see feusers/context_processors.py). Mirrors the ai_available/ai_unavailable
fixture pattern in test_add_expense_page.py.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, run_cmd, setup_user, cleanup_user

NEW_EXPENSE_URL   = "/budget/expenses/new/"
NEW_SCHEDULED_URL = "/budget/scheduled/new/"


def _set_fake_api_key(email: str) -> None:
    run_cmd(
        "shell", "-c",
        f"from feusers.models import FeUser; u = FeUser.objects.get(email='{email}'); "
        f"u.anthropic_api_key = 'sk-test-fake-key'; "
        f"u.save(update_fields=['anthropic_api_key'])",
    )


def _clear_api_key(email: str) -> None:
    run_cmd(
        "shell", "-c",
        f"from feusers.models import FeUser; u = FeUser.objects.get(email='{email}'); "
        f"u.anthropic_api_key = ''; "
        f"u.save(update_fields=['anthropic_api_key'])",
    )


def _set_disable_ai_ui(email: str, value: bool) -> None:
    run_cmd(
        "shell", "-c",
        f"from feusers.models import FeUser; u = FeUser.objects.get(email='{email}'); "
        f"u.disable_ai_ui = {value}; "
        f"u.save(update_fields=['disable_ai_ui'])",
    )


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


@pytest.fixture
def ai_available(ctx):
    """Force ai_smart_create_available True regardless of this environment's
    trial-key configuration, by giving the user their own (fake) key."""
    _set_fake_api_key(ctx["email"])
    yield
    _clear_api_key(ctx["email"])


@pytest.fixture
def ai_unavailable(ctx):
    """Force ai_smart_create_available False via 'Hide all AI features'
    (disable_ai_ui), regardless of an own/trial key."""
    _set_disable_ai_ui(ctx["email"], True)
    yield
    _set_disable_ai_ui(ctx["email"], False)


class TestAiAvailable:

    def test_button_present_on_new_expense_form(self, driver, w, ctx, ai_available):
        driver.get(_url(NEW_EXPENSE_URL))
        time.sleep(1)
        assert driver.find_elements(By.ID, "tag-ai-btn")

    def test_button_present_on_new_scheduled_expense_form(self, driver, w, ctx, ai_available):
        driver.get(_url(NEW_SCHEDULED_URL))
        time.sleep(1)
        assert driver.find_elements(By.ID, "tag-ai-btn")


class TestAiUnavailable:

    def test_button_absent_on_new_expense_form(self, driver, w, ctx, ai_unavailable):
        driver.get(_url(NEW_EXPENSE_URL))
        time.sleep(1)
        assert not driver.find_elements(By.ID, "tag-ai-btn")

    def test_button_absent_on_new_scheduled_expense_form(self, driver, w, ctx, ai_unavailable):
        driver.get(_url(NEW_SCHEDULED_URL))
        time.sleep(1)
        assert not driver.find_elements(By.ID, "tag-ai-btn")
