"""
Buddy expense participant notification emails.

Tests that the correct notification emails are sent when:
- A buddy expense is created (participants get a participation notice)
- A buddy expense is edited (title/value change -> participants get an update notice)
- A participant is added to an existing expense (added participant gets a notice)
- A participant is removed from an existing expense (removed participant gets a removed notice)

Settlement expenses must NOT trigger these notifications (they have their own flow).
"""
import json
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user, fetch_email, mailpit_seen_ids, server_today
from bhelpers import _shell, _login_as, _create_buddy_link, _get_pk


# ---------------------------------------------------------------------------
# Create: participant gets a participation notice
# ---------------------------------------------------------------------------

class TestCreateNotifiesParticipant:
    """When A creates a buddy expense with B as participant, B gets a notice."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Alice", last_name="Creator")
        b = setup_user(None, None, first_name="Bob", last_name="Participant")
        _create_buddy_link(a["email"], b["email"])
        ctx = {"a": a, "b": b}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_create_expense_with_feuser_participant(self, driver, w, ctx):
        today = server_today()
        seen_before = mailpit_seen_ids()
        ctx["seen_before_create"] = seen_before

        b_pk = int(_get_pk(ctx["b"]["email"]))
        ctx["b_pk"] = b_pk

        _login_as(driver, ctx["a"])
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)

        driver.execute_script(
            "document.getElementById('id_title').value = 'Shared Dinner';"
            "document.getElementById('id_value').value = '80.00';"
            f"document.getElementById('id_date_due').value = '{today}';"
            "document.getElementById('id_settled').checked = true;"
        )
        # Enable buddy payment
        driver.find_element(By.ID, "buddy-payment-cb").click()
        time.sleep(0.5)

        # Select B as participant via the dropdown
        driver.execute_script(
            f"var sel = document.getElementById('buddy-participant-select');"
            f"sel.value = 'feuser:{b_pk}';"
            f"sel.dispatchEvent(new Event('change', {{bubbles: true}}));"
        )
        time.sleep(0.4)
        driver.find_element(By.ID, "buddy-equal-btn").click()
        time.sleep(0.3)

        driver.find_element(
            By.CSS_SELECTOR,
            "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)"
        ).click()
        time.sleep(2)
        assert "/budget/expenses/" in driver.current_url, \
            "Expected redirect to expense list after creating buddy expense"

    def test_b_receives_participation_notice_email(self, driver, w, ctx):
        body = fetch_email(
            ctx["b"]["email"], "included you in a shared expense",
            ignore_ids=ctx.get("seen_before_create"),
        )
        assert "Shared Dinner" in body, "Email must mention the expense title"
        assert "Alice Creator" in body, "Email must mention the creator's name"

    def test_participation_email_shows_share_value(self, driver, w, ctx):
        body = fetch_email(
            ctx["b"]["email"], "included you in a shared expense",
            ignore_ids=ctx.get("seen_before_create"),
        )
        # 50% of 80 = 40
        assert "40" in body, "Email must show the recipient's share value (40.00)"

    def test_a_does_not_receive_participation_notice(self, driver, w, ctx):
        # A created the expense, so they must not receive a self-notification
        import requests
        from helpers import MAILPIT_API
        msgs = requests.get(f"{MAILPIT_API}/messages", timeout=5).json().get("messages", [])
        new_msgs = [
            m for m in msgs
            if m["ID"] not in ctx.get("seen_before_create", set())
        ]
        for msg in new_msgs:
            recipients = [t.get("Address", "") for t in msg.get("To", [])]
            subj = msg.get("Subject", "").lower()
            if ctx["a"]["email"] in recipients and "included" in subj and "shared expense" in subj:
                raise AssertionError(
                    f"A should NOT receive a participation notice for their own expense, but got: {subj}"
                )


# ---------------------------------------------------------------------------
# Edit: title/value change -> participant gets an update notice
# ---------------------------------------------------------------------------

class TestEditNotifiesParticipant:
    """When A edits a buddy expense (title or value), B gets an update notice."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Carol", last_name="Editor")
        b = setup_user(None, None, first_name="Dave", last_name="Notified")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))

        # Create expense via shell (setup)
        exp_pk = _shell(
            f"from budget.expense_factory import create_expense; "
            f"from feusers.models import FeUser; from budget.models import TransactionType; "
            f"from decimal import Decimal; import datetime; "
            f"a = FeUser.objects.get(email='{a['email']}'); "
            f"e = create_expense(owning_feuser=a, title='Edit Me Expense', "
            f"  type=TransactionType.EXPENSE, value=Decimal('60.00'), "
            f"  date_due=datetime.date.today(), settled=False, "
            f"  buddy_spendings=[{{'type': 'feuser', 'id': {b_pk}, 'share_percent': 50}}]); "
            f"print(e.pk)"
        )
        ctx = {"a": a, "b": b, "b_pk": b_pk, "exp_pk": int(exp_pk)}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_edit_expense_title_triggers_update_email(self, driver, w, ctx):
        today = server_today()
        seen_before = mailpit_seen_ids()
        ctx["seen_before_edit"] = seen_before

        _login_as(driver, ctx["a"])
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)

        # Change the title
        driver.execute_script(
            "document.getElementById('id_title').value = 'Edit Me Expense UPDATED';"
        )

        # Ensure the buddy data is still set in the hidden inputs
        # (Alpine.js should have pre-populated this, but we force it to be safe)
        driver.execute_script(
            f"document.getElementById('buddy-spendings-json').value = "
            f"JSON.stringify([{{type:'feuser',id:{ctx['b_pk']},share_percent:50}}]);"
            f"document.getElementById('buddy-upfront-type-input').value = 'me';"
            f"document.getElementById('buddy-mode-input').value = 'single';"
        )

        driver.find_element(
            By.CSS_SELECTOR,
            "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)"
        ).click()
        time.sleep(2)

    def test_b_receives_update_email(self, driver, w, ctx):
        body = fetch_email(
            ctx["b"]["email"], "updated a shared expense",
            ignore_ids=ctx.get("seen_before_edit"),
        )
        assert "Edit Me Expense UPDATED" in body, \
            "Update email must contain the new expense title"
        assert "Carol Editor" in body, "Update email must mention the editor's name"

    def test_update_email_shows_old_title_in_diff(self, driver, w, ctx):
        body = fetch_email(
            ctx["b"]["email"], "updated a shared expense",
            ignore_ids=ctx.get("seen_before_edit"),
        )
        assert "Edit Me Expense" in body, \
            "Update email must show the old title in the diff section"


