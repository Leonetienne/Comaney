"""
Notification bell navigation tests.

For every notification type this file:
  1. Creates the notification via the service layer (same code path as the UI)
     or via direct injection for types that need no specific related object.
  2. Logs in as the recipient and clicks the notification in the bell dropdown.
  3. Asserts the browser lands on the correct URL (path + anchor).
  4. Asserts the anchor element is present in the destination page's DOM.
  5. Asserts the unread-count badge decreased.

Extra coverage:
  - When both the related expense and project are null the notification carries
    no link; clicking it stays on the current page but still marks it read.
  - Clicking a linking notification and a non-linking notification both
    decrease the unread badge count.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import (
    _shell, _login_as, _get_pk, _create_buddy_link,
    _create_group, _add_group_member,
    _create_group_expense, _create_personal_expense_with_buddy,
)

# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

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


def _find_unread(driver, fragment: str):
    for el in driver.find_elements(By.CSS_SELECTOR, "#notif-list .notif-item--unread"):
        if fragment.lower() in el.text.lower():
            return el
    return None


def _click_notif(driver, item):
    item.click()
    time.sleep(2)


def _anchor_exists(driver, anchor_id: str) -> bool:
    return bool(driver.find_elements(By.ID, anchor_id))


# ---------------------------------------------------------------------------
# Notification creation helpers (service layer via Django shell)
# ---------------------------------------------------------------------------

def _inject_notif(email: str, ntype: str, message: str,
                  project_id=None, expense_id=None, feuser_id=None):
    pid_arg = f"related_project_id={project_id}" if project_id else "related_project=None"
    eid_arg = f"related_expense_id={expense_id}" if expense_id else "related_expense=None"
    fid_arg = f"related_feuser_id={feuser_id}" if feuser_id else "related_feuser=None"
    _shell(
        f"from feusers.models import FeUser, Notification; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"Notification.objects.create(owning_feuser=u, type='{ntype}', "
        f"  subject='Test', message='{message}', {pid_arg}, {eid_arg}, {fid_arg})"
    )


def _emit_participation(expense_pk: int, actor_email: str, recipient_email: str):
    _shell(
        f"from buddies.services.email import BuddyEmailService; "
        f"from budget.models import Expense; from feusers.models import FeUser; "
        f"e = Expense.objects.get(pk={expense_pk}); "
        f"actor = FeUser.objects.get(email='{actor_email}'); "
        f"rec = FeUser.objects.get(email='{recipient_email}'); "
        f"BuddyEmailService.send_expense_participant_notice(e, actor, rec, actor.currency)"
    )


def _emit_assignment(expense_pk: int, initiator_email: str):
    _shell(
        f"from buddies.services.email import BuddyEmailService; "
        f"from budget.models import Expense; from feusers.models import FeUser; "
        f"e = Expense.objects.get(pk={expense_pk}); "
        f"initiator = FeUser.objects.get(email='{initiator_email}'); "
        f"BuddyEmailService.send_expense_approval_request(e, initiator)"
    )


def _emit_participant_decision(expense_pk: int, participant_email: str):
    _shell(
        f"from buddies.services.email import BuddyEmailService; "
        f"from buddies.models import BuddySpending; "
        f"from budget.models import Expense; from feusers.models import FeUser; "
        f"e = Expense.objects.get(pk={expense_pk}); "
        f"p = FeUser.objects.get(email='{participant_email}'); "
        f"BuddyEmailService.send_participant_approval_notification("
        f"  e, p, BuddySpending.APPROVAL_APPROVED)"
    )


def _emit_settlement_request(expense_pk: int, debtor_email: str, creditor_email: str):
    _shell(
        f"from buddies.services.email import BuddyEmailService; "
        f"from budget.models import Expense; from feusers.models import FeUser; "
        f"e = Expense.objects.get(pk={expense_pk}); "
        f"debtor = FeUser.objects.get(email='{debtor_email}'); "
        f"creditor = FeUser.objects.get(email='{creditor_email}'); "
        f"BuddyEmailService.send_settlement_confirmation_request("
        f"  e, debtor, creditor, debtor.first_name)"
    )


def _create_settlement_expense(debtor_email: str, creditor_pk: int,
                                project_id=None, value: str = "50.00") -> str:
    """Create a settlement expense (buddy_approved=False) so it appears in pending_approvals."""
    project_arg = f"project_id={project_id}" if project_id else "project=None"
    return _shell(
        f"from budget.models import Expense; "
        f"from buddies.models import BuddySpending; "
        f"from feusers.models import FeUser; from decimal import Decimal; "
        f"debtor = FeUser.objects.get(email='{debtor_email}'); "
        f"e = Expense.objects.create(owning_feuser=debtor, title='NavSettlement', "
        f"  type='expense', value=Decimal('{value}'), settled=True, "
        f"  buddy_approved=False, is_buddies_settlement=True, {project_arg}); "
        f"BuddySpending.objects.create(expense=e, participant_feuser_id={creditor_pk}, "
        f"  share_percent=Decimal('100.0')); "
        f"print(e.pk)"
    )


# ---------------------------------------------------------------------------
# Module fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ctx(driver, w):
    alice = setup_user(driver, w, first_name="Alice", last_name="NavTest")
    bob = setup_user(None, None, first_name="Bob", last_name="NavTest")
    alice_pk = int(_get_pk(alice["email"]))
    bob_pk = int(_get_pk(bob["email"]))
    _create_buddy_link(alice["email"], bob["email"])
    project_id = int(_create_group(alice["email"], "NavTestProject"))
    _add_group_member(project_id, bob["email"])
    yield {
        "alice": alice,
        "bob": bob,
        "alice_pk": alice_pk,
        "bob_pk": bob_pk,
        "project_id": project_id,
    }
    cleanup_user(alice["email"])
    cleanup_user(bob["email"])


# ---------------------------------------------------------------------------
# 1. expense_participation – project expense
# ---------------------------------------------------------------------------

class TestExpenseParticipationProject:
    """Navigates to /projects/{pid}/#expense-{eid}; anchor exists."""

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        eid = int(_create_group_expense(
            ctx["alice"]["email"], ctx["bob"]["email"],
            ctx["project_id"], title="NavProjParticip",
        ))
        _emit_participation(eid, ctx["alice"]["email"], ctx["bob"]["email"])
        ctx["proj_particip_eid"] = eid

    def test_navigates_and_anchor_exists(self, driver, w, ctx):
        pid, eid = ctx["project_id"], ctx["proj_particip_eid"]
        _login_as(driver, ctx["bob"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        before = _badge_count(driver)
        assert before > 0, "Expected at least one unread notification for bob"
        _open_dropdown(driver)
        item = _find_unread(driver, "NavProjParticip")
        assert item is not None, "expense_participation (project) not in dropdown"
        _click_notif(driver, item)
        assert f"/projects/{pid}/" in driver.current_url, driver.current_url
        assert _anchor_exists(driver, f"expense-{eid}"), \
            f"#expense-{eid} missing on project page"
        assert _badge_count(driver) < before or _badge_count(driver) == 0


# ---------------------------------------------------------------------------
# 2. expense_participation – direct buddy expense
# ---------------------------------------------------------------------------

class TestExpenseParticipationDirect:
    """Navigates to /buddies/summary/#expense-{eid}; anchor exists."""

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        eid = int(_create_personal_expense_with_buddy(
            ctx["alice"]["email"], ctx["bob_pk"], title="NavDirectParticip",
        ))
        _emit_participation(eid, ctx["alice"]["email"], ctx["bob"]["email"])
        ctx["direct_particip_eid"] = eid

    def test_navigates_and_anchor_exists(self, driver, w, ctx):
        eid = ctx["direct_particip_eid"]
        _login_as(driver, ctx["bob"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        before = _badge_count(driver)
        _open_dropdown(driver)
        item = _find_unread(driver, "NavDirectParticip")
        assert item is not None, "expense_participation (direct) not in dropdown"
        _click_notif(driver, item)
        assert "/buddies/summary/" in driver.current_url, driver.current_url
        assert _anchor_exists(driver, f"expense-{eid}"), \
            f"#expense-{eid} missing on buddy summary page"
        assert _badge_count(driver) < before or _badge_count(driver) == 0


# ---------------------------------------------------------------------------
# 3. expense_assignments – project expense  (sent to expense owner)
# ---------------------------------------------------------------------------

class TestExpenseAssignmentsProject:
    """Navigates to /projects/{pid}/#expense-{eid}; anchor exists."""

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        eid = int(_create_group_expense(
            ctx["alice"]["email"], ctx["bob"]["email"],
            ctx["project_id"], title="NavProjAssign",
        ))
        _emit_assignment(eid, ctx["bob"]["email"])   # bob initiates, alice (owner) is notified
        ctx["proj_assign_eid"] = eid

    def test_navigates_and_anchor_exists(self, driver, w, ctx):
        pid, eid = ctx["project_id"], ctx["proj_assign_eid"]
        _login_as(driver, ctx["alice"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        before = _badge_count(driver)
        _open_dropdown(driver)
        item = _find_unread(driver, "NavProjAssign")
        assert item is not None, "expense_assignments (project) not in dropdown"
        _click_notif(driver, item)
        assert f"/projects/{pid}/" in driver.current_url, driver.current_url
        assert _anchor_exists(driver, f"expense-{eid}"), \
            f"#expense-{eid} missing on project page"
        assert _badge_count(driver) < before or _badge_count(driver) == 0


# ---------------------------------------------------------------------------
# 4. expense_assignments – direct buddy expense
# ---------------------------------------------------------------------------

class TestExpenseAssignmentsDirect:
    """Navigates to /buddies/summary/#expense-{eid}; anchor exists."""

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        eid = int(_create_personal_expense_with_buddy(
            ctx["alice"]["email"], ctx["bob_pk"], title="NavDirectAssign",
        ))
        _emit_assignment(eid, ctx["bob"]["email"])   # alice (owner) is notified
        ctx["direct_assign_eid"] = eid

    def test_navigates_and_anchor_exists(self, driver, w, ctx):
        eid = ctx["direct_assign_eid"]
        _login_as(driver, ctx["alice"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        before = _badge_count(driver)
        _open_dropdown(driver)
        item = _find_unread(driver, "NavDirectAssign")
        assert item is not None, "expense_assignments (direct) not in dropdown"
        _click_notif(driver, item)
        assert "/buddies/summary/" in driver.current_url, driver.current_url
        assert _anchor_exists(driver, f"expense-{eid}"), \
            f"#expense-{eid} missing on buddy summary page"
        assert _badge_count(driver) < before or _badge_count(driver) == 0


# ---------------------------------------------------------------------------
# 5. participant_decisions – project expense
# ---------------------------------------------------------------------------

class TestParticipantDecisionsProject:
    """Navigates to /projects/{pid}/#expense-{eid}; anchor exists."""

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        eid = int(_create_group_expense(
            ctx["alice"]["email"], ctx["bob"]["email"],
            ctx["project_id"], title="NavProjDecision",
        ))
        _emit_participant_decision(eid, ctx["bob"]["email"])   # alice (owner) is notified
        ctx["proj_decision_eid"] = eid

    def test_navigates_and_anchor_exists(self, driver, w, ctx):
        pid, eid = ctx["project_id"], ctx["proj_decision_eid"]
        _login_as(driver, ctx["alice"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        before = _badge_count(driver)
        _open_dropdown(driver)
        item = _find_unread(driver, "NavProjDecision")
        assert item is not None, "participant_decisions (project) not in dropdown"
        _click_notif(driver, item)
        assert f"/projects/{pid}/" in driver.current_url, driver.current_url
        assert _anchor_exists(driver, f"expense-{eid}"), \
            f"#expense-{eid} missing on project page"
        assert _badge_count(driver) < before or _badge_count(driver) == 0


# ---------------------------------------------------------------------------
# 6. participant_decisions – direct buddy expense
# ---------------------------------------------------------------------------

class TestParticipantDecisionsDirect:
    """Navigates to /buddies/summary/#expense-{eid}; anchor exists."""

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        eid = int(_create_personal_expense_with_buddy(
            ctx["alice"]["email"], ctx["bob_pk"], title="NavDirectDecision",
        ))
        _emit_participant_decision(eid, ctx["bob"]["email"])   # alice (owner) is notified
        ctx["direct_decision_eid"] = eid

    def test_navigates_and_anchor_exists(self, driver, w, ctx):
        eid = ctx["direct_decision_eid"]
        _login_as(driver, ctx["alice"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        before = _badge_count(driver)
        _open_dropdown(driver)
        item = _find_unread(driver, "NavDirectDecision")
        assert item is not None, "participant_decisions (direct) not in dropdown"
        _click_notif(driver, item)
        assert "/buddies/summary/" in driver.current_url, driver.current_url
        assert _anchor_exists(driver, f"expense-{eid}"), \
            f"#expense-{eid} missing on buddy summary page"
        assert _badge_count(driver) < before or _badge_count(driver) == 0


# ---------------------------------------------------------------------------
# 7. settlements – project
# ---------------------------------------------------------------------------

class TestSettlementsProject:
    """Navigates to /projects/{pid}/#section-balances; anchor exists."""

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        eid = int(_create_settlement_expense(
            ctx["alice"]["email"], ctx["bob_pk"],
            project_id=ctx["project_id"],
        ))
        _emit_settlement_request(eid, ctx["alice"]["email"], ctx["bob"]["email"])

    def test_navigates_and_anchor_exists(self, driver, w, ctx):
        pid = ctx["project_id"]
        _login_as(driver, ctx["bob"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        before = _badge_count(driver)
        _open_dropdown(driver)
        item = _find_unread(driver, "settlement")
        assert item is not None, "settlements (project) not in dropdown"
        _click_notif(driver, item)
        assert f"/projects/{pid}/" in driver.current_url, driver.current_url
        assert _anchor_exists(driver, "section-balances"), \
            "#section-balances missing on project page"
        assert _badge_count(driver) < before or _badge_count(driver) == 0


# ---------------------------------------------------------------------------
# 8. settlements – direct (no project)
# ---------------------------------------------------------------------------

class TestSettlementsDirect:
    """Navigates to /buddies/summary/#section-pending; anchor exists."""

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        eid = int(_create_settlement_expense(
            ctx["alice"]["email"], ctx["bob_pk"],
        ))
        _emit_settlement_request(eid, ctx["alice"]["email"], ctx["bob"]["email"])

    def test_navigates_and_anchor_exists(self, driver, w, ctx):
        _login_as(driver, ctx["bob"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        before = _badge_count(driver)
        _open_dropdown(driver)
        item = _find_unread(driver, "settlement")
        assert item is not None, "settlements (direct) not in dropdown"
        _click_notif(driver, item)
        assert "/buddies/summary/" in driver.current_url, driver.current_url
        assert _anchor_exists(driver, "section-pending"), \
            "#section-pending missing on buddy summary page"
        assert _badge_count(driver) < before or _badge_count(driver) == 0


# ---------------------------------------------------------------------------
# 9. group_activity – project invite
# ---------------------------------------------------------------------------

class TestGroupActivityProjectInvite:
    """Navigates to /projects/{pid}/."""

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        invite_pid = int(_create_group(ctx["alice"]["email"], "NavInviteProject"))
        _shell(
            f"from buddies.services import BuddyGroupService; "
            f"from feusers.models import FeUser; from buddies.models import Project; "
            f"admin = FeUser.objects.get(email='{ctx['alice']['email']}'); "
            f"g = Project.objects.get(pk={invite_pid}); "
            f"BuddyGroupService.invite_member(g, admin, '{ctx['bob']['email']}')"
        )
        ctx["invite_pid"] = invite_pid

    def test_navigates_to_project_page(self, driver, w, ctx):
        pid = ctx["invite_pid"]
        _login_as(driver, ctx["bob"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        before = _badge_count(driver)
        _open_dropdown(driver)
        item = _find_unread(driver, "NavInviteProject")
        assert item is not None, "group_activity (project invite) not in dropdown"
        _click_notif(driver, item)
        assert f"/projects/{pid}/" in driver.current_url, driver.current_url
        assert _badge_count(driver) < before or _badge_count(driver) == 0


# ---------------------------------------------------------------------------
# 10. group_activity – direct buddy invite
# ---------------------------------------------------------------------------

class TestGroupActivityBuddyInvite:
    """Navigates to /buddies/my-buddies/#section-invites; anchor exists."""

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        _inject_notif(
            ctx["bob"]["email"], "group_activity",
            "NavBuddyInvite: Alice invited you to be spending buddies.",
            feuser_id=ctx["alice_pk"],
        )

    def test_navigates_and_anchor_exists(self, driver, w, ctx):
        _login_as(driver, ctx["bob"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        before = _badge_count(driver)
        _open_dropdown(driver)
        item = _find_unread(driver, "NavBuddyInvite")
        assert item is not None, "group_activity (buddy invite) not in dropdown"
        _click_notif(driver, item)
        assert "/buddies/my-buddies/" in driver.current_url, driver.current_url
        assert _anchor_exists(driver, "section-invites"), \
            "#section-invites missing on my-buddies page"
        assert _badge_count(driver) < before or _badge_count(driver) == 0


# ---------------------------------------------------------------------------
# 11a. group_activity – project kick  →  no link (stays on current page)
# ---------------------------------------------------------------------------

class TestGroupActivityProjectKick:
    """Kicked-from-project notifications carry no URL; clicking just marks read."""

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        # Mimics send_group_removed_notification: pid set, rfid NOT set.
        _inject_notif(
            ctx["bob"]["email"], "group_activity",
            "NavProjectKick: Alice removed you from the project.",
            project_id=ctx["project_id"],
        )

    def test_no_navigation_on_click(self, driver, w, ctx):
        _login_as(driver, ctx["bob"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        before_url = driver.current_url
        before_count = _badge_count(driver)
        assert before_count > 0
        _open_dropdown(driver)
        item = _find_unread(driver, "NavProjectKick")
        assert item is not None, "project-kick notification not in dropdown"
        assert item.get_attribute("data-url") in (None, ""), \
            "project-kick notification must not have a data-url"
        _click_notif(driver, item)
        assert driver.current_url == before_url, \
            f"Expected no navigation; URL changed to {driver.current_url}"
        assert _badge_count(driver) < before_count or _badge_count(driver) == 0


# ---------------------------------------------------------------------------
# 11b. group_activity – buddy kick  →  /buddies/my-buddies/
# ---------------------------------------------------------------------------

class TestGroupActivityBuddyKick:
    """Kicked-as-buddy notification navigates to /buddies/my-buddies/ (no anchor)."""

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        # Mimics send_kicked_notification: no pid, no rfid.
        _inject_notif(
            ctx["bob"]["email"], "group_activity",
            "NavBuddyKick: Alice removed you as a spending buddy.",
        )

    def test_navigates_to_my_buddies(self, driver, w, ctx):
        _login_as(driver, ctx["bob"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        before = _badge_count(driver)
        assert before > 0
        _open_dropdown(driver)
        item = _find_unread(driver, "NavBuddyKick")
        assert item is not None, "buddy-kick notification not in dropdown"
        _click_notif(driver, item)
        assert "/buddies/my-buddies/" in driver.current_url, driver.current_url
        assert _badge_count(driver) < before or _badge_count(driver) == 0


# ---------------------------------------------------------------------------
# 11. own_partnership_changes  →  /budget/categories-tags/
# ---------------------------------------------------------------------------

class TestOwnPartnershipChanges:
    """Navigates to /budget/categories-tags/."""

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        _inject_notif(
            ctx["bob"]["email"], "own_partnership_changes",
            "NavOwnPartnership: your partnership changed.",
        )

    def test_navigates(self, driver, w, ctx):
        _login_as(driver, ctx["bob"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        before = _badge_count(driver)
        _open_dropdown(driver)
        item = _find_unread(driver, "NavOwnPartnership")
        assert item is not None, "own_partnership_changes not in dropdown"
        _click_notif(driver, item)
        assert "/budget/categories-tags/" in driver.current_url, driver.current_url
        assert _badge_count(driver) < before or _badge_count(driver) == 0


# ---------------------------------------------------------------------------
# 12. someones_partnership_changes  →  /budget/categories-tags/
# ---------------------------------------------------------------------------

class TestSomeonesPartnershipChanges:
    """Navigates to /budget/categories-tags/."""

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        _inject_notif(
            ctx["bob"]["email"], "someones_partnership_changes",
            "NavSomeonePartnership: a partner status changed.",
        )

    def test_navigates(self, driver, w, ctx):
        _login_as(driver, ctx["bob"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        before = _badge_count(driver)
        _open_dropdown(driver)
        item = _find_unread(driver, "NavSomeonePartnership")
        assert item is not None, "someones_partnership_changes not in dropdown"
        _click_notif(driver, item)
        assert "/budget/categories-tags/" in driver.current_url, driver.current_url
        assert _badge_count(driver) < before or _badge_count(driver) == 0


# ---------------------------------------------------------------------------
# 13. expense_reminders  →  /budget/expenses/
# ---------------------------------------------------------------------------

class TestExpenseReminders:
    """Navigates to /budget/expenses/."""

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        _inject_notif(
            ctx["alice"]["email"], "expense_reminders",
            "NavExpenseReminder: your payment is due soon.",
        )

    def test_navigates(self, driver, w, ctx):
        _login_as(driver, ctx["alice"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        before = _badge_count(driver)
        _open_dropdown(driver)
        item = _find_unread(driver, "NavExpenseReminder")
        assert item is not None, "expense_reminders not in dropdown"
        _click_notif(driver, item)
        assert "/budget/expenses/" in driver.current_url, driver.current_url
        assert _badge_count(driver) < before or _badge_count(driver) == 0


# ---------------------------------------------------------------------------
# 14. expense_settled  →  /budget/expenses/
# ---------------------------------------------------------------------------

class TestExpenseSettled:
    """Navigates to /budget/expenses/."""

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        _inject_notif(
            ctx["alice"]["email"], "expense_settled",
            "NavExpenseSettled: your payment has been marked as paid.",
        )

    def test_navigates(self, driver, w, ctx):
        _login_as(driver, ctx["alice"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        before = _badge_count(driver)
        _open_dropdown(driver)
        item = _find_unread(driver, "NavExpenseSettled")
        assert item is not None, "expense_settled not in dropdown"
        _click_notif(driver, item)
        assert "/budget/expenses/" in driver.current_url, driver.current_url
        assert _badge_count(driver) < before or _badge_count(driver) == 0


# ---------------------------------------------------------------------------
# 15. Deleted expense + deleted project: notification has no link
# ---------------------------------------------------------------------------

class TestDeletedExpenseAndProjectNoLink:
    """When both the related expense and project FKs are null, the notification
    item has no data-url; clicking stays on the current page."""

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        _inject_notif(
            ctx["bob"]["email"], "expense_participation",
            "NavDeletedBoth: expense and project were deleted.",
            project_id=None, expense_id=None,
        )

    def test_no_navigation_on_click(self, driver, w, ctx):
        _login_as(driver, ctx["bob"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        before_url = driver.current_url
        before_count = _badge_count(driver)
        assert before_count > 0
        _open_dropdown(driver)
        item = _find_unread(driver, "NavDeletedBoth")
        assert item is not None, "notification for null expense+project not in dropdown"
        assert item.get_attribute("data-url") in (None, ""), \
            "notification with null expense+project must not have a data-url"
        _click_notif(driver, item)
        assert driver.current_url == before_url, \
            f"Expected no navigation; URL changed to {driver.current_url}"
        assert _badge_count(driver) < before_count or _badge_count(driver) == 0


# ---------------------------------------------------------------------------
# 16. Badge count decreases for both linking and non-linking notifications
# ---------------------------------------------------------------------------

class TestBadgeCountDecreases:
    """Clicking any notification (linking or not) decreases the badge count."""

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        _inject_notif(
            ctx["alice"]["email"], "expense_reminders",
            "NavBadgeLinking: linking notification.",
        )
        _inject_notif(
            ctx["alice"]["email"], "expense_participation",
            "NavBadgeNoLink: non-linking notification (null expense+project).",
            project_id=None, expense_id=None,
        )

    def test_linking_notification_decreases_badge(self, driver, w, ctx):
        _login_as(driver, ctx["alice"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        before = _badge_count(driver)
        assert before > 0
        _open_dropdown(driver)
        item = _find_unread(driver, "NavBadgeLinking")
        assert item is not None
        _click_notif(driver, item)
        assert _badge_count(driver) < before or _badge_count(driver) == 0

    def test_non_linking_notification_decreases_badge(self, driver, w, ctx):
        _login_as(driver, ctx["alice"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        before = _badge_count(driver)
        assert before > 0
        _open_dropdown(driver)
        item = _find_unread(driver, "NavBadgeNoLink")
        assert item is not None
        item.click()   # no navigation — badge updates in-DOM
        time.sleep(2)
        assert _badge_count(driver) < before or _badge_count(driver) == 0
