"""
"Enter manually" share dialog on the expense and recurring expense forms, plus
the server-side share bounds check (req sharing.manual.*, sharing.assign.share-bounds).
"""
import json

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from helpers import _url, setup_user, cleanup_user, server_today
from bhelpers import (
    _shell, _create_group, share_dialog_open, share_dialog_rows, share_dialog_type,
    share_dialog_value, share_dialog_click, share_dialog_reason, share_dialog_save_enabled,
    share_dialog_is_open,
)
from pacing import pause


def _add_dummy(email: str, name: str) -> None:
    _shell(
        f"from buddies.models import DummyUser; from feusers.models import FeUser; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"DummyUser.objects.create(owning_feuser=u, display_name='{name}')"
    )


def _fill_expense(driver, title: str, value: str) -> None:
    driver.execute_script(
        "document.getElementById('id_title').value = arguments[0];"
        "var v = document.getElementById('id_value'); v.value = arguments[1];"
        "v.dispatchEvent(new Event('input', {bubbles: true}));"
        "var d = document.getElementById('id_date_due'); if (d) d.value = arguments[2];",
        title, value, server_today(),
    )


def _pick_contact(driver, name: str) -> None:
    sel = driver.find_element(By.ID, "buddy-participant-select")
    opt = next(o for o in sel.find_elements(By.TAG_NAME, "option") if name in o.text)
    Select(sel).select_by_value(opt.get_attribute("value"))
    pause(0.3)


def _manual_btn(driver):
    return driver.find_element(By.ID, "buddy-manual-btn")


def _submit(driver) -> None:
    driver.find_element(By.CSS_SELECTOR, ".form-wrap button[type=submit]").click()
    pause(2)


def _spendings_of(title: str, email: str) -> list:
    out = _shell(
        f"import json; from budget.models import Expense; from feusers.models import FeUser; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"e = Expense.objects.filter(title='{title}', owning_feuser=u).first(); "
        f"print(json.dumps([float(bs.share_percent) for bs in e.buddy_spendings.all()] if e else None))"
    )
    return json.loads(out)


