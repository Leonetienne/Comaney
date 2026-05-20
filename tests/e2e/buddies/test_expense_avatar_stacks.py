"""
Avatar stacks on expense rows: count and content verification.

Covers five structural cases across four UI locations:

  Case 1  Normal buddy: feuser pays feuser, one BuddySpending       → 2 avatars
  Case 2  Dummy payer:  is_dummy=True, two BuddySpending rows       → 3 avatars
  Case 3  Settlement dummy→feuser: is_dummy=True, no BuddySpending  → 2 avatars (template only)
  Case 4  Feuser→dummy: feuser pays, one BuddySpending with dummy   → 2 avatars
  Case 5  Non-buddy:    is_dummy=False, no BuddySpending            → no stack

Locations:
  /budget/expenses/         (Alpine.js, API-driven) — only Cases 1, 4, 5 appear here;
                             the API filters is_dummy=False so Cases 2 and 3 are excluded.
  /buddies/summary/         "One-on-one expenses"
  /buddies/summary/         "Waiting for your approval"
  /projects/<id>/     "Waiting for approval" + "Expense Breakdown"
"""
import time
import uuid
from datetime import date

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user, PASSWORD
from bhelpers import (
    _shell, _login_as,
    _create_buddy_link, _create_group, _add_group_member, _get_pk,
)


# ── DOM helpers ────────────────────────────────────────────────────────────────

def _avatars_in_list_row(driver, title: str) -> int:
    """Count .user-avatar elements in the Alpine.js expense list card for *title*."""
    return driver.execute_script(
        """
        var cards = document.querySelectorAll('.exp-card');
        for (var c of cards) {
            var t = c.querySelector('.exp-title');
            if (t && t.textContent.trim() === arguments[0]) {
                var stack = c.querySelector('.avatar-stack');
                return stack ? stack.querySelectorAll('.user-avatar').length : 0;
            }
        }
        return -1;
        """,
        title,
    )


def _avatar_texts_in_list_row(driver, title: str) -> list:
    """Return initials or img src for each avatar in the Alpine.js card for *title*."""
    return driver.execute_script(
        """
        var cards = document.querySelectorAll('.exp-card');
        for (var c of cards) {
            var t = c.querySelector('.exp-title');
            if (t && t.textContent.trim() === arguments[0]) {
                var stack = c.querySelector('.avatar-stack');
                if (!stack) return [];
                return Array.from(stack.querySelectorAll('.user-avatar')).map(function(el) {
                    return el.tagName === 'IMG' ? el.getAttribute('src') : el.textContent.trim();
                });
            }
        }
        return null;
        """,
        title,
    )


def _avatars_in_card(driver, title: str) -> int:
    """Count .user-avatar elements in the server-rendered card whose .bexp-title matches *title*.

    Uses first-text-node matching so that nested pill spans (e.g. the 'Pending' badge
    inside the group pending section's .bexp-title) do not interfere.
    """
    return driver.execute_script(
        """
        var firstText = function(el) {
            var nodes = Array.from(el.childNodes).filter(function(n) {
                return n.nodeType === 3 && n.textContent.trim().length > 0;
            });
            return nodes.length ? nodes[0].textContent.trim() : '';
        };
        var titleEls = document.querySelectorAll('.bexp-title');
        for (var t of titleEls) {
            if (firstText(t) === arguments[0]) {
                var card = t.closest('.bexp-breakdown-card');
                if (!card) return -1;
                var stack = card.querySelector('.avatar-stack');
                return stack ? stack.querySelectorAll('.user-avatar').length : 0;
            }
        }
        return -1;
        """,
        title,
    )


