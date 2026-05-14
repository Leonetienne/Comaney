"""
Expense form: buddy payment section, participant selection, equal-share split,
upfront-payer modes, and slider interactivity on re-edit.

Also covers the regression where checking a group-mode participant checkbox had
no effect when a non-me (dummy) member was selected as the upfront payer.
"""
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from helpers import (
    _url, setup_user, cleanup_user, api_get, server_today,
    fetch_email, mailpit_seen_ids,
)
from bhelpers import _shell, _create_buddy_link, _get_pk, _create_group


def _select_first_participant(driver):
    """Select the first available participant, handling both single (dropdown)
    and multi (checkboxes) modes that the buddy expense JS may render."""
    sel_els = driver.find_elements(By.ID, "buddy-participant-select")
    if sel_els:
        sel = Select(sel_els[0])
        sel.select_by_index(1)  # index 0 is the empty '-- Select buddy --' option
        time.sleep(0.3)
        return
    cbs = driver.find_elements(By.CSS_SELECTOR,
        "#buddy-participants-checkboxes input[type=checkbox]")
    if cbs:
        cbs[0].click()
        time.sleep(0.3)


# ---------------------------------------------------------------------------
# Buddy section visibility and equal-share UX
# ---------------------------------------------------------------------------

class TestBuddyPaymentSectionUI:
    """The buddy payment section appears and the equal-share button works."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Eve", last_name="FormUser")
        email = c["email"]
        _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"DummyUser.objects.create(owning_feuser=u, display_name='Form Buddy')"
        )
        yield c
        cleanup_user(c["email"])

    def test_buddy_section_visible_with_buddy(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        assert "This is a buddy payment" in driver.page_source
        assert "Form Buddy" in driver.page_source

    def test_enable_buddy_payment_shows_section(self, driver, w, ctx):
        driver.find_element(By.ID, "buddy-payment-cb").click()
        time.sleep(0.5)
        section = driver.find_element(By.ID, "buddy-payment-section")
        assert section.is_displayed()

    def test_participant_selector_present(self, driver, w, ctx):
        sel_els = driver.find_elements(By.ID, "buddy-participant-select")
        cbs = driver.find_elements(By.CSS_SELECTOR,
            "#buddy-participants-checkboxes input[type=checkbox]")
        assert len(sel_els) >= 1 or len(cbs) >= 1, \
            "Participant selector (dropdown in single mode, or checkboxes in group mode) must be shown"

    def test_select_participant_and_equal_shares_gives_50_50(self, driver, w, ctx):
        _select_first_participant(driver)
        driver.find_element(By.ID, "buddy-equal-btn").click()
        time.sleep(0.3)
        pct_els = driver.find_elements(By.CSS_SELECTOR, "#buddy-sliders .buddy-slider-pct")
        assert len(pct_els) == 2, "Payer row + participant row expected"
        assert all("50.0%" in el.text for el in pct_els), \
            f"Both shares must be 50%, got: {[el.text for el in pct_els]}"

    def test_share_sum_is_100(self, driver, w, ctx):
        pct_els = driver.find_elements(By.CSS_SELECTOR, "#buddy-sliders .buddy-slider-pct")
        total = sum(float(el.text.rstrip("%")) for el in pct_els)
        assert abs(total - 100.0) < 0.1, \
            f"All slider shares must sum to 100%, got: {[el.text for el in pct_els]}"


# ---------------------------------------------------------------------------
# Save expense with dummy participant (I pay)
# ---------------------------------------------------------------------------

class TestExpenseWithDummyParticipant:
    """Create expense: me as payer, dummy as participant. Expense appears in normal list."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Sam", last_name="Payer")
        email = c["email"]
        _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"DummyUser.objects.create(owning_feuser=u, display_name='Participant Dummy')"
        )
        yield c
        cleanup_user(c["email"])

    def test_create_expense_with_dummy_participant(self, driver, w, ctx):
        today = server_today()
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        driver.find_element(By.ID, "id_title").clear()
        driver.find_element(By.ID, "id_title").send_keys("Buddy Participant Expense")
        driver.find_element(By.ID, "id_value").clear()
        driver.find_element(By.ID, "id_value").send_keys("80.00")
        driver.execute_script(
            f"document.getElementById('id_date_due').value = '{today}';"
            "document.getElementById('id_settled').checked = true;"
        )
        driver.find_element(By.ID, "buddy-payment-cb").click()
        time.sleep(0.5)
        _select_first_participant(driver)
        driver.find_element(By.ID, "buddy-equal-btn").click()
        time.sleep(0.3)
        driver.find_element(By.CSS_SELECTOR, "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)").click()
        time.sleep(2)
        assert "/budget/expenses/" in driver.current_url

    def test_expense_in_api_list(self, driver, w, ctx):
        resp = api_get("/api/v1/expenses/", ctx, params={"q": "Buddy Participant Expense"})
        assert resp.status_code == 200
        assert any(e["title"] == "Buddy Participant Expense" for e in resp.json()["expenses"]), \
            "Expense with dummy participant (I pay) must appear in the expense API"

    def test_expense_visible_on_buddy_summary(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Buddy Participant Expense" in driver.page_source


# ---------------------------------------------------------------------------
# Save expense with dummy as upfront payer (redirect to summary)
# ---------------------------------------------------------------------------

class TestExpenseWithDummyAsPayer:
    """Create expense: dummy is upfront payer. Must redirect to /buddies/summary/."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Greg", last_name="Borrower")
        email = c["email"]
        dummy_id = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Greg Lender'); "
            f"print(d.pk)"
        )
        c["dummy_id"] = int(dummy_id)
        yield c
        cleanup_user(c["email"])

    def test_create_expense_dummy_as_payer(self, driver, w, ctx):
        today = server_today()
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        driver.find_element(By.ID, "id_title").clear()
        driver.find_element(By.ID, "id_title").send_keys("Dummy Payer Expense")
        driver.find_element(By.ID, "id_value").clear()
        driver.find_element(By.ID, "id_value").send_keys("60.00")
        driver.execute_script(
            f"document.getElementById('id_date_due').value = '{today}';"
            "document.getElementById('id_settled').checked = true;"
        )
        driver.find_element(By.ID, "buddy-payment-cb").click()
        time.sleep(0.5)
        # Select dummy as upfront payer via JS
        driver.execute_script(
            f"var sel = document.getElementById('buddy-upfront-select');"
            f"sel.value = 'dummy:{ctx['dummy_id']}';"
            f"sel.dispatchEvent(new Event('change', {{bubbles: true}}));"
        )
        time.sleep(0.4)
        # Me is now the participant; check the checkbox for me
        cbs = driver.find_elements(By.CSS_SELECTOR, "#buddy-participants-checkboxes input[type=checkbox]")
        if cbs:
            cbs[0].click()
            time.sleep(0.3)
            driver.find_element(By.ID, "buddy-equal-btn").click()
            time.sleep(0.3)
        driver.find_element(By.CSS_SELECTOR, "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)").click()
        time.sleep(2)

    def test_redirected_to_buddy_summary(self, driver, w, ctx):
        assert "/buddies/summary/" in driver.current_url, \
            f"Expected redirect to /buddies/summary/, got: {driver.current_url}"

    def test_flash_message_mentions_no_expense_list(self, driver, w, ctx):
        assert "won't appear in your regular expense list" in driver.page_source

    def test_expense_not_in_api(self, driver, w, ctx):
        resp = api_get("/api/v1/expenses/", ctx, params={"q": "Dummy Payer Expense"})
        assert resp.status_code == 200
        assert not any(e["title"] == "Dummy Payer Expense" for e in resp.json()["expenses"]), \
            "Dummy-payer expense must not appear in the expense API (is_dummy=True)"

    def test_expense_visible_on_summary(self, driver, w, ctx):
        assert "Dummy Payer Expense" in driver.page_source, \
            "Dummy-payer expense must be visible on the buddy summary page"


# ---------------------------------------------------------------------------
# Slider interactivity on re-edit (regression)
# ---------------------------------------------------------------------------

class TestBuddyExpenseReEdit:
    """Re-editing a buddy expense: sliders are interactive, not broken by HTML-encoding."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Reg", last_name="ReEditer")
        email = c["email"]
        dummy_id = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Re-Edit Buddy'); "
            f"print(d.pk)"
        )
        _shell(
            f"from budget.expense_factory import create_expense; "
            f"from feusers.models import FeUser; from budget.models import TransactionType; "
            f"from decimal import Decimal; import datetime; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"create_expense(owning_feuser=u, title='Re-Edit Expense', "
            f"  type=TransactionType.EXPENSE, value=Decimal('90.00'), "
            f"  date_due=datetime.date.today(), settled=False, "
            f"  buddy_spendings=[{{'type': 'dummy', 'id': {dummy_id}, 'share_percent': 50}}])"
        )
        yield c
        cleanup_user(c["email"])

    def test_edit_form_has_buddy_cb_prechecked(self, driver, w, ctx):
        resp = api_get("/api/v1/expenses/", ctx, params={"q": "Re-Edit Expense"})
        exp_id = resp.json()["expenses"][0]["id"]
        ctx["exp_id"] = exp_id
        driver.get(_url(f"/budget/expenses/{exp_id}/edit/"))
        time.sleep(1)
        cb = driver.find_element(By.ID, "buddy-payment-cb")
        assert cb.get_attribute("checked") is not None, \
            "buddy-payment-cb must be pre-checked when re-editing a buddy expense"

    def test_slider_rows_present(self, driver, w, ctx):
        pct_els = driver.find_elements(By.CSS_SELECTOR, "#buddy-sliders .buddy-slider-pct")
        assert len(pct_els) >= 2, "Expected payer + participant slider rows"

    def test_slider_is_interactive(self, driver, w, ctx):
        # #bs-slider-0 is the first participant slider (payer row uses #buddy-payer-slider)
        slider = driver.find_element(By.CSS_SELECTOR, "#bs-slider-0")
        driver.execute_script(
            "var s = arguments[0]; s.value = 30;"
            "s.dispatchEvent(new Event('input', {bubbles: true}));",
            slider,
        )
        time.sleep(0.3)
        pct_el = driver.find_element(By.ID, "bs-pct-0")
        assert "30.0%" in pct_el.text, \
            f"Participant slider did not update to 30%, got: {pct_el.text!r}"


# ---------------------------------------------------------------------------
# Real buddy as upfront payer (req 3.5): UI flow + approval email
# ---------------------------------------------------------------------------

class TestRealBuddyAsUptrontPayer:
    """A creates expense in UI with B (real buddy) as upfront payer.

    Expects: redirect to /buddies/summary/, expense shows 'Needs approval'
    on both A's and B's summary pages, and B receives an approval email.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Upfront", last_name="Asker")
        b = setup_user(None, None, first_name="Upfront", last_name="Payer")
        _create_buddy_link(a["email"], b["email"])
        b_pk = _get_pk(b["email"])
        ctx = {"a": a, "b": b, "b_pk": b_pk}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_create_expense_with_buddy_as_payer(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before"] = seen_before
        today = server_today()
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        driver.find_element(By.ID, "id_title").clear()
        driver.find_element(By.ID, "id_title").send_keys("Buddy Payer Expense")
        driver.find_element(By.ID, "id_value").clear()
        driver.find_element(By.ID, "id_value").send_keys("80.00")
        driver.execute_script(
            f"document.getElementById('id_date_due').value = '{today}';"
        )
        driver.find_element(By.ID, "buddy-payment-cb").click()
        time.sleep(0.5)
        # Set B (real buddy) as upfront payer
        driver.execute_script(
            f"var sel = document.getElementById('buddy-upfront-select');"
            f"sel.value = 'feuser:{ctx['b_pk']}';"
            f"sel.dispatchEvent(new Event('change', {{bubbles: true}}));"
        )
        time.sleep(0.4)
        driver.find_element(By.ID, "buddy-equal-btn").click()
        time.sleep(0.3)
        driver.find_element(By.CSS_SELECTOR,
            "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)").click()
        # The JS intercepts submit and shows a confirm dialog for feuser payer
        time.sleep(0.5)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(2)

    def test_redirected_to_expense_list(self, driver, w, ctx):
        # Feuser-as-payer expenses are saved on B's account and redirect to A's
        # expense list (not buddy summary); the expense appears on the summary page
        # because A is a participant in a buddy spending owned by B.
        assert "/budget/expenses/" in driver.current_url, \
            f"Expected redirect to /budget/expenses/, got: {driver.current_url}"

    def test_a_sees_needs_approval_on_summary(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Needs approval" in driver.page_source, \
            "A must see 'Needs approval' badge for the pending expense"
        assert "Buddy Payer Expense" in driver.page_source

    def test_b_receives_approval_email(self, driver, w, ctx):
        body = fetch_email(
            ctx["b"]["email"],
            "needs your approval",
            ignore_ids=ctx.get("seen_before"),
        )
        assert "Buddy Payer Expense" in body, \
            "Approval email must mention the expense title"

    def test_b_sees_needs_approval_on_summary(self, driver, w, ctx):
        from bhelpers import _login_as
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Needs approval" in driver.page_source, \
            "B (owning_feuser) must also see 'Needs approval' on their summary"
        assert "Buddy Payer Expense" in driver.page_source


# ---------------------------------------------------------------------------
# Regression: group-mode participant checkbox ignored when payer is non-me
# ---------------------------------------------------------------------------

class TestGroupModeParticipantCheckboxWithNonMePayer:
    """Checking a group participant checkbox must add them to the sliders
    even when a dummy member (not 'me') is selected as the upfront payer.

    Before the fix, syncParticipantsFromCheckboxes() short-circuited after
    adding 'me' and never read the checkboxes, so checking Jim had no effect.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        user = setup_user(driver, w, first_name="Bob", last_name="Builder")
        email = user["email"]
        group_id = _create_group(email, "Test Group Regression")
        thomas_id = _shell(
            f"from buddies.services import BuddyGroupService; "
            f"from feusers.models import FeUser; from buddies.models import BuddyGroup; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"g = BuddyGroup.objects.get(pk={group_id}); "
            f"d = BuddyGroupService.create_group_dummy(g, u, 'Thomas Payer'); "
            f"print(d.pk)"
        )
        jim_id = _shell(
            f"from buddies.services import BuddyGroupService; "
            f"from feusers.models import FeUser; from buddies.models import BuddyGroup; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"g = BuddyGroup.objects.get(pk={group_id}); "
            f"d = BuddyGroupService.create_group_dummy(g, u, 'Jim Participant'); "
            f"print(d.pk)"
        )
        yield {**user, "group_id": int(group_id), "thomas_id": int(thomas_id), "jim_id": int(jim_id)}
        cleanup_user(email)

    def test_open_new_expense_form(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        assert "This is a buddy payment" in driver.page_source

    def test_enable_buddy_checkbox(self, driver, w, ctx):
        driver.find_element(By.ID, "buddy-payment-cb").click()
        time.sleep(0.5)
        assert driver.find_element(By.ID, "buddy-payment-section").is_displayed()

    def test_switch_to_group_mode(self, driver, w, ctx):
        driver.find_element(By.ID, "buddy-mode-group").click()
        time.sleep(0.4)
        row = driver.find_element(By.ID, "buddy-group-select-row")
        assert row.is_displayed()

    def test_select_group(self, driver, w, ctx):
        driver.execute_script(
            f"var sel = document.getElementById('buddy-group-select');"
            f"sel.value = '{ctx['group_id']}';"
            f"sel.dispatchEvent(new Event('change', {{bubbles: true}}));"
        )
        time.sleep(0.5)
        # Participant checkboxes for group members should now be visible
        cbs = driver.find_elements(By.CSS_SELECTOR,
            "#buddy-participants-checkboxes .buddy-participant-cb")
        assert len(cbs) >= 2, "Expected at least Thomas and Jim as group member checkboxes"

    def test_select_thomas_as_upfront_payer(self, driver, w, ctx):
        driver.execute_script(
            f"var sel = document.getElementById('buddy-upfront-select');"
            f"sel.value = 'dummy:{ctx['thomas_id']}';"
            f"sel.dispatchEvent(new Event('change', {{bubbles: true}}));"
        )
        time.sleep(0.4)
        # Thomas's checkbox should be hidden; Jim's should still be visible
        thomas_lbl = driver.find_element(
            By.CSS_SELECTOR,
            f"#buddy-participants-checkboxes .buddy-participant-cb[data-id='{ctx['thomas_id']}']"
        )
        assert thomas_lbl.value_of_css_property("display") == "none", \
            "Payer Thomas must be hidden from the participant checkboxes"

    def test_check_jim_adds_him_to_sliders(self, driver, w, ctx):
        jim_lbl = driver.find_element(
            By.CSS_SELECTOR,
            f"#buddy-participants-checkboxes .buddy-participant-cb[data-id='{ctx['jim_id']}']"
        )
        jim_cb = jim_lbl.find_element(By.CSS_SELECTOR, "input[type=checkbox]")
        if jim_cb.is_selected():
            jim_cb.click()
            time.sleep(0.4)
        jim_cb.click()
        time.sleep(0.5)
        sliders = driver.find_elements(By.CSS_SELECTOR, "#buddy-sliders .buddy-slider-row")
        # Payer row + me row + Jim row = 3
        assert len(sliders) >= 3, (
            f"Expected at least 3 slider rows (payer + me + Jim) after checking Jim, "
            f"got {len(sliders)}. Regression: participant checkbox in group mode with "
            f"non-me payer was previously ignored."
        )

    def test_jim_slider_name_visible(self, driver, w, ctx):
        names = [el.text for el in
                 driver.find_elements(By.CSS_SELECTOR, "#buddy-sliders .buddy-slider-name")]
        assert any("Jim" in n for n in names), \
            f"Jim Participant must appear as a named slider row, got: {names}"

    def test_share_sum_is_100(self, driver, w, ctx):
        pct_els = driver.find_elements(By.CSS_SELECTOR, "#buddy-sliders .buddy-slider-pct")
        total = sum(float(el.text.rstrip("%")) for el in pct_els)
        assert abs(total - 100.0) < 0.2, \
            f"All slider shares must sum to 100%, got: {[el.text for el in pct_els]}"
