"""Buddies feature end-to-end tests.

Covers: dummy CRUD, actual buddy invite/accept/decline/revoke, buddy expense
creation via form, is_dummy visibility, kick flows with debt warnings, expense
approval, and dummy-to-actual merge.
"""
import subprocess
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import (
    _url, server_today,
    fetch_email, extract_link,
    api_get,
    setup_user, cleanup_user, browser_login, PASSWORD, DOCKER_WEB,
    SUBMIT_BTN,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _shell(code: str) -> str:
    """Run a Python snippet inside the container's Django shell."""
    r = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c", code],
        capture_output=True, text=True, timeout=20,
    )
    assert r.returncode == 0, f"Shell command failed:\n{r.stderr}\nCode: {code}"
    return r.stdout.strip()


def _login_as(driver, w, ctx_user: dict) -> None:
    """Clear the current browser session and log in as ctx_user.

    browser_login alone hangs when a user is already logged in because the
    login view redirects authenticated users away before the form renders.
    Clearing cookies first avoids this.
    """
    driver.delete_all_cookies()
    driver.execute_script("sessionStorage.clear(); localStorage.clear();")
    browser_login(driver, w, ctx_user["email"], PASSWORD)


def _create_buddy_link(email_a: str, email_b: str) -> str:
    """Create a BuddyLink between two users and return the link pk as a string."""
    return _shell(
        f"from feusers.models import FeUser; from buddies.models import BuddyLink; "
        f"a = FeUser.objects.get(email='{email_a}'); "
        f"b = FeUser.objects.get(email='{email_b}'); "
        f"lo, hi = sorted([a, b], key=lambda u: u.pk); "
        f"lnk, _ = BuddyLink.objects.get_or_create(user_a=lo, user_b=hi); "
        f"print(lnk.pk)"
    )


def _get_pk(email: str) -> str:
    """Return the pk of the FeUser with the given email."""
    return _shell(
        f"from feusers.models import FeUser; "
        f"print(FeUser.objects.get(email='{email}').pk)"
    )


# ---------------------------------------------------------------------------
# TestDummyBuddy: offline buddy CRUD + kick flows
# ---------------------------------------------------------------------------