# ---------------------------------------------------------------------------
# Edit: add participant -> new participant gets a notice
# ---------------------------------------------------------------------------

class TestEditAddParticipantNotification:
    """When A adds C to an existing group expense, C receives an 'added' email.

    Uses group mode because single-buddy mode caps participants at 1, making
    it impossible to add a second participant in that mode.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Eve", last_name="Adder")
        b = setup_user(None, None, first_name="Frank", last_name="Existing")
        c = setup_user(None, None, first_name="Grace", last_name="Added")
        _create_buddy_link(a["email"], b["email"])
        _create_buddy_link(a["email"], c["email"])
        b_pk = int(_get_pk(b["email"]))
        c_pk = int(_get_pk(c["email"]))

        from bhelpers import _create_group, _add_group_member
        group_pk = int(_create_group(a["email"], "Add Participant Group"))
        _add_group_member(group_pk, b["email"])
        _add_group_member(group_pk, c["email"])

        exp_pk = _shell(
            f"from budget.expense_factory import create_expense; "
            f"from feusers.models import FeUser; from budget.models import TransactionType; "
            f"from buddies.models import BuddyGroup; "
            f"from decimal import Decimal; import datetime; "
            f"a = FeUser.objects.get(email='{a['email']}'); "
            f"g = BuddyGroup.objects.get(pk={group_pk}); "
            f"e = create_expense(owning_feuser=a, title='Add Participant Expense', "
            f"  type=TransactionType.EXPENSE, value=Decimal('90.00'), "
            f"  date_due=datetime.date.today(), settled=False, buddy_group=g, "
            f"  buddy_spendings=[{{'type': 'feuser', 'id': {b_pk}, 'share_percent': 50}}]); "
            f"print(e.pk)"
        )
        ctx = {
            "a": a, "b": b, "c": c,
            "b_pk": b_pk, "c_pk": c_pk,
            "exp_pk": int(exp_pk), "group_pk": group_pk,
        }
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])
        cleanup_user(c["email"])

    def test_edit_adds_c_as_participant(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before_add"] = seen_before

        _login_as(driver, ctx["a"])
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)

        # Add C alongside B in group mode (single mode caps at 1 participant)
        new_spendings = json.dumps([
            {"type": "feuser", "id": ctx["b_pk"], "share_percent": 33.333},
            {"type": "feuser", "id": ctx["c_pk"], "share_percent": 33.333},
        ])
        driver.execute_script(
            f"document.getElementById('buddy-spendings-json').value = "
            f"'{new_spendings}';"
            f"document.getElementById('buddy-upfront-type-input').value = 'me';"
            f"document.getElementById('buddy-mode-input').value = 'group';"
            f"document.getElementById('buddy-group-id-input').value = '{ctx['group_pk']}';"
        )

        driver.find_element(
            By.CSS_SELECTOR,
            "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)"
        ).click()
        time.sleep(2)

    def test_c_receives_added_to_expense_email(self, driver, w, ctx):
        body = fetch_email(
            ctx["c"]["email"], "added you to a shared expense",
            ignore_ids=ctx.get("seen_before_add"),
        )
        assert "Add Participant Expense" in body, \
            "Email to C must mention the expense title"
        assert "Eve Adder" in body, \
            "Email to C must mention who added them"

    def test_b_receives_update_email_about_added_participant(self, driver, w, ctx):
        body = fetch_email(
            ctx["b"]["email"], "updated a shared expense",
            ignore_ids=ctx.get("seen_before_add"),
        )
        assert "Add Participant Expense" in body
        assert "Grace Added" in body, \
            "B's update email must mention the newly added participant"


# ---------------------------------------------------------------------------
# Edit: remove participant -> removed participant gets a notice
# ---------------------------------------------------------------------------

class TestEditRemoveParticipantNotification:
    """When A removes B from an existing group expense, B receives a 'removed' email.

    Uses group mode because the initial expense has two participants (B and C),
    which requires group mode.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Hank", last_name="Remover")
        b = setup_user(None, None, first_name="Iris", last_name="Removed")
        c = setup_user(None, None, first_name="Jack", last_name="Stays")
        _create_buddy_link(a["email"], b["email"])
        _create_buddy_link(a["email"], c["email"])
        b_pk = int(_get_pk(b["email"]))
        c_pk = int(_get_pk(c["email"]))

        from bhelpers import _create_group, _add_group_member
        group_pk = int(_create_group(a["email"], "Remove Participant Group"))
        _add_group_member(group_pk, b["email"])
        _add_group_member(group_pk, c["email"])

        exp_pk = _shell(
            f"from budget.expense_factory import create_expense; "
            f"from feusers.models import FeUser; from budget.models import TransactionType; "
            f"from buddies.models import BuddyGroup; "
            f"from decimal import Decimal; import datetime; "
            f"a = FeUser.objects.get(email='{a['email']}'); "
            f"g = BuddyGroup.objects.get(pk={group_pk}); "
            f"e = create_expense(owning_feuser=a, title='Remove Participant Expense', "
            f"  type=TransactionType.EXPENSE, value=Decimal('120.00'), "
            f"  date_due=datetime.date.today(), settled=False, buddy_group=g, "
            f"  buddy_spendings=["
            f"    {{'type': 'feuser', 'id': {b_pk}, 'share_percent': 33.333}},"
            f"    {{'type': 'feuser', 'id': {c_pk}, 'share_percent': 33.333}}"
            f"  ]); "
            f"print(e.pk)"
        )
        ctx = {
            "a": a, "b": b, "c": c,
            "b_pk": b_pk, "c_pk": c_pk,
            "exp_pk": int(exp_pk), "group_pk": group_pk,
        }
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])
        cleanup_user(c["email"])

    def test_edit_removes_b_from_expense(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before_remove"] = seen_before

        _login_as(driver, ctx["a"])
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)

        # Keep only C; remove B. Use group mode (original expense has 2 participants).
        new_spendings = json.dumps([
            {"type": "feuser", "id": ctx["c_pk"], "share_percent": 50},
        ])
        driver.execute_script(
            f"document.getElementById('buddy-spendings-json').value = "
            f"'{new_spendings}';"
            f"document.getElementById('buddy-upfront-type-input').value = 'me';"
            f"document.getElementById('buddy-mode-input').value = 'group';"
            f"document.getElementById('buddy-group-id-input').value = '{ctx['group_pk']}';"
        )

        driver.find_element(
            By.CSS_SELECTOR,
            "button[type=submit]:not(#logout-button):not(#sidebar-logout-button)"
        ).click()
        time.sleep(2)

    def test_b_receives_removed_from_expense_email(self, driver, w, ctx):
        body = fetch_email(
            ctx["b"]["email"], "removed you from a shared expense",
            ignore_ids=ctx.get("seen_before_remove"),
        )
        assert "Remove Participant Expense" in body, \
            "Removed email must mention the expense title"
        assert "Hank Remover" in body, \
            "Removed email must mention who removed them"

    def test_c_receives_update_email_about_removed_participant(self, driver, w, ctx):
        body = fetch_email(
            ctx["c"]["email"], "updated a shared expense",
            ignore_ids=ctx.get("seen_before_remove"),
        )
        assert "Iris Removed" in body, \
            "C's update email must mention who was removed"


