"""
Add Expense selector page (budget:add_expense).

The sidebar's "Add Expense" link routes to the AI-vs-manual selector page
when AI express creation is available for the user, or straight to the
manual expense form when it isn't -- mirroring how the old AI-only sidebar
section used to be hidden entirely in that case. The selector page's three
panels (Enter Manually / Create with AI / Create new recurring expense) each
link to, and successfully load, their target page.
"""
import time

import pytest
import requests
from selenium.webdriver.common.by import By

from helpers import _url, run_cmd, setup_user, cleanup_user, session_cookies

ADD_EXPENSE_URL = "/budget/expenses/add/"
MANUAL_URL      = "/budget/expenses/new/"
AI_URL          = "/budget/ai/express-creation/"
RECURRING_URL   = "/budget/scheduled/new/"


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


@pytest.fixture(scope="module")
def sess(driver, ctx):
    driver.get(_url("/budget/"))
    s = requests.Session()
    s.cookies.update(session_cookies(driver))
    return s


@pytest.fixture
def ai_available(ctx):
    """Force ai_smart_create_available True regardless of this environment's
    trial-key configuration, by giving the user their own (fake) key."""
    _set_fake_api_key(ctx["email"])
    yield
    _clear_api_key(ctx["email"])


@pytest.fixture
def ai_unavailable(ctx):
    """Force ai_smart_create_available False regardless of an own/trial key
    (disable_ai_ui short-circuits both, see feusers/context_processors.py)."""
    _set_disable_ai_ui(ctx["email"], True)
    yield
    _set_disable_ai_ui(ctx["email"], False)


class TestAiAvailable:

    def test_sidebar_link_points_to_selector(self, driver, w, ctx, ai_available):
        driver.get(_url("/budget/"))
        time.sleep(1)
        link = driver.find_element(By.LINK_TEXT, "Add Expense")
        assert link.get_attribute("href").endswith(ADD_EXPENSE_URL)

    def test_sidebar_link_navigates_to_selector(self, driver, w, ctx, ai_available):
        driver.get(_url("/budget/"))
        time.sleep(1)
        driver.find_element(By.LINK_TEXT, "Add Expense").click()
        time.sleep(1)
        assert driver.current_url.endswith(ADD_EXPENSE_URL)

    def test_manual_panel_navigates_to_manual_form(self, driver, w, ctx, ai_available):
        driver.get(_url(ADD_EXPENSE_URL))
        time.sleep(1)
        driver.find_element(By.ID, "add-expense-manual-tile").click()
        time.sleep(1)
        assert driver.current_url.endswith(MANUAL_URL)

    def test_ai_panel_navigates_to_express_creation(self, driver, w, ctx, ai_available):
        driver.get(_url(ADD_EXPENSE_URL))
        time.sleep(1)
        driver.find_element(By.ID, "add-expense-ai-tile").click()
        time.sleep(1)
        assert driver.current_url.endswith(AI_URL)

    def test_recurring_panel_navigates_to_scheduled_form(self, driver, w, ctx, ai_available):
        driver.get(_url(ADD_EXPENSE_URL))
        time.sleep(1)
        driver.find_element(By.CSS_SELECTOR, ".add-expense-tile--recurring").click()
        time.sleep(1)
        assert driver.current_url.endswith(RECURRING_URL)

    def test_all_panel_target_urls_return_2xx(self, driver, w, ctx, ai_available, sess):
        for path in (ADD_EXPENSE_URL, MANUAL_URL, AI_URL, RECURRING_URL):
            r = sess.get(_url(path))
            assert 200 <= r.status_code < 300, f"{path} returned {r.status_code}"


class TestAiUnavailable:

    def test_sidebar_link_points_directly_to_manual_form(self, driver, w, ctx, ai_unavailable):
        driver.get(_url("/budget/"))
        time.sleep(1)
        link = driver.find_element(By.LINK_TEXT, "Add Expense")
        assert link.get_attribute("href").endswith(MANUAL_URL)

    def test_sidebar_link_navigates_directly_to_manual_form(self, driver, w, ctx, ai_unavailable):
        driver.get(_url("/budget/"))
        time.sleep(1)
        driver.find_element(By.LINK_TEXT, "Add Expense").click()
        time.sleep(1)
        assert driver.current_url.endswith(MANUAL_URL)

    def test_direct_hit_on_selector_url_redirects_to_manual_form(self, driver, w, ctx, ai_unavailable):
        driver.get(_url(ADD_EXPENSE_URL))
        time.sleep(1)
        assert driver.current_url.endswith(MANUAL_URL)