class TestDummyBuddy:
    """Offline (dummy) buddy: add, display, kick without debt, kick with debt."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Diana", last_name="Dummy")
        yield c
        cleanup_user(c["email"])

    # --- Basic CRUD ---

    def test_add_dummy(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        inp = driver.find_element(By.CSS_SELECTOR, "input[name='display_name']")
        inp.clear()
        inp.send_keys("Offline Alice")
        driver.find_element(By.CSS_SELECTOR,
            "form[action*='add-dummy'] button[type=submit]").click()
        time.sleep(1)
        assert "Offline Alice" in driver.page_source, "Dummy name not shown after adding"
        assert "Offline buddy" in driver.page_source

    def test_onboarding_hint_hidden_with_buddy(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "How Buddies works:" not in driver.page_source

    def test_dummy_in_expense_form(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        assert "This is a buddy payment" in driver.page_source
        assert "Offline Alice" in driver.page_source

    def test_kick_dummy_no_debt(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        driver.find_element(By.CSS_SELECTOR,
            "form[action*='kick'] button[type=submit]").click()
        time.sleep(1)
        assert "Offline Alice" not in driver.page_source
        assert "/buddies/" in driver.current_url

    def test_onboarding_hint_visible_when_empty(self, driver, w, ctx):
        assert "How Buddies works:" in driver.page_source

    # --- Kick with debt warning ---

    def test_add_dummy_for_debt_test(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        inp = driver.find_element(By.CSS_SELECTOR, "input[name='display_name']")
        inp.clear()
        inp.send_keys("Debt Dummy")
        driver.find_element(By.CSS_SELECTOR,
            "form[action*='add-dummy'] button[type=submit]").click()
        time.sleep(1)
        assert "Debt Dummy" in driver.page_source
        email = ctx["email"]
        ctx["debt_dummy_id"] = int(_shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"print(DummyUser.objects.get(owning_feuser=u, display_name='Debt Dummy').pk)"
        ))

    def test_create_expense_with_dummy_participant(self, driver, w, ctx):
        email = ctx["email"]
        dummy_id = ctx["debt_dummy_id"]
        _shell(
            f"from budget.expense_factory import create_expense; "
            f"from feusers.models import FeUser; from budget.models import TransactionType; "
            f"from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"create_expense(owning_feuser=u, title='Debt Test Expense', "
            f"  type=TransactionType.EXPENSE, value=Decimal('100.00'), "
            f"  date_due=None, settled=False, "
            f"  buddy_spendings=[{{'type': 'dummy', 'id': {dummy_id}, 'share_percent': 50}}])"
        )

    def test_shared_expense_on_buddies_page(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Debt Test Expense" in driver.page_source, \
            "Expense with dummy participant must appear in Shared Expenses"

    def test_kick_dummy_with_debt_shows_warning(self, driver, w, ctx):
        dummy_id = ctx["debt_dummy_id"]
        driver.find_element(By.CSS_SELECTOR,
            f"form[action*='dummy/{dummy_id}/kick'] button[type=submit]").click()
        time.sleep(1)
        assert "Outstanding balance" in driver.page_source, \
            "Debt warning page must appear when kicking dummy with balance"
        assert "Remove anyway" in driver.page_source

    def test_kick_dummy_accept_debt_warning(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR, "button.btn-danger").click()
        time.sleep(1)
        assert "Debt Dummy" not in driver.page_source
        assert "/buddies/" in driver.current_url

    # --- is_dummy=True expense visibility ---

    def test_is_dummy_expense_not_in_expense_api(self, driver, w, ctx):
        email = ctx["email"]
        _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; from budget.models import Expense; "
            f"from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='PayerDummy'); "
            f"Expense.objects.create(owning_feuser=u, title='Hidden Payer Expense', "
            f"  type='expense', value=Decimal('50.00'), settled=False, "
            f"  is_dummy=True, upfront_payee_dummy=d)"
        )
        resp = api_get("/api/v1/expenses/", ctx, params={"q": "Hidden Payer Expense"})
        assert resp.status_code == 200
        assert not any(e["title"] == "Hidden Payer Expense"
                       for e in resp.json()["expenses"]), \
            "is_dummy=True expense must not appear in the expense list API"

    def test_is_dummy_expense_visible_on_buddies_page(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Hidden Payer Expense" in driver.page_source, \
            "is_dummy=True expense must appear in Shared Expenses on buddies page"
        assert "Offline payer" in driver.page_source


# ---------------------------------------------------------------------------
# TestActualBuddyInvite: send invite; B accepts via email link
# ---------------------------------------------------------------------------

class TestActualBuddyInvite:
    """Send a buddy invite by email; B views and accepts from the invite page."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Alice", last_name="Invite")
        b = setup_user(None, None, first_name="Bob", last_name="Invite")
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_a_sends_invite(self, driver, w, ctx):
        # Fixture already logged in A; navigate directly without re-logging in
        email_b = ctx["b"]["email"]
        driver.get(_url("/buddies/"))
        time.sleep(1)
        inp = driver.find_element(By.CSS_SELECTOR,
            "form[action*='invite-actual'] input[name='email']")
        inp.clear()
        inp.send_keys(email_b)
        driver.find_element(By.CSS_SELECTOR,
            "form[action*='invite-actual'] button[type=submit]").click()
        time.sleep(1)
        assert "Invitations you sent" in driver.page_source
        assert email_b in driver.page_source

    def test_invite_email_arrives(self, driver, w, ctx):
        email_b = ctx["b"]["email"]
        body = fetch_email(email_b, "invited you to be spending buddies")
        ctx["invite_link"] = extract_link(body)
        assert "/buddies/invite/" in ctx["invite_link"]

    def test_b_sees_invite_on_buddies_page(self, driver, w, ctx):
        email_a = ctx["a"]["email"]
        _login_as(driver, w, ctx["b"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Waiting for your response" in driver.page_source
        assert email_a in driver.page_source

    def test_b_accepts_via_invite_link(self, driver, w, ctx):
        # B is already logged in from the previous test
        email_a = ctx["a"]["email"]
        driver.get(ctx["invite_link"])
        time.sleep(1)
        assert "invited you to be spending buddies" in driver.page_source
        driver.find_element(By.CSS_SELECTOR,
            "form[action*='accept'] button[type=submit]").click()
        time.sleep(1)
        assert "/buddies/" in driver.current_url
        assert email_a in driver.page_source

    def test_a_sees_b_as_buddy(self, driver, w, ctx):
        email_b = ctx["b"]["email"]
        _login_as(driver, w, ctx["a"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert email_b in driver.page_source
        assert "My Buddies" in driver.page_source


# ---------------------------------------------------------------------------
# TestInviteDeclineRevoke: decline and revoke flows
# ---------------------------------------------------------------------------

class TestInviteDeclineRevoke:
    """B declines an invite; A then sends another and revokes it."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Alice", last_name="Revoke")
        b = setup_user(None, None, first_name="Bob", last_name="Revoke")
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def _a_sends_invite(self, driver, w, ctx):
        """Log in as A and send invite to B; leaves browser on A's buddies page."""
        email_b = ctx["b"]["email"]
        _login_as(driver, w, ctx["a"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        inp = driver.find_element(By.CSS_SELECTOR,
            "form[action*='invite-actual'] input[name='email']")
        inp.clear()
        inp.send_keys(email_b)
        driver.find_element(By.CSS_SELECTOR,
            "form[action*='invite-actual'] button[type=submit]").click()
        time.sleep(1)
        assert email_b in driver.page_source

    def test_b_declines_invite(self, driver, w, ctx):
        email_a = ctx["a"]["email"]
        self._a_sends_invite(driver, w, ctx)
        _login_as(driver, w, ctx["b"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Waiting for your response" in driver.page_source
        driver.find_element(By.CSS_SELECTOR,
            "form[action*='decline'] button[type=submit]").click()
        time.sleep(1)
        assert "Waiting for your response" not in driver.page_source
        assert email_a not in driver.page_source

    def test_a_revokes_invite(self, driver, w, ctx):
        self._a_sends_invite(driver, w, ctx)
        # Already on A's buddies page showing the pending invite
        driver.find_element(By.CSS_SELECTOR,
            "form[action*='revoke'] button[type=submit]").click()
        time.sleep(1)
        assert "Invitations you sent" not in driver.page_source


# ---------------------------------------------------------------------------
# TestBuddyExpenseForm: create expense with buddy sharing via the expense form
# ---------------------------------------------------------------------------

class TestBuddyExpenseForm:
    """Expense form: buddy payment section, dummy participant, equal shares."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Eve", last_name="Form")
        email = c["email"]
        # Pre-create a dummy so the buddy payment section appears
        _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"DummyUser.objects.create(owning_feuser=u, display_name='Form Buddy')"
        )
        yield c
        cleanup_user(c["email"])

    def test_buddy_section_visible(self, driver, w, ctx):
        # Fixture already logged in Eve; navigate directly
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        assert "This is a buddy payment" in driver.page_source
        assert "Form Buddy" in driver.page_source

    def test_create_expense_with_dummy_participant(self, driver, w, ctx):
        today = server_today()
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)

        driver.find_element(By.ID, "id_title").clear()
        driver.find_element(By.ID, "id_title").send_keys("Form Buddy Expense")
        driver.find_element(By.ID, "id_value").clear()
        driver.find_element(By.ID, "id_value").send_keys("80.00")
        driver.execute_script(
            f"document.getElementById('id_date_due').value = '{today}';"
            "document.getElementById('id_settled').checked = true;"
        )

        # Enable buddy payment section
        driver.find_element(By.ID, "buddy-payment-cb").click()
        time.sleep(0.5)

        # Check the first participant checkbox
        labels = driver.find_elements(By.CSS_SELECTOR, ".buddy-participant-cb")
        assert len(labels) > 0, "No participant checkboxes shown"
        labels[0].find_element(By.CSS_SELECTOR, "input").click()
        time.sleep(0.3)

        # Equal shares and verify sum
        driver.find_element(By.ID, "buddy-equal-btn").click()
        time.sleep(0.3)
        sum_el = driver.find_element(By.ID, "buddy-share-sum")
        assert "100.0%" in sum_el.text, f"Expected 100% sum, got: {sum_el.text}"

        driver.find_element(By.CSS_SELECTOR, SUBMIT_BTN).click()
        time.sleep(2)
        assert "/budget/expenses/" in driver.current_url

    def test_shared_expense_on_buddies_page(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Form Buddy Expense" in driver.page_source

    def test_expense_in_api_list(self, driver, w, ctx):
        # is_dummy=False (me paid, dummy is participant) -> visible in API
        resp = api_get("/api/v1/expenses/", ctx, params={"q": "Form Buddy Expense"})
        assert resp.status_code == 200
        exps = resp.json()["expenses"]
        assert any(e["title"] == "Form Buddy Expense" for e in exps), \
            "Expense with dummy participant must appear in expense API"

    def test_re_edit_buddy_expense_sliders_interactive(self, driver, w, ctx):
        """Re-editing an existing buddy expense: sliders must be interactive.

        Regression test for the |safe bug: existing_spendings_json was rendered
        without |safe, so Django HTML-escaped the quotes to &quot;, producing
        broken JavaScript inside the <script> block and making the entire buddy
        section non-interactive on re-edit.
        """
        # Find the expense created by the previous test and navigate to edit it
        resp = api_get("/api/v1/expenses/", ctx, params={"q": "Form Buddy Expense"})
        exp_uid = resp.json()["expenses"][0]["id"]
        driver.get(_url(f"/budget/expenses/{exp_uid}/edit/"))
        time.sleep(1)

        # The buddy-payment section must already be visible (is_buddy_expense=True)
        assert "This is a buddy payment" in driver.page_source
        cb = driver.find_element(By.ID, "buddy-payment-cb")
        assert cb.get_attribute("checked") is not None, \
            "buddy-payment-cb must be pre-checked when editing a buddy expense"

        # The slider for the participant must be rendered and show a percentage
        pct_els = driver.find_elements(By.CSS_SELECTOR, "#buddy-sliders .buddy-slider-pct")
        assert len(pct_els) >= 2, "Expected at least payer row + participant row"

        # Use JS to move the slider to 30% and verify the display updates
        participant_slider = driver.find_element(By.CSS_SELECTOR,
            "#buddy-sliders input[type=range]:not([disabled])")
        driver.execute_script(
            "var s = arguments[0]; s.value = 30;"
            "s.dispatchEvent(new Event('input', {bubbles: true}));",
            participant_slider,
        )
        time.sleep(0.3)
        # The participant's percentage label must now reflect 30%
        pct_els = driver.find_elements(By.CSS_SELECTOR, "#buddy-sliders .buddy-slider-pct")
        participant_pct = pct_els[-1].text  # last entry is the participant
        assert "30.0%" in participant_pct, \
            f"Slider did not update: expected 30.0%, got '{participant_pct}'"

    def test_equal_shares_gives_50_50(self, driver, w, ctx):
        """Equal shares with one participant must give 50/50 split."""
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        driver.find_element(By.ID, "buddy-payment-cb").click()
        time.sleep(0.5)
        labels = driver.find_elements(By.CSS_SELECTOR, ".buddy-participant-cb")
        labels[0].find_element(By.CSS_SELECTOR, "input").click()
        time.sleep(0.3)
        driver.find_element(By.ID, "buddy-equal-btn").click()
        time.sleep(0.3)
        pct_els = driver.find_elements(By.CSS_SELECTOR, "#buddy-sliders .buddy-slider-pct")
        assert len(pct_els) == 2  # payer row + participant row
        assert all("50.0%" in el.text for el in pct_els)


# ---------------------------------------------------------------------------
# TestActualBuddyKick: kick actual buddy, with and without outstanding debt
# ---------------------------------------------------------------------------

class TestActualBuddyKick:
    """Kick an actual buddy: immediate (no debt) and via warning page (with debt)."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Kira", last_name="Kicker")
        b = setup_user(None, None, first_name="Victor", last_name="Kicked")
        _create_buddy_link(a["email"], b["email"])
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_buddy_visible_before_kick(self, driver, w, ctx):
        email_b = ctx["b"]["email"]
        # Fixture logged in Kira; navigate directly
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert email_b in driver.page_source
        assert "My Buddies" in driver.page_source

    def test_kick_buddy_no_debt_immediate(self, driver, w, ctx):
        email_b = ctx["b"]["email"]
        driver.find_element(By.CSS_SELECTOR,
            ".buddy-card:not(.buddy-card-dummy) form[action*='kick'] button[type=submit]"
        ).click()
        time.sleep(1)
        assert "/buddies/" in driver.current_url
        assert email_b not in driver.page_source

    def test_restore_link_and_add_debt(self, driver, w, ctx):
        email_a = ctx["a"]["email"]
        email_b = ctx["b"]["email"]
        _create_buddy_link(email_a, email_b)
        b_pk = _get_pk(email_b)
        _shell(
            f"from budget.expense_factory import create_expense; "
            f"from feusers.models import FeUser; from budget.models import TransactionType; "
            f"from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{email_a}'); "
            f"create_expense(owning_feuser=u, title='Kick Debt Exp', "
            f"  type=TransactionType.EXPENSE, value=Decimal('200.00'), "
            f"  date_due=None, settled=False, "
            f"  buddy_spendings=[{{'type': 'feuser', 'id': {b_pk}, 'share_percent': 50}}])"
        )

    def test_kick_with_debt_shows_warning(self, driver, w, ctx):
        # Reload A's buddies page (Kira is still the logged-in user)
        driver.get(_url("/buddies/"))
        time.sleep(1)
        driver.find_element(By.CSS_SELECTOR,
            ".buddy-card:not(.buddy-card-dummy) form[action*='kick'] button[type=submit]"
        ).click()
        time.sleep(1)
        assert "Outstanding balance" in driver.page_source
        assert "Remove anyway" in driver.page_source

    def test_kick_accept_debt_warning(self, driver, w, ctx):
        email_b = ctx["b"]["email"]
        driver.find_element(By.CSS_SELECTOR, "button.btn-danger").click()
        time.sleep(2)
        assert email_b not in driver.page_source
        assert "/buddies/" in driver.current_url

    def test_kicked_b_has_dummy_for_a(self, driver, w, ctx):
        # After kick, Victor gets a dummy representing Kira on his account
        _login_as(driver, w, ctx["b"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Offline buddy" in driver.page_source

    def test_kicked_b_has_cloned_expense(self, driver, w, ctx):
        # B's buddies page also shows the cloned expense (is_dummy=True, offline payer)
        assert "Kick Debt Exp" in driver.page_source


# ---------------------------------------------------------------------------
# TestExpenseApproval: B approves an expense A created with B as upfront payer
# ---------------------------------------------------------------------------

class TestExpenseApproval:
    """B sees 'Needs approval' badge; B approves from the buddies page."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Anna", last_name="Approver")
        b = setup_user(None, None, first_name="Ben", last_name="Approver")
        _create_buddy_link(a["email"], b["email"])
        email_a = a["email"]
        email_b = b["email"]
        a_pk = _get_pk(email_a)
        # Create expense owned by B, buddy_approved=False, A is a participant
        _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import BuddySpending; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"b = FeUser.objects.get(email='{email_b}'); "
            f"e = Expense.objects.create(owning_feuser=b, title='Approval Expense', "
            f"  type='expense', value=Decimal('60.00'), settled=False, buddy_approved=False); "
            f"BuddySpending.objects.create(expense=e, participant_feuser_id={a_pk}, "
            f"  share_percent=Decimal('50.0'))"
        )
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_b_sees_needs_approval_badge(self, driver, w, ctx):
        _login_as(driver, w, ctx["b"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Needs approval" in driver.page_source
        assert "Approval Expense" in driver.page_source

    def test_b_approves_expense(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR,
            ".bexp-actions form[action*='approve'] button[type=submit]").click()
        time.sleep(1)
        assert "/budget/expenses/" in driver.current_url

    def test_badge_gone_after_approval(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Needs approval" not in driver.page_source
        assert "Approval Expense" in driver.page_source


# ---------------------------------------------------------------------------
# TestExpenseRejection: B rejects an expense A created with B as upfront payer
# ---------------------------------------------------------------------------

class TestExpenseRejection:
    """B sees 'Needs approval' badge; B rejects; expense is deleted from B's account."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Rex", last_name="Rejecter")
        b = setup_user(None, None, first_name="Belle", last_name="Rejecter")
        _create_buddy_link(a["email"], b["email"])
        email_a = a["email"]
        email_b = b["email"]
        a_pk = _get_pk(email_a)
        # Create expense owned by B with buddy_approved=False; A is a participant.
        # This mirrors what happens when A sets B as the upfront payer.
        _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import BuddySpending; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"b = FeUser.objects.get(email='{email_b}'); "
            f"e = Expense.objects.create(owning_feuser=b, title='Rejection Expense', "
            f"  type='expense', value=Decimal('40.00'), settled=False, buddy_approved=False); "
            f"BuddySpending.objects.create(expense=e, participant_feuser_id={a_pk}, "
            f"  share_percent=Decimal('50.0'))"
        )
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_b_sees_needs_approval_badge(self, driver, w, ctx):
        _login_as(driver, w, ctx["b"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Needs approval" in driver.page_source
        assert "Rejection Expense" in driver.page_source

    def test_b_rejects_expense(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR,
            ".bexp-actions form[action*='reject'] button[type=submit]").click()
        time.sleep(1)
        assert "/budget/expenses/" in driver.current_url

    def test_expense_gone_from_buddies_page(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Rejection Expense" not in driver.page_source


# ---------------------------------------------------------------------------
# TestDummyMerge: A has dummy for B; B accepts merge invite; history transfers
# ---------------------------------------------------------------------------

class TestDummyMerge:
    """Dummy-to-actual merge: expense history transferred, buddy link created."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Mia", last_name="Merger")
        b = setup_user(None, None, first_name="Neil", last_name="Merger")
        email_a = a["email"]
        # Create dummy owned by A representing B
        dummy_pk = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{email_a}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Merge Test Buddy'); "
            f"print(d.pk)"
        )
        # Create expense with dummy as participant so there is history to transfer
        _shell(
            f"from budget.expense_factory import create_expense; "
            f"from feusers.models import FeUser; from budget.models import TransactionType; "
            f"from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{email_a}'); "
            f"create_expense(owning_feuser=u, title='Merge History Expense', "
            f"  type=TransactionType.EXPENSE, value=Decimal('90.00'), "
            f"  date_due=None, settled=False, "
            f"  buddy_spendings=[{{'type': 'dummy', 'id': {dummy_pk}, 'share_percent': 50}}])"
        )
        yield {"a": a, "b": b, "dummy_pk": int(dummy_pk)}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_a_sees_dummy_and_merge_button(self, driver, w, ctx):
        # Fixture already logged in Mia; navigate directly
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Merge Test Buddy" in driver.page_source
        assert "Invite to merge" in driver.page_source

    def test_a_sends_merge_invite(self, driver, w, ctx):
        email_b = ctx["b"]["email"]
        dummy_pk = ctx["dummy_pk"]
        # Reveal the inline email form via the onclick button
        driver.execute_script(
            "document.querySelector('.buddy-card-dummy .buddy-card-actions "
            "button.btn-secondary').click();"
        )
        time.sleep(0.4)
        merge_form = driver.find_element(By.CSS_SELECTOR,
            f"form[action*='dummy/{dummy_pk}/send-merge']")
        email_inp = merge_form.find_element(By.CSS_SELECTOR, "input[name='email']")
        email_inp.clear()
        email_inp.send_keys(email_b)
        merge_form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        time.sleep(1)

    def test_merge_email_arrives(self, driver, w, ctx):
        email_b = ctx["b"]["email"]
        body = fetch_email(email_b, "link your account with their buddy record")
        ctx["merge_link"] = extract_link(body)
        assert "/buddies/merge/" in ctx["merge_link"]

    def test_b_sees_merge_invitation(self, driver, w, ctx):
        _login_as(driver, w, ctx["b"])
        driver.get(ctx["merge_link"])
        time.sleep(1)
        assert "Merge Test Buddy" in driver.page_source
        assert "Accept and merge" in driver.page_source

    def test_b_accepts_merge(self, driver, w, ctx):
        email_a = ctx["a"]["email"]
        driver.find_element(By.CSS_SELECTOR,
            "form[action*='accept'] button[type=submit]").click()
        time.sleep(1)
        assert "/buddies/" in driver.current_url
        assert email_a in driver.page_source

    def test_merge_history_visible_for_b(self, driver, w, ctx):
        # Shared expense history (BuddySpending) was transferred to B
        assert "Merge History Expense" in driver.page_source

    def test_a_sees_b_as_actual_buddy(self, driver, w, ctx):
        email_b = ctx["b"]["email"]
        _login_as(driver, w, ctx["a"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Merge Test Buddy" not in driver.page_source
        assert email_b in driver.page_source
        assert "My Buddies" in driver.page_source
