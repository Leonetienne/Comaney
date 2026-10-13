"""
Missing category/tags warning before saving an expense.

Saving an expense (or recurring expense) without a category or without tags
shows one confirmation dialog ("You are missing a category or tags...") with
Save anyway / Don't show again / Cancel. It only warns about what would put the
expense on the Unclassified Expenses page, and only about a field the user
could have filled in: no warning for a missing category if they own no
categories, or for missing tags if they own no tags. "Don't show again" turns
the warning off; the profile's "Expense entry" card turns it back on.
Several warnings (e.g. date outside the display period) show one after the
other, and the expense is saved once at the end.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, api_get, cleanup_user, run_cmd, server_today, setup_user

NEW_EXPENSE_URL = "/budget/expenses/new/"
NEW_SCHEDULED_URL = "/budget/scheduled/new/"
WARNING_TEXT = "You are missing a category or tags"


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w, first_name="Warn", last_name="Me", unclassified_warning=True)
    yield c
    cleanup_user(c["email"])


def _shell(code: str) -> str:
    return run_cmd("shell", "-c", code).strip()


def _warning_enabled(email: str) -> bool:
    return _shell(
        f"from feusers.models import FeUser; "
        f"print(FeUser.objects.get(email='{email}').warn_unclassified_on_save)"
    ) == "True"


def _set_warning_enabled(email: str, value: bool) -> None:
    _shell(
        f"from feusers.models import FeUser; "
        f"FeUser.objects.filter(email='{email}').update(warn_unclassified_on_save={value})"
    )


def _fill_expense_form(driver, title, *, category=False, tag=False, type_="expense"):
    """Fill the plain expense form fields; pick the first category/tag if asked."""
    driver.get(_url(NEW_EXPENSE_URL))
    time.sleep(1)
    driver.execute_script(
        "localStorage.removeItem('comaney_date_range');"
        "document.getElementById('id_title').value = arguments[0];"
        "document.getElementById('id_value').value = '7.00';"
        "document.getElementById('id_type').value = arguments[1];"
        "document.getElementById('id_date_due').value = arguments[2];"
        "document.getElementById('id_settled').checked = true;"
        "var cat = document.getElementById('id_category');"
        "cat.value = arguments[3] ? cat.options[1].value : '';"
        "var wantTag = arguments[4];"
        "document.querySelectorAll('input[name=tags]').forEach(function (cb, i) {"
        "    cb.checked = wantTag && i === 0;"
        "});",
        title, type_, server_today(), category, tag,
    )


def _submit(driver):
    driver.find_element(By.CSS_SELECTOR, ".form-wrap button[type=submit]").click()
    time.sleep(0.7)


def _dialog_visible(driver) -> bool:
    return "cdialog-visible" in driver.find_element(By.ID, "cdialog-backdrop").get_attribute("class")


def _dialog_text(driver) -> str:
    return driver.find_element(By.ID, "cdialog-msg").text


def _expense_exists(ctx, title) -> bool:
    resp = api_get("/api/v2/expenses/", ctx, params={"q": title})
    return any(e["title"] == title for e in resp.json()["expenses"])


class TestWarningOnExpenseForm:

    def test_missing_tags_shows_warning_with_three_buttons(self, driver, w, ctx):
        _fill_expense_form(driver, "Warn No Tags", category=True)
        _submit(driver)
        assert _dialog_visible(driver)
        assert WARNING_TEXT in _dialog_text(driver)
        assert driver.find_element(By.ID, "cdialog-ok").text == "Save anyway"
        assert driver.find_element(By.ID, "cdialog-extra").is_displayed()
        assert driver.find_element(By.ID, "cdialog-extra").text == "Don't show again"
        assert driver.find_element(By.ID, "cdialog-cancel").is_displayed()

    def test_cancel_does_not_save(self, driver, w, ctx):
        driver.find_element(By.ID, "cdialog-cancel").click()
        time.sleep(1)
        assert NEW_EXPENSE_URL in driver.current_url
        assert not _expense_exists(ctx, "Warn No Tags")

    def test_save_anyway_saves(self, driver, w, ctx):
        _submit(driver)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(2)
        assert NEW_EXPENSE_URL not in driver.current_url
        assert _expense_exists(ctx, "Warn No Tags")
        assert _warning_enabled(ctx["email"]), "Save anyway must not turn the warning off"

    def test_missing_category_shows_same_warning(self, driver, w, ctx):
        _fill_expense_form(driver, "Warn No Category", tag=True)
        _submit(driver)
        assert _dialog_visible(driver)
        assert WARNING_TEXT in _dialog_text(driver)
        driver.find_element(By.ID, "cdialog-cancel").click()
        time.sleep(0.5)

    def test_no_warning_when_classified(self, driver, w, ctx):
        _fill_expense_form(driver, "Warn Classified", category=True, tag=True)
        _submit(driver)
        time.sleep(1.5)
        assert NEW_EXPENSE_URL not in driver.current_url
        assert _expense_exists(ctx, "Warn Classified")

    def test_no_warning_for_savings_deposit(self, driver, w, ctx):
        _fill_expense_form(driver, "Warn Savings", type_="savings_dep")
        _submit(driver)
        time.sleep(1.5)
        assert NEW_EXPENSE_URL not in driver.current_url
        assert _expense_exists(ctx, "Warn Savings")


class TestWarningChainedWithDateWarning:

    def test_both_warnings_show_one_after_the_other(self, driver, w, ctx):
        _fill_expense_form(driver, "Warn Chain", category=True)
        driver.execute_script(
            "localStorage.setItem('comaney_date_range', "
            "JSON.stringify({from: '2020-01-01', to: '2020-01-31'}));"
        )
        _submit(driver)
        assert _dialog_visible(driver)
        assert "2020-01-01" in _dialog_text(driver), "Date warning must come first"
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(0.7)
        assert _dialog_visible(driver)
        assert WARNING_TEXT in _dialog_text(driver)
        assert not _expense_exists(ctx, "Warn Chain"), "Nothing is saved before the last warning"
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(2)
        driver.execute_script("localStorage.removeItem('comaney_date_range');")
        assert _expense_exists(ctx, "Warn Chain")


class TestWarningOnScheduledForm:

    def test_missing_tags_on_recurring_expense_warns(self, driver, w, ctx):
        driver.get(_url(NEW_SCHEDULED_URL))
        time.sleep(1)
        driver.execute_script(
            "document.getElementById('id_title').value = 'Warn Scheduled';"
            "document.getElementById('id_value').value = '9.00';"
            "var cat = document.getElementById('id_category');"
            "cat.value = cat.options[1].value;"
            "document.querySelectorAll('input[name=tags]').forEach(function (cb) { cb.checked = false; });"
        )
        _submit(driver)
        assert _dialog_visible(driver)
        assert WARNING_TEXT in _dialog_text(driver)
        driver.find_element(By.ID, "cdialog-cancel").click()
        time.sleep(0.5)
        assert NEW_SCHEDULED_URL in driver.current_url


class TestDontShowAgain:
    """Runs after the other ctx tests: it turns the warning off for that user."""

    def test_dont_show_again_saves_and_turns_warning_off(self, driver, w, ctx):
        _fill_expense_form(driver, "Warn Dismissed", category=True)
        _submit(driver)
        assert _dialog_visible(driver)
        driver.find_element(By.ID, "cdialog-extra").click()
        time.sleep(2)
        assert NEW_EXPENSE_URL not in driver.current_url
        assert _expense_exists(ctx, "Warn Dismissed")
        assert not _warning_enabled(ctx["email"])

    def test_no_warning_after_dismissal(self, driver, w, ctx):
        _fill_expense_form(driver, "Warn After Dismissal")
        _submit(driver)
        time.sleep(1.5)
        assert NEW_EXPENSE_URL not in driver.current_url
        assert _expense_exists(ctx, "Warn After Dismissal")

    def test_profile_setting_shows_off_and_turns_it_back_on(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        checkbox = driver.find_element(By.ID, "id_warn_unclassified_on_save")
        assert not checkbox.is_selected()
        driver.execute_script("arguments[0].checked = true;", checkbox)
        driver.find_element(
            By.CSS_SELECTOR, "#section-expense-entry button[type=submit]"
        ).click()
        time.sleep(1.5)
        assert driver.find_element(By.ID, "id_warn_unclassified_on_save").is_selected()
        assert _warning_enabled(ctx["email"])

    def test_warning_back_after_reenabling(self, driver, w, ctx):
        _fill_expense_form(driver, "Warn Reenabled", category=True)
        _submit(driver)
        assert _dialog_visible(driver)
        assert WARNING_TEXT in _dialog_text(driver)
        driver.find_element(By.ID, "cdialog-cancel").click()
        time.sleep(0.5)


class TestDemoUserCannotDismiss:
    """A demo account is shared, so one visitor must not switch the warning
    off for the next one."""

    @pytest.fixture(scope="class")
    def demo_like_user(self, driver, w):
        c = setup_user(None, None, unclassified_warning=True)
        _shell(
            f"from feusers.models import FeUser; "
            f"FeUser.objects.filter(email='{c['email']}').update(is_demo=True)"
        )
        yield c
        cleanup_user(c["email"])

    def test_dismiss_endpoint_refuses_demo_user(self, demo_like_user):
        status = _shell(
            "from django.conf import settings; from django.test import Client; "
            "from feusers.models import FeUser; "
            "settings.ENABLE_DEMO_USERS = True; "
            f"u = FeUser.objects.get(email='{demo_like_user['email']}'); "
            "c = Client(); s = c.session; "
            "s['feuser_id'] = u.pk; s['demo_banner_accepted'] = True; s.save(); "
            "print(c.post('/budget/unclassified/save-warning/dismiss/').status_code)"
        )
        assert status == "403"
        assert _warning_enabled(demo_like_user["email"])


class TestOwnedCatalogDecides:
    """Runs last: its fixture logs the browser in as a different user."""

    @pytest.fixture(scope="class")
    def no_tags_user(self, driver, w):
        c = setup_user(driver, w, unclassified_warning=True)
        _shell(
            f"from budget.models import Tag; "
            f"Tag.objects.filter(owning_feuser__email='{c['email']}').delete()"
        )
        yield c
        cleanup_user(c["email"])

    def test_no_warning_for_missing_tags_without_owned_tags(self, driver, w, no_tags_user):
        _fill_expense_form(driver, "Warn Tagless User", category=True)
        _submit(driver)
        time.sleep(1.5)
        assert NEW_EXPENSE_URL not in driver.current_url
        assert _expense_exists(no_tags_user, "Warn Tagless User")

    def test_missing_category_still_warns_without_owned_tags(self, driver, w, no_tags_user):
        _fill_expense_form(driver, "Warn Tagless No Cat")
        _submit(driver)
        assert _dialog_visible(driver)
        assert WARNING_TEXT in _dialog_text(driver)
        driver.find_element(By.ID, "cdialog-cancel").click()
        time.sleep(0.5)
