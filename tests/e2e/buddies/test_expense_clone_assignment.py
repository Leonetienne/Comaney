"""
Expense clone preserves buddy assignment and sends notifications.

Tests:
1. Cloning a direct-buddy expense copies BuddySpending rows to the clone.
2. Participant receives a "included you in a shared expense" email after clone.
3. Cloning a project expense copies the project FK and BuddySpending rows.
4. Project participant receives notification after clone.
"""
import time

import pytest
import requests

from helpers import _url, setup_user, cleanup_user, fetch_email, mailpit_seen_ids, MAILPIT_API
from bhelpers import _shell, _login_as, _create_buddy_link, _get_pk, _create_group, _add_group_member


# ---------------------------------------------------------------------------
# Direct buddy expense: clone preserves spendings and notifies participant
# ---------------------------------------------------------------------------

class TestCloneDirectBuddyExpense:
    """Cloning a direct buddy expense copies BuddySpending rows and notifies B."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Ana", last_name="CloneOwner")
        b = setup_user(None, None, first_name="Ben", last_name="CloneParticipant")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))

        # Create a buddy expense via shell (no notifications yet for setup)
        exp_pk = _shell(
            f"from budget.models import Expense, TransactionType; "
            f"from buddies.models import BuddySpending; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"a = FeUser.objects.get(email='{a['email']}'); "
            f"b = FeUser.objects.get(email='{b['email']}'); "
            f"e = Expense.objects.create(owning_feuser=a, title='Original Buddy Expense', "
            f"  type=TransactionType.EXPENSE, value=Decimal('100.00'), settled=False, "
            f"  buddy_approved=True); "
            f"BuddySpending.objects.create(expense=e, participant_feuser=b, "
            f"  share_percent=Decimal('50.00')); "
            f"print(e.pk)"
        )
        ctx = {"a": a, "b": b, "b_pk": b_pk, "exp_pk": int(exp_pk)}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_clone_copies_buddy_spendings(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before_clone"] = seen_before

        _login_as(driver, ctx["a"])
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/clone/"))
        time.sleep(2)

        import re
        m = re.search(r'/expenses/(\d+)/edit/', driver.current_url)
        assert m, "Clone should redirect to the edit page of the new expense"
        ctx["clone_pk"] = int(m.group(1))

        count = _shell(
            f"from buddies.models import BuddySpending; "
            f"print(BuddySpending.objects.filter(expense_id={ctx['clone_pk']}).count())"
        )
        assert count == "1", (
            f"Clone must have 1 BuddySpending row, got {count}"
        )

    def test_clone_spendings_match_original(self, driver, w, ctx):
        share = _shell(
            f"from buddies.models import BuddySpending; "
            f"bs = BuddySpending.objects.get(expense_id={ctx['clone_pk']}); "
            f"print(bs.share_percent)"
        )
        assert share == "50.00", f"Cloned share_percent should be 50.00, got {share}"

        participant_email = _shell(
            f"from buddies.models import BuddySpending; "
            f"bs = BuddySpending.objects.get(expense_id={ctx['clone_pk']}); "
            f"print(bs.participant_feuser.email)"
        )
        assert participant_email == ctx["b"]["email"], (
            "Cloned BuddySpending must point to the original participant"
        )

    def test_participant_notified_after_clone(self, driver, w, ctx):
        body = fetch_email(
            ctx["b"]["email"], "included you in a shared expense",
            ignore_ids=ctx.get("seen_before_clone"),
        )
        assert "Original Buddy Expense" in body or "CLONE" in body, (
            "Notification email must mention the cloned expense title"
        )
        assert "Ana CloneOwner" in body, "Email must mention the creator's name"

    def test_owner_does_not_receive_self_notification(self, driver, w, ctx):
        msgs = requests.get(f"{MAILPIT_API}/messages", timeout=5).json().get("messages", [])
        new_msgs = [m for m in msgs if m["ID"] not in ctx.get("seen_before_clone", set())]
        for msg in new_msgs:
            recipients = [t.get("Address", "") for t in msg.get("To", [])]
            subj = msg.get("Subject", "").lower()
            if ctx["a"]["email"] in recipients and "included" in subj and "shared expense" in subj:
                raise AssertionError(
                    f"Cloning owner must not receive a self-notification, but got: {subj}"
                )


# ---------------------------------------------------------------------------
# Project expense: clone preserves project FK and spendings, notifies member
# ---------------------------------------------------------------------------

class TestCloneProjectExpense:
    """Cloning a project expense copies project FK and BuddySpending rows, notifies B."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Cara", last_name="ProjectCloner")
        b = setup_user(None, None, first_name="Dan", last_name="ProjectMember")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        group_pk = int(_create_group(a["email"], "Clone Test Project"))
        _add_group_member(group_pk, b["email"])

        exp_pk = _shell(
            f"from budget.models import Expense, TransactionType; "
            f"from buddies.models import BuddySpending, Project; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"a = FeUser.objects.get(email='{a['email']}'); "
            f"b = FeUser.objects.get(email='{b['email']}'); "
            f"g = Project.objects.get(pk={group_pk}); "
            f"e = Expense.objects.create(owning_feuser=a, title='Original Project Expense', "
            f"  type=TransactionType.EXPENSE, value=Decimal('120.00'), settled=False, "
            f"  buddy_approved=True, project=g); "
            f"BuddySpending.objects.create(expense=e, participant_feuser=b, "
            f"  share_percent=Decimal('50.00')); "
            f"print(e.pk)"
        )
        ctx = {"a": a, "b": b, "b_pk": b_pk, "group_pk": group_pk, "exp_pk": int(exp_pk)}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_clone_preserves_project_fk(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before_clone"] = seen_before

        _login_as(driver, ctx["a"])
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/clone/"))
        time.sleep(2)

        import re
        m = re.search(r'/expenses/(\d+)/edit/', driver.current_url)
        assert m, "Clone should redirect to the edit page of the new expense"
        ctx["clone_pk"] = int(m.group(1))

        project_pk = _shell(
            f"from budget.models import Expense; "
            f"e = Expense.objects.get(pk={ctx['clone_pk']}); "
            f"print(e.project_id)"
        )
        assert project_pk == str(ctx["group_pk"]), (
            f"Cloned expense must retain project FK {ctx['group_pk']}, got {project_pk}"
        )

    def test_clone_copies_project_spendings(self, driver, w, ctx):
        count = _shell(
            f"from buddies.models import BuddySpending; "
            f"print(BuddySpending.objects.filter(expense_id={ctx['clone_pk']}).count())"
        )
        assert count == "1", f"Clone must have 1 BuddySpending row, got {count}"

    def test_project_participant_notified_after_clone(self, driver, w, ctx):
        body = fetch_email(
            ctx["b"]["email"], "included you in a shared expense",
            ignore_ids=ctx.get("seen_before_clone"),
        )
        assert "Original Project Expense" in body or "CLONE" in body, (
            "Notification email must mention the cloned expense title"
        )
        assert "Cara ProjectCloner" in body, "Email must mention the cloner's name"
