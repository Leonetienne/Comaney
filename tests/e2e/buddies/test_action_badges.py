"""
Action badges in the sidebar (Manage Buddies, Buddy Expenses, Projects)
and per-project approval bubble on the projects list page.

Each test class:
  1. Creates the triggering state via the shell/service layer.
  2. Logs in as the affected user.
  3. Navigates to a page that contains the sidebar.
  4. Asserts the correct badge is visible with a positive count.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import (
    _shell, _login_as, _get_pk,
    _create_buddy_link, _create_group, _add_group_member,
    _create_group_expense, _create_personal_expense_with_buddy,
)


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

def _sidebar_badge(driver, nav_text: str) -> int:
    """Return the integer value of the action-badge next to the given sidebar link text."""
    links = driver.find_elements(By.CSS_SELECTOR, "nav.sidebar a")
    for link in links:
        if nav_text.lower() in link.text.lower():
            badges = link.find_elements(By.CSS_SELECTOR, ".action-badge")
            if badges:
                text = badges[0].text.strip()
                return int(text) if text.isdigit() else 0
    return 0


def _project_card_badge(driver, project_name: str) -> int:
    """Return the action-badge count on the project card with the given name."""
    cards = driver.find_elements(By.CSS_SELECTOR, ".bgs-card")
    for card in cards:
        names = card.find_elements(By.CSS_SELECTOR, ".bgs-name")
        if names and project_name.lower() in names[0].text.lower():
            badges = card.find_elements(By.CSS_SELECTOR, ".action-badge")
            if badges:
                text = badges[0].text.strip()
                return int(text) if text.isdigit() else 0
    return 0


def _create_buddy_invite(inviter_email: str, invitee_email: str) -> None:
    """Create a BuddyInvite from inviter to invitee (bypassing expiry)."""
    _shell(
        f"from buddies.models import BuddyInvite; "
        f"from feusers.models import FeUser; "
        f"from django.utils import timezone; from datetime import timedelta; "
        f"inviter = FeUser.objects.get(email='{inviter_email}'); "
        f"BuddyInvite.objects.create(inviter=inviter, invitee_email='{invitee_email}', "
        f"  expires_at=timezone.now() + timedelta(days=7))"
    )


def _create_project_invite(admin_email: str, invitee_email: str, project_id: int) -> None:
    """Create a ProjectInvite for the given project."""
    _shell(
        f"from buddies.services import ProjectService; "
        f"from feusers.models import FeUser; from buddies.models import Project; "
        f"admin = FeUser.objects.get(email='{admin_email}'); "
        f"g = Project.objects.get(pk={project_id}); "
        f"ProjectService.invite_member(g, admin, '{invitee_email}')"
    )


def _create_unapproved_expense(owner_email: str, participant_pk: int) -> str:
    """Create a personal buddy expense that owner has not yet approved (buddy_approved=False)."""
    return _shell(
        f"from budget.models import Expense; "
        f"from buddies.models import BuddySpending; "
        f"from feusers.models import FeUser; from decimal import Decimal; "
        f"other = FeUser.objects.get(pk={participant_pk}); "
        f"owner = FeUser.objects.get(email='{owner_email}'); "
        f"e = Expense.objects.create(owning_feuser=owner, title='BadgeTest', "
        f"  type='expense', value=Decimal('50.00'), settled=False, "
        f"  buddy_approved=False, is_buddies_settlement=False); "
        f"BuddySpending.objects.create(expense=e, participant_feuser=other, "
        f"  share_percent=Decimal('50.0')); "
        f"print(e.pk)"
    )


def _create_settlement_pending(debtor_email: str, creditor_pk: int,
                                project_id=None) -> str:
    """Create a settlement expense awaiting creditor approval."""
    project_arg = f"project_id={project_id}" if project_id else "project=None"
    return _shell(
        f"from budget.models import Expense; "
        f"from buddies.models import BuddySpending; "
        f"from feusers.models import FeUser; from decimal import Decimal; "
        f"debtor = FeUser.objects.get(email='{debtor_email}'); "
        f"e = Expense.objects.create(owning_feuser=debtor, title='BadgeSettlement', "
        f"  type='expense', value=Decimal('50.00'), settled=True, "
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
    alice = setup_user(driver, w, first_name="Alice", last_name="BadgeTest")
    bob = setup_user(None, None, first_name="Bob", last_name="BadgeTest")
    alice_pk = int(_get_pk(alice["email"]))
    bob_pk = int(_get_pk(bob["email"]))
    _create_buddy_link(alice["email"], bob["email"])
    project_id = int(_create_group(alice["email"], "BadgeProject"))
    _add_group_member(project_id, bob["email"])
    extra_users: list = []
    yield {
        "alice": alice,
        "bob": bob,
        "alice_pk": alice_pk,
        "bob_pk": bob_pk,
        "project_id": project_id,
        "extra_users": extra_users,
    }
    for u in extra_users:
        cleanup_user(u["email"])
    cleanup_user(alice["email"])
    cleanup_user(bob["email"])


# ---------------------------------------------------------------------------
# 1. "Manage Buddies" badge: incoming buddy invite
# ---------------------------------------------------------------------------

class TestManageBuddiesBadge:
    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        carol = setup_user(None, None, first_name="Carol", last_name="BadgeTest")
        ctx["extra_users"].append(carol)
        _create_buddy_invite(carol["email"], ctx["alice"]["email"])
        ctx["carol"] = carol

    def test_manage_buddies_badge_visible(self, driver, w, ctx):
        _login_as(driver, ctx["alice"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        count = _sidebar_badge(driver, "Manage Buddies")
        assert count >= 1, f"Expected Manage Buddies badge >= 1, got {count}"

    def test_no_manage_buddies_badge_for_inviter(self, driver, w, ctx):
        _login_as(driver, ctx["carol"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        count = _sidebar_badge(driver, "Manage Buddies")
        assert count == 0, f"Inviter should not see a badge, got {count}"


# ---------------------------------------------------------------------------
# 2. "Buddy Expenses" badge: expense awaiting owner approval
# ---------------------------------------------------------------------------

class TestBuddyExpensesBadge:
    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        # Bob logs an expense with Alice as upfront payer (buddy_approved=False)
        eid = _create_unapproved_expense(ctx["alice"]["email"], ctx["bob_pk"])
        ctx["unapproved_eid"] = int(eid)

    def test_buddy_expenses_badge_visible(self, driver, w, ctx):
        _login_as(driver, ctx["alice"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        count = _sidebar_badge(driver, "Buddy Expenses")
        assert count >= 1, f"Expected Buddy Expenses badge >= 1, got {count}"

    def test_no_buddy_expenses_badge_for_participant(self, driver, w, ctx):
        _login_as(driver, ctx["bob"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        # Bob is participant, not the one who needs to approve
        count = _sidebar_badge(driver, "Buddy Expenses")
        assert count == 0, f"Participant should not see a badge, got {count}"


# ---------------------------------------------------------------------------
# 3. "Buddy Expenses" badge: settlement awaiting creditor approval
# ---------------------------------------------------------------------------

class TestBuddyExpensesSettlementBadge:
    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        # Alice is debtor, Bob is creditor (bob needs to approve)
        eid = _create_settlement_pending(ctx["alice"]["email"], ctx["bob_pk"])
        ctx["settlement_eid"] = int(eid)

    def test_buddy_expenses_settlement_badge(self, driver, w, ctx):
        _login_as(driver, ctx["bob"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        count = _sidebar_badge(driver, "Buddy Expenses")
        assert count >= 1, f"Expected Buddy Expenses badge for creditor >= 1, got {count}"


# ---------------------------------------------------------------------------
# 4. "Projects" badge: incoming project invite
# ---------------------------------------------------------------------------

class TestProjectsBadgeInvite:
    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        dave = setup_user(None, None, first_name="Dave", last_name="BadgeTest")
        ctx["extra_users"].append(dave)
        invite_pid = int(_create_group(ctx["alice"]["email"], "BadgeInviteProject"))
        _create_project_invite(ctx["alice"]["email"], dave["email"], invite_pid)
        ctx["dave"] = dave
        ctx["invite_pid"] = invite_pid

    def test_projects_badge_for_invitee(self, driver, w, ctx):
        _login_as(driver, ctx["dave"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        count = _sidebar_badge(driver, "Projects")
        assert count >= 1, f"Expected Projects badge >= 1 for invitee, got {count}"


# ---------------------------------------------------------------------------
# 5. "Projects" badge: approval pending in a project
# ---------------------------------------------------------------------------

class TestProjectsBadgeApproval:
    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        # Alice is debtor, Bob is creditor in a project settlement
        eid = _create_settlement_pending(
            ctx["alice"]["email"], ctx["bob_pk"],
            project_id=ctx["project_id"],
        )
        ctx["proj_settlement_eid"] = int(eid)

    def test_projects_badge_for_creditor(self, driver, w, ctx):
        _login_as(driver, ctx["bob"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        count = _sidebar_badge(driver, "Projects")
        assert count >= 1, f"Expected Projects badge >= 1, got {count}"

    def test_no_projects_badge_for_debtor(self, driver, w, ctx):
        _login_as(driver, ctx["alice"])
        driver.get(_url("/budget/"))
        time.sleep(1)
        count = _sidebar_badge(driver, "Projects")
        # Alice initiated the settlement so she has no pending action
        assert count == 0, f"Debtor should not see a badge, got {count}"


# ---------------------------------------------------------------------------
# 6. Per-project approval bubble on the projects list page
# ---------------------------------------------------------------------------

class TestProjectListApprovalBubble:
    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        # Create another project with a pending approval for alice (owner approval)
        pid = int(_create_group(ctx["alice"]["email"], "BubbleProject"))
        _add_group_member(pid, ctx["bob"]["email"])
        # Alice is recorded as upfront payer, buddy_approved=False
        _create_unapproved_expense(ctx["alice"]["email"], ctx["bob_pk"])
        # Also add a project-level unapproved expense for alice in the project
        _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import BuddySpending, Project; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"alice = FeUser.objects.get(email='{ctx['alice']['email']}'); "
            f"bob = FeUser.objects.get(pk={ctx['bob_pk']}); "
            f"g = Project.objects.get(pk={pid}); "
            f"e = Expense.objects.create(owning_feuser=alice, title='BubbleExp', "
            f"  type='expense', value=Decimal('80.00'), settled=False, "
            f"  buddy_approved=False, is_buddies_settlement=False, project=g); "
            f"BuddySpending.objects.create(expense=e, participant_feuser=bob, "
            f"  share_percent=Decimal('50.0'))"
        )
        ctx["bubble_project_id"] = pid

    def test_project_card_shows_bubble(self, driver, w, ctx):
        _login_as(driver, ctx["alice"])
        driver.get(_url("/projects/"))
        time.sleep(1)
        count = _project_card_badge(driver, "BubbleProject")
        assert count >= 1, f"Expected project card bubble >= 1, got {count}"

    def test_no_bubble_for_clean_project(self, driver, w, ctx):
        _login_as(driver, ctx["alice"])
        driver.get(_url("/projects/"))
        time.sleep(1)
        # "BadgeProject" (created in the module fixture) has no feuser-level
        # approvals for alice (alice is admin/owner but all prior test expenses
        # only added approvals for bob as creditor)
        count = _project_card_badge(driver, "BadgeProject")
        assert count == 0, f"Clean project should not show a bubble, got {count}"


# ---------------------------------------------------------------------------
# 7. Projects sidebar number == sum of all per-project card numbers
# ---------------------------------------------------------------------------

def _all_project_card_badges(driver) -> list[int]:
    """Return the badge count for every project card on the projects list page."""
    counts = []
    for card in driver.find_elements(By.CSS_SELECTOR, ".bgs-card"):
        badges = card.find_elements(By.CSS_SELECTOR, ".action-badge")
        if badges:
            text = badges[0].text.strip()
            counts.append(int(text) if text.isdigit() else 0)
        else:
            counts.append(0)
    return counts


class TestProjectsSidebarEqualsSumOfCards:
    """
    The Projects sidebar badge must equal the sum of all per-project card
    bubbles when there are no pending project invites for the user.
    We use a fresh user (Eve) who has no outstanding invites, only approvals
    spread across two projects.
    """

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, ctx):
        eve = setup_user(None, None, first_name="Eve", last_name="BadgeTest")
        ctx["extra_users"].append(eve)
        eve_pk = int(_get_pk(eve["email"]))

        # Project A: 2 pending approvals for Eve (she is upfront payer twice)
        pid_a = int(_create_group(eve["email"], "SumProjectA"))
        _add_group_member(pid_a, ctx["bob"]["email"])
        for idx in range(2):
            _shell(
                f"from budget.models import Expense; "
                f"from buddies.models import BuddySpending, Project; "
                f"from feusers.models import FeUser; from decimal import Decimal; "
                f"eve = FeUser.objects.get(pk={eve_pk}); "
                f"bob = FeUser.objects.get(pk={ctx['bob_pk']}); "
                f"g = Project.objects.get(pk={pid_a}); "
                f"e = Expense.objects.create(owning_feuser=eve, title='SumExpA{idx}', "
                f"  type='expense', value=Decimal('30.00'), settled=False, "
                f"  buddy_approved=False, is_buddies_settlement=False, project=g); "
                f"BuddySpending.objects.create(expense=e, participant_feuser=bob, "
                f"  share_percent=Decimal('50.0'))"
            )

        # Project B: 1 pending approval for Eve (she is creditor in a settlement)
        pid_b = int(_create_group(eve["email"], "SumProjectB"))
        _add_group_member(pid_b, ctx["bob"]["email"])
        _create_settlement_pending(ctx["bob"]["email"], eve_pk, project_id=pid_b)

        ctx["eve"] = eve
        ctx["eve_pk"] = eve_pk
        ctx["sum_pid_a"] = pid_a
        ctx["sum_pid_b"] = pid_b

    def test_sidebar_equals_sum_of_card_badges(self, driver, w, ctx):
        _login_as(driver, ctx["eve"])
        # Read sidebar badge from any page that has the sidebar
        driver.get(_url("/budget/"))
        time.sleep(1)
        sidebar_count = _sidebar_badge(driver, "Projects")

        # Read per-project card badges from the projects list
        driver.get(_url("/projects/"))
        time.sleep(1)
        card_counts = _all_project_card_badges(driver)
        card_sum = sum(card_counts)

        assert sidebar_count == card_sum, (
            f"Projects sidebar badge ({sidebar_count}) != "
            f"sum of card badges ({card_sum}, individual: {card_counts})"
        )