class TestManualSharesContact:
    """Contact expense of 8.00: percent and amount inputs, save gate, save and cancel."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Mia", last_name="Manual")
        _add_dummy(c["email"], "Manual Contact")
        yield c
        cleanup_user(c["email"])

    def test_dialog_prefilled_with_current_shares(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/new/"))
        pause(1)
        _fill_expense(driver, "Manual Share Dinner", "8.00")
        driver.find_element(By.ID, "assign-contact").click()
        pause(0.5)
        assert not _manual_btn(driver).is_displayed(), "share buttons stay hidden until a participant is picked"
        assert not driver.find_element(By.ID, "buddy-equal-btn").is_displayed()
        _pick_contact(driver, "Manual Contact")
        assert _manual_btn(driver).is_displayed()
        share_dialog_open(driver, _manual_btn(driver))
        rows = share_dialog_rows(driver)
        assert len(rows) == 2, "payer row plus one contact row expected"
        assert "Manual Contact" in rows[1].text
        assert share_dialog_value(driver, 0, "pct") == "50"
        assert share_dialog_value(driver, 1, "amt") == "4.00"
        assert not driver.find_elements(By.CSS_SELECTOR, ".share-dialog-remove"), \
            "a contact expense offers no remove button"
        assert share_dialog_save_enabled(driver)

    def test_percent_recomputes_amount_and_blocks_save(self, driver, w, ctx):
        share_dialog_type(driver, 1, "pct", "75")
        assert share_dialog_value(driver, 1, "amt") == "6.00"
        assert share_dialog_value(driver, 0, "pct") == "50", "other rows stay unchanged"
        assert not share_dialog_save_enabled(driver)
        reason = share_dialog_reason(driver)
        assert "25 % (2.00" in reason and "over 100 %" in reason, reason

    def test_amount_recomputes_percent_and_enables_save(self, driver, w, ctx):
        share_dialog_type(driver, 0, "amt", "2,00")
        assert share_dialog_value(driver, 0, "pct") == "25"
        assert share_dialog_save_enabled(driver)
        assert share_dialog_reason(driver) == ""

    def test_save_applies_to_sliders(self, driver, w, ctx):
        share_dialog_click(driver, ".share-dialog-save")
        assert not share_dialog_is_open(driver)
        assert driver.find_element(By.ID, "bs-pct-0").text == "75.0%"
        assert driver.find_element(By.ID, "buddy-payer-pct").text == "25.0%"

    def test_cancel_keeps_shares(self, driver, w, ctx):
        share_dialog_open(driver, _manual_btn(driver))
        share_dialog_type(driver, 1, "pct", "10")
        share_dialog_click(driver, ".share-dialog-cancel")
        assert not share_dialog_is_open(driver)
        assert driver.find_element(By.ID, "bs-pct-0").text == "75.0%"

    def test_saved_share_is_exact(self, driver, w, ctx):
        _submit(driver)
        assert _spendings_of("Manual Share Dinner", ctx["email"]) == [75.0]


class TestManualSharesProject:
    """Project expense with two offline members: reset, fill remaining, remove."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Pia", last_name="Project")
        gid = _create_group(c["email"], "Manual Shares Project")
        for name in ("Anna Offline", "Ben Offline"):
            _shell(
                f"from buddies.services import BuddyGroupService; from feusers.models import FeUser; "
                f"from buddies.models import Project; u = FeUser.objects.get(email='{c['email']}'); "
                f"BuddyGroupService.create_group_dummy(Project.objects.get(pk={gid}), u, '{name}')"
            )
        yield {**c, "gid": int(gid)}
        cleanup_user(c["email"])

    def _checkbox(self, driver, name):
        lbl = next(l for l in driver.find_elements(By.CSS_SELECTOR, ".buddy-participant-cb") if name in l.text)
        return lbl.find_element(By.TAG_NAME, "input")

    def test_open_with_both_members(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/new/"))
        pause(1)
        _fill_expense(driver, "Manual Share Groceries", "30.00")
        driver.find_element(By.ID, "assign-project").click()
        pause(0.5)
        driver.execute_script(
            "var s = document.getElementById('buddy-group-select'); s.value = arguments[0];"
            "s.dispatchEvent(new Event('change', {bubbles: true}));", str(ctx["gid"]))
        pause(0.5)
        for name in ("Anna Offline", "Ben Offline"):
            cb = self._checkbox(driver, name)
            if not cb.is_selected():
                driver.execute_script("arguments[0].click();", cb)
                pause(0.2)
        share_dialog_open(driver, _manual_btn(driver))
        assert len(share_dialog_rows(driver)) == 3
        assert len(driver.find_elements(By.CSS_SELECTOR, ".share-dialog-remove")) == 2, \
            "every participant row but the payer's has a remove button"

    def test_reset_then_fill_remaining(self, driver, w, ctx):
        share_dialog_click(driver, ".share-dialog-row:nth-child(2) .share-dialog-reset")
        share_dialog_click(driver, ".share-dialog-row:nth-child(3) .share-dialog-reset")
        assert share_dialog_value(driver, 1, "pct") == "" and share_dialog_value(driver, 1, "amt") == ""
        share_dialog_type(driver, 0, "pct", "40")
        assert not share_dialog_save_enabled(driver)
        assert "2 empty rows" in share_dialog_reason(driver)
        share_dialog_click(driver, ".share-dialog-fill")
        assert share_dialog_value(driver, 1, "pct") == "30"
        assert share_dialog_value(driver, 2, "amt") == "9.00"
        assert share_dialog_save_enabled(driver)

    def test_remove_then_cancel_keeps_participant(self, driver, w, ctx):
        share_dialog_click(driver, ".share-dialog-row:nth-child(2) .share-dialog-remove")
        assert len(share_dialog_rows(driver)) == 2
        share_dialog_click(driver, ".share-dialog-cancel")
        assert self._checkbox(driver, "Anna Offline").is_selected()

    def test_remove_then_save_drops_participant(self, driver, w, ctx):
        share_dialog_open(driver, _manual_btn(driver))
        share_dialog_click(driver, ".share-dialog-row:nth-child(2) .share-dialog-remove")
        share_dialog_type(driver, 0, "pct", "20")
        share_dialog_type(driver, 1, "pct", "80")
        share_dialog_click(driver, ".share-dialog-save")
        assert not self._checkbox(driver, "Anna Offline").is_selected()
        assert len(driver.find_elements(By.CSS_SELECTOR, "#buddy-sliders .buddy-slider-row")) == 2
        _submit(driver)
        assert _spendings_of("Manual Share Groceries", ctx["email"]) == [80.0]

    def test_removing_last_participant_gives_payer_100(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/new/"))
        pause(1)
        _fill_expense(driver, "Manual Share Solo", "30.00")
        driver.find_element(By.ID, "assign-project").click()
        pause(0.5)
        driver.execute_script(
            "var s = document.getElementById('buddy-group-select'); s.value = arguments[0];"
            "s.dispatchEvent(new Event('change', {bubbles: true}));", str(ctx["gid"]))
        pause(0.5)
        cb = self._checkbox(driver, "Ben Offline")
        if not cb.is_selected():
            driver.execute_script("arguments[0].click();", cb)
            pause(0.2)
        cb = self._checkbox(driver, "Anna Offline")
        if cb.is_selected():
            driver.execute_script("arguments[0].click();", cb)
            pause(0.2)
        share_dialog_open(driver, _manual_btn(driver))
        share_dialog_click(driver, ".share-dialog-row:nth-child(2) .share-dialog-remove")
        assert len(share_dialog_rows(driver)) == 1
        assert share_dialog_value(driver, 0, "pct") == "100"
        assert share_dialog_save_enabled(driver)


class TestManualSharesRecurring:
    """The recurring expense form offers the same dialog."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Rex", last_name="Recurring")
        _add_dummy(c["email"], "Rent Mate")
        yield c
        cleanup_user(c["email"])

    def test_manual_share_saved_on_recurring_expense(self, driver, w, ctx):
        driver.get(_url("/budget/scheduled/new/"))
        pause(1)
        driver.execute_script(
            "document.getElementById('id_title').value = 'Manual Share Rent';"
            "var v = document.getElementById('id_value'); v.value = '1000.00';"
            "v.dispatchEvent(new Event('input', {bubbles: true}));"
            "document.getElementById('id_repeat_every_factor').value = '1';"
            "document.getElementById('id_repeat_base_date').value = arguments[0];",
            server_today(),
        )
        Select(driver.find_element(By.ID, "id_repeat_every_unit")).select_by_value("months")
        driver.find_element(By.ID, "assign-contact").click()
        pause(0.5)
        _pick_contact(driver, "Rent Mate")
        share_dialog_open(driver, _manual_btn(driver))
        share_dialog_type(driver, 1, "amt", "650")
        share_dialog_type(driver, 0, "pct", "35")
        share_dialog_click(driver, ".share-dialog-save")
        _submit(driver)
        out = _shell(
            "import json; from budget.models import ScheduledExpense; "
            "s = ScheduledExpense.objects.get(title='Manual Share Rent'); "
            "print(json.dumps([x['share_percent'] for x in json.loads(s.assign_spendings_json)]))"
        )
        assert json.loads(out) == [65.0]


class TestShareBoundsRejectedOnForm:
    """A forged submission with shares above 100 % is rejected with an explanation."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Olga", last_name="Overshare")
        _add_dummy(c["email"], "Forged Share Contact")
        yield c
        cleanup_user(c["email"])

    def test_shares_over_100_not_saved(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/new/"))
        pause(1)
        _fill_expense(driver, "Forged Share Expense", "10.00")
        driver.find_element(By.ID, "assign-contact").click()
        pause(0.5)
        _pick_contact(driver, "Forged Share Contact")
        driver.execute_script(
            "var j = document.getElementById('buddy-spendings-json');"
            "var s = JSON.parse(j.value); s[0].share_percent = 120; j.value = JSON.stringify(s);"
        )
        _submit(driver)
        assert "at most 100 %" in driver.page_source
        assert _spendings_of("Forged Share Expense", ctx["email"]) is None