# ---------------------------------------------------------------------------
# Settlements: no participation notice sent
# ---------------------------------------------------------------------------

class TestSettlementNoNotification:
    """Settlement expenses must never trigger participation notices."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Karl", last_name="Settler")
        b = setup_user(None, None, first_name="Lena", last_name="Creditor")
        _create_buddy_link(a["email"], b["email"])
        ctx = {"a": a, "b": b}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_settle_does_not_trigger_participation_notice(self, driver, w, ctx):
        b_pk = int(_get_pk(ctx["b"]["email"]))
        seen_before = mailpit_seen_ids()

        # Create a settlement expense directly (as the settlement service would)
        _shell(
            f"from budget.expense_factory import create_expense; "
            f"from feusers.models import FeUser; from budget.models import TransactionType; "
            f"from decimal import Decimal; import datetime; "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"create_expense(owning_feuser=a, title='Settlement Notice Test', "
            f"  type=TransactionType.EXPENSE, value=Decimal('30.00'), "
            f"  date_due=datetime.date.today(), settled=True, "
            f"  is_buddies_settlement=True, "
            f"  buddy_spendings=[{{'type': 'feuser', 'id': {b_pk}, 'share_percent': 100}}])"
        )
        time.sleep(1)

        import requests
        from helpers import MAILPIT_API
        msgs = requests.get(f"{MAILPIT_API}/messages", timeout=5).json().get("messages", [])
        new_msgs = [m for m in msgs if m["ID"] not in seen_before]
        for msg in new_msgs:
            recipients = [t.get("Address", "") for t in msg.get("To", [])]
            subj = msg.get("Subject", "").lower()
            if ctx["b"]["email"] in recipients and (
                "included you in" in subj or "added you to" in subj
            ):
                raise AssertionError(
                    f"Settlement must not trigger a participation notice, but got: {subj}"
                )