def _avatar_texts_in_card(driver, title: str) -> list:
    """Return initials or img src for each avatar in the server-rendered card for *title*."""
    return driver.execute_script(
        """
        var firstText = function(el) {
            var nodes = Array.from(el.childNodes).filter(function(n) {
                return n.nodeType === 3 && n.textContent.trim().length > 0;
            });
            return nodes.length ? nodes[0].textContent.trim() : '';
        };
        var titleEls = document.querySelectorAll('.bexp-title');
        for (var t of titleEls) {
            if (firstText(t) === arguments[0]) {
                var card = t.closest('.bexp-breakdown-card');
                if (!card) return null;
                var stack = card.querySelector('.avatar-stack');
                if (!stack) return [];
                return Array.from(stack.querySelectorAll('.user-avatar')).map(function(el) {
                    return el.tagName === 'IMG' ? el.getAttribute('src') : el.textContent.trim();
                });
            }
        }
        return null;
        """,
        title,
    )


def _search_expense_list(driver, query: str) -> None:
    """Type *query* into the expense search box and wait for results."""
    el = driver.find_element(By.ID, "exp-search")
    driver.execute_script("arguments[0].value = arguments[1];", el, query)
    driver.execute_script(
        "var e = arguments[0];"
        "e.dispatchEvent(new Event('input', {bubbles:true}));"
        "e.dispatchEvent(new Event('change', {bubbles:true}));",
        el,
    )
    time.sleep(2)


# ── Fixture ────────────────────────────────────────────────────────────────────

class TestExpenseAvatarStacks:

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        # Alice: logged-in browser user  (initials "AA")
        alice = setup_user(driver, w, first_name="Alice", last_name="Alves")

        # Bob: second feuser, created via shell  (initials "BB")
        bob_email = f"bob-av-{uuid.uuid4().hex[:6]}@test.invalid"
        bob_pk = _shell(
            f"from feusers.models import FeUser; "
            f"u = FeUser(email='{bob_email}', first_name='Bob', last_name='Berger', "
            f"  is_confirmed=True, is_active=True); "
            f"u.set_password('{PASSWORD}'); u.save(); print(u.pk)"
        )
        _create_buddy_link(alice["email"], bob_email)

        # Group: Alice is admin, Bob is member
        group_id = _create_group(alice["email"], "Avatar Test Group")
        _add_group_member(int(group_id), bob_email)

        # Group dummy 1: payer in Case 2  (initials "GG")
        gdummy1_pk = _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='Group Gamma'); "
            f"ProjectMember.objects.create(group=g, dummy=d); "
            f"print(d.pk)"
        )
        # Group dummy 2: participant in Case 2  (initials "GD")
        gdummy2_pk = _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='Group Delta'); "
            f"ProjectMember.objects.create(group=g, dummy=d); "
            f"print(d.pk)"
        )
        # Personal dummy: used in Cases 3 and 4  (initials "PZ")
        pdummy_pk = _shell(
            f"from buddies.models import DummyUser; from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{alice['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Personal Zeta'); "
            f"print(d.pk)"
        )

        alice_pk = _get_pk(alice["email"])

        today = date.today().isoformat()

        # E1: Case 1 approved — feuser (Alice) pays feuser (Bob).  2 avatars: AA + BB
        e1_pk = _shell(
            f"from budget.models import Expense; from buddies.models import BuddySpending; "
            f"from feusers.models import FeUser; from decimal import Decimal; from datetime import date; "
            f"a = FeUser.objects.get(email='{alice['email']}'); "
            f"e = Expense.objects.create(owning_feuser=a, title='AvatarTest Normal Buddy', "
            f"  type='expense', value=Decimal('50.00'), buddy_approved=True, "
            f"  date_due=date.fromisoformat('{today}')); "
            f"BuddySpending.objects.create(expense=e, participant_feuser_id={bob_pk}, "
            f"  share_percent=Decimal('50.0')); print(e.pk)"
        )
        # E_pend1: Case 1 unapproved — same participants, for "Waiting for approval".  2 avatars: AA + BB
        e_pend1_pk = _shell(
            f"from budget.models import Expense; from buddies.models import BuddySpending; "
            f"from feusers.models import FeUser; from decimal import Decimal; from datetime import date; "
            f"a = FeUser.objects.get(email='{alice['email']}'); "
            f"e = Expense.objects.create(owning_feuser=a, title='AvatarTest Pending Buddy', "
            f"  type='expense', value=Decimal('50.00'), buddy_approved=False, "
            f"  date_due=date.fromisoformat('{today}')); "
            f"BuddySpending.objects.create(expense=e, participant_feuser_id={bob_pk}, "
            f"  share_percent=Decimal('50.0')); print(e.pk)"
        )
        # E2: Case 2 unapproved — group dummy payer (GDummy1), Bob + GDummy2 as spending participants.
        #     3 avatars: GG + BB + GD.  Appears in group "Waiting for approval" and buddy_summary
        #     "Waiting for approval" (dummy_payer kind).  NOT in the expense list (is_dummy=True).
        e2_pk = _shell(
            f"from budget.models import Expense; from buddies.models import Project, BuddySpending; "
            f"from feusers.models import FeUser; from decimal import Decimal; from datetime import date; "
            f"a = FeUser.objects.get(email='{alice['email']}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"e = Expense.objects.create(owning_feuser=a, title='AvatarTest Dummy Payer Pending', "
            f"  type='expense', value=Decimal('90.00'), buddy_approved=False, "
            f"  is_dummy=True, upfront_payee_dummy_id={gdummy1_pk}, project=g, "
            f"  date_due=date.fromisoformat('{today}')); "
            f"BuddySpending.objects.create(expense=e, participant_feuser_id={bob_pk}, "
            f"  share_percent=Decimal('33.0')); "
            f"BuddySpending.objects.create(expense=e, participant_dummy_id={gdummy2_pk}, "
            f"  share_percent=Decimal('33.0')); print(e.pk)"
        )
        # E2_approved: Case 2 approved — same setup, for group "Expense Breakdown".
        e2_appr_pk = _shell(
            f"from budget.models import Expense; from buddies.models import Project, BuddySpending; "
            f"from feusers.models import FeUser; from decimal import Decimal; from datetime import date; "
            f"a = FeUser.objects.get(email='{alice['email']}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"e = Expense.objects.create(owning_feuser=a, title='AvatarTest Dummy Payer Approved', "
            f"  type='expense', value=Decimal('90.00'), buddy_approved=True, "
            f"  is_dummy=True, upfront_payee_dummy_id={gdummy1_pk}, project=g, "
            f"  date_due=date.fromisoformat('{today}')); "
            f"BuddySpending.objects.create(expense=e, participant_feuser_id={bob_pk}, "
            f"  share_percent=Decimal('33.0')); "
            f"BuddySpending.objects.create(expense=e, participant_dummy_id={gdummy2_pk}, "
            f"  share_percent=Decimal('33.0')); print(e.pk)"
        )
        # E3: Case 3 — is_dummy=True, upfront_payee_dummy set, NO BuddySpending rows.
        #     Template renders 2 avatars (PDummy payer + Alice from {% empty %} block).
        #     NOT in the expense list (is_dummy=True is filtered by the API).
        e3_pk = _shell(
            f"from budget.models import Expense; "
            f"from feusers.models import FeUser; from decimal import Decimal; from datetime import date; "
            f"a = FeUser.objects.get(email='{alice['email']}'); "
            f"e = Expense.objects.create(owning_feuser=a, "
            f"  title='AvatarTest Settlement Dummy Payer', "
            f"  type='expense', value=Decimal('30.00'), buddy_approved=False, "
            f"  is_dummy=True, upfront_payee_dummy_id={pdummy_pk}, "
            f"  date_due=date.fromisoformat('{today}')); print(e.pk)"
        )
        # E4: Case 4 — feuser (Alice) pays, one BuddySpending with a dummy.  2 avatars: AA + PZ
        e4_pk = _shell(
            f"from budget.models import Expense; from buddies.models import BuddySpending; "
            f"from feusers.models import FeUser; from decimal import Decimal; from datetime import date; "
            f"a = FeUser.objects.get(email='{alice['email']}'); "
            f"e = Expense.objects.create(owning_feuser=a, title='AvatarTest Feuser To Dummy', "
            f"  type='expense', value=Decimal('40.00'), buddy_approved=True, "
            f"  date_due=date.fromisoformat('{today}')); "
            f"BuddySpending.objects.create(expense=e, participant_dummy_id={pdummy_pk}, "
            f"  share_percent=Decimal('50.0')); print(e.pk)"
        )
        # E5: Case 5 — plain non-buddy expense.  No avatar stack.
        e5_pk = _shell(
            f"from budget.models import Expense; "
            f"from feusers.models import FeUser; from decimal import Decimal; from datetime import date; "
            f"a = FeUser.objects.get(email='{alice['email']}'); "
            f"e = Expense.objects.create(owning_feuser=a, title='AvatarTest Non Buddy', "
            f"  type='expense', value=Decimal('20.00'), "
            f"  date_due=date.fromisoformat('{today}')); print(e.pk)"
        )

        yield {
            "alice": alice,
            "alice_pk": alice_pk,
            "bob_email": bob_email,
            "bob_pk": bob_pk,
            "group_id": group_id,
            "gdummy1_pk": gdummy1_pk,
            "gdummy2_pk": gdummy2_pk,
            "pdummy_pk": pdummy_pk,
            "e1_pk": e1_pk,
            "e_pend1_pk": e_pend1_pk,
            "e2_pk": e2_pk,
            "e2_appr_pk": e2_appr_pk,
            "e3_pk": e3_pk,
            "e4_pk": e4_pk,
            "e5_pk": e5_pk,
        }

        cleanup_user(alice["email"])
        cleanup_user(bob_email)

    # ── /budget/expenses/ (Alpine.js expense list) ─────────────────────────────

    def test_expense_list_case1_normal_buddy_count(self, driver, w, ctx):
        """Case 1: feuser pays feuser → 2 avatars in the expense list."""
        _login_as(driver, ctx["alice"])
        driver.get(_url("/budget/expenses/"))
        time.sleep(2)
        _search_expense_list(driver, "AvatarTest Normal Buddy")
        count = _avatars_in_list_row(driver, "AvatarTest Normal Buddy")
        assert count == 2, f"Expected 2 avatars for Case 1, got {count}"

    def test_expense_list_case1_normal_buddy_content(self, driver, w, ctx):
        """Case 1: avatar stack contains Alice (AA) and Bob (BB), no duplicates."""
        texts = _avatar_texts_in_list_row(driver, "AvatarTest Normal Buddy")
        assert texts is not None, "Row not found in expense list"
        assert "AA" in texts, f"Alice initials 'AA' missing from {texts}"
        assert "BB" in texts, f"Bob initials 'BB' missing from {texts}"
        assert len(texts) == len(set(texts)), f"Duplicate avatars: {texts}"

    def test_expense_list_case4_feuser_to_dummy_count(self, driver, w, ctx):
        """Case 4: feuser pays, one dummy spending participant → 2 avatars."""
        _search_expense_list(driver, "AvatarTest Feuser To Dummy")
        count = _avatars_in_list_row(driver, "AvatarTest Feuser To Dummy")
        assert count == 2, f"Expected 2 avatars for Case 4, got {count}"

    def test_expense_list_case4_feuser_to_dummy_content(self, driver, w, ctx):
        """Case 4: stack contains Alice (AA) and PDummy (PZ), no duplicates."""
        texts = _avatar_texts_in_list_row(driver, "AvatarTest Feuser To Dummy")
        assert texts is not None, "Row not found"
        assert "AA" in texts, f"Alice initials 'AA' missing from {texts}"
        assert "PZ" in texts, f"PDummy initials 'PZ' missing from {texts}"
        assert len(texts) == len(set(texts)), f"Duplicate avatars: {texts}"

    def test_expense_list_case5_non_buddy_no_stack(self, driver, w, ctx):
        """Case 5: non-buddy expense → no avatar stack in the expense list row."""
        _search_expense_list(driver, "AvatarTest Non Buddy")
        count = _avatars_in_list_row(driver, "AvatarTest Non Buddy")
        assert count == 0, f"Expected 0 avatars for Case 5 (non-buddy), got {count}"

    # ── /buddies/summary/ — "One-on-one expenses" ──────────────────────────────

    def _load_summary(self, driver):
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)

    def test_one_on_one_case1_count(self, driver, w, ctx):
        """Case 1 in One-on-one expenses: 2 avatars (Alice + Bob)."""
        _login_as(driver, ctx["alice"])
        self._load_summary(driver)
        count = _avatars_in_card(driver, "AvatarTest Normal Buddy")
        assert count == 2, f"Expected 2 avatars in One-on-one for Case 1, got {count}"

    def test_one_on_one_case1_content(self, driver, w, ctx):
        """Case 1 in One-on-one: AA and BB present, no duplicates."""
        texts = _avatar_texts_in_card(driver, "AvatarTest Normal Buddy")
        assert texts is not None, "Card not found in One-on-one section"
        assert "AA" in texts, f"Alice 'AA' missing from {texts}"
        assert "BB" in texts, f"Bob 'BB' missing from {texts}"
        assert len(texts) == len(set(texts)), f"Duplicate avatars: {texts}"

    def test_one_on_one_case4_count(self, driver, w, ctx):
        """Case 4 in One-on-one expenses: 2 avatars (Alice + PDummy)."""
        count = _avatars_in_card(driver, "AvatarTest Feuser To Dummy")
        assert count == 2, f"Expected 2 avatars in One-on-one for Case 4, got {count}"

    def test_one_on_one_case4_content(self, driver, w, ctx):
        """Case 4 in One-on-one: AA and PZ present, no duplicates."""
        texts = _avatar_texts_in_card(driver, "AvatarTest Feuser To Dummy")
        assert texts is not None, "Card not found in One-on-one section"
        assert "AA" in texts, f"Alice 'AA' missing from {texts}"
        assert "PZ" in texts, f"PDummy 'PZ' missing from {texts}"
        assert len(texts) == len(set(texts)), f"Duplicate avatars: {texts}"

    def test_one_on_one_case3_count(self, driver, w, ctx):
        """Case 3 in One-on-one: is_dummy=True no spendings → template shows 2 avatars (PDummy + Alice)."""
        count = _avatars_in_card(driver, "AvatarTest Settlement Dummy Payer")
        assert count == 2, f"Expected 2 avatars in One-on-one for Case 3, got {count}"

    def test_one_on_one_case3_content(self, driver, w, ctx):
        """Case 3 in One-on-one: PZ (dummy payer) and AA (owning feuser via empty block)."""
        texts = _avatar_texts_in_card(driver, "AvatarTest Settlement Dummy Payer")
        assert texts is not None, "Card not found in One-on-one section"
        assert "PZ" in texts, f"PDummy 'PZ' missing from {texts}"
        assert "AA" in texts, f"Alice 'AA' missing from {texts}"
        assert len(texts) == len(set(texts)), f"Duplicate avatars: {texts}"

    # ── /buddies/summary/ — "Waiting for your approval" ───────────────────────

    def test_pending_approvals_case1_count(self, driver, w, ctx):
        """Case 1 unapproved in pending_approvals (expense_owner kind): 2 avatars."""
        _login_as(driver, ctx["alice"])
        self._load_summary(driver)
        count = _avatars_in_card(driver, "AvatarTest Pending Buddy")
        assert count == 2, f"Expected 2 avatars in Waiting-for-approval for Case 1, got {count}"

    def test_pending_approvals_case1_content(self, driver, w, ctx):
        """Case 1 pending: AA (Alice payer) and BB (Bob participant)."""
        texts = _avatar_texts_in_card(driver, "AvatarTest Pending Buddy")
        assert texts is not None, "Card not found in Waiting-for-approval"
        assert "AA" in texts, f"Alice 'AA' missing from {texts}"
        assert "BB" in texts, f"Bob 'BB' missing from {texts}"
        assert len(texts) == len(set(texts)), f"Duplicate avatars: {texts}"

    def test_pending_approvals_case2_dummy_payer_count(self, driver, w, ctx):
        """Case 2 (dummy_payer kind for group admin): 3 avatars."""
        count = _avatars_in_card(driver, "AvatarTest Dummy Payer Pending")
        assert count == 3, f"Expected 3 avatars in Waiting-for-approval for Case 2, got {count}"

    def test_pending_approvals_case2_dummy_payer_content(self, driver, w, ctx):
        """Case 2 pending: GG (dummy payer), BB (Bob), GD (GDummy2)."""
        texts = _avatar_texts_in_card(driver, "AvatarTest Dummy Payer Pending")
        assert texts is not None, "Card not found in Waiting-for-approval"
        assert "GG" in texts, f"GDummy1 'GG' missing from {texts}"
        assert "BB" in texts, f"Bob 'BB' missing from {texts}"
        assert "GD" in texts, f"GDummy2 'GD' missing from {texts}"
        assert len(texts) == len(set(texts)), f"Duplicate avatars: {texts}"

    def test_pending_approvals_case3_count(self, driver, w, ctx):
        """Case 3 (expense_owner kind, is_dummy no spendings): 2 avatars via template empty block."""
        count = _avatars_in_card(driver, "AvatarTest Settlement Dummy Payer")
        assert count == 2, f"Expected 2 avatars in Waiting-for-approval for Case 3, got {count}"

    def test_pending_approvals_case3_content(self, driver, w, ctx):
        """Case 3 pending: PZ (dummy payer) and AA (owning feuser from empty block)."""
        texts = _avatar_texts_in_card(driver, "AvatarTest Settlement Dummy Payer")
        assert texts is not None, "Card not found in Waiting-for-approval"
        assert "PZ" in texts, f"PDummy 'PZ' missing from {texts}"
        assert "AA" in texts, f"Alice 'AA' missing from {texts}"
        assert len(texts) == len(set(texts)), f"Duplicate avatars: {texts}"

    # ── /projects/<id>/ — "Waiting for approval" ────────────────────────

    def _load_group(self, driver, ctx):
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(2)

    def test_group_pending_case2_count(self, driver, w, ctx):
        """Case 2 in group Waiting-for-approval: 3 avatars (GDummy1 + Bob + GDummy2)."""
        _login_as(driver, ctx["alice"])
        self._load_group(driver, ctx)
        count = _avatars_in_card(driver, "AvatarTest Dummy Payer Pending")
        assert count == 3, f"Expected 3 avatars in group pending for Case 2, got {count}"

    def test_group_pending_case2_content(self, driver, w, ctx):
        """Case 2 group pending: GG (payer), BB and GD (spendings), no duplicates."""
        texts = _avatar_texts_in_card(driver, "AvatarTest Dummy Payer Pending")
        assert texts is not None, "Card not found in group Waiting-for-approval"
        assert "GG" in texts, f"GDummy1 'GG' missing from {texts}"
        assert "BB" in texts, f"Bob 'BB' missing from {texts}"
        assert "GD" in texts, f"GDummy2 'GD' missing from {texts}"
        assert len(texts) == len(set(texts)), f"Duplicate avatars: {texts}"

    # ── /projects/<id>/ — "Expense Breakdown" ────────────────────────────

    def test_group_breakdown_case2_count(self, driver, w, ctx):
        """Case 2 approved in group Expense Breakdown: 3 avatars (GDummy1 + Bob + GDummy2)."""
        count = _avatars_in_card(driver, "AvatarTest Dummy Payer Approved")
        assert count == 3, f"Expected 3 avatars in group Expense Breakdown for Case 2, got {count}"

    def test_group_breakdown_case2_content(self, driver, w, ctx):
        """Case 2 group breakdown: GG (payer), BB and GD (spendings), no duplicates."""
        texts = _avatar_texts_in_card(driver, "AvatarTest Dummy Payer Approved")
        assert texts is not None, "Card not found in group Expense Breakdown"
        assert "GG" in texts, f"GDummy1 'GG' missing from {texts}"
        assert "BB" in texts, f"Bob 'BB' missing from {texts}"
        assert "GD" in texts, f"GDummy2 'GD' missing from {texts}"
        assert len(texts) == len(set(texts)), f"Duplicate avatars: {texts}"
