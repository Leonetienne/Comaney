"""
Buddy group management: create, invite, accept/decline group invite,
member management, dummy management, admin transfer, leave, dissolve,
and group expense breakdown.
"""
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from helpers import (
    _url, setup_user, cleanup_user,
    fetch_email, extract_link, server_today,
)
from bhelpers import (
    _shell, _login_as, _confirm,
    _create_buddy_link, _get_pk,
    _create_group, _add_group_member, _create_group_expense,
)


# ---------------------------------------------------------------------------
# Create group and verify group detail page
# ---------------------------------------------------------------------------

class TestGroupCreate:
    """Create a group; verify detail page shows name, user is admin."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Gary", last_name="GroupAdmin")
        yield {"a": a}
        cleanup_user(a["email"])

    def test_create_group_via_ui(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        inp = driver.find_element(By.CSS_SELECTOR,
            "form[action*='create'] input[name='name']")
        inp.clear()
        inp.send_keys("Test Group Alpha")
        driver.find_element(By.ID, "btn-create-group").click()
        time.sleep(1)
        assert "/buddies/groups/" in driver.current_url

    def test_group_name_on_detail_page(self, driver, w, ctx):
        assert "Test Group Alpha" in driver.page_source

    def test_admin_pill_visible(self, driver, w, ctx):
        assert "You are admin" in driver.page_source or "Admin" in driver.page_source

    def test_admin_invite_section_visible(self, driver, w, ctx):
        assert "Invite members" in driver.page_source

    def test_group_appears_on_my_buddies(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Test Group Alpha" in driver.page_source


# ---------------------------------------------------------------------------
# Invite member via email + accept via email link
# ---------------------------------------------------------------------------

class TestGroupInviteAccept:
    """Admin invites C; C accepts via email link; C joins as member."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Gina", last_name="InvAdmin")
        c = setup_user(None, None, first_name="Carl", last_name="InvMember")
        group_id = _create_group(a["email"], "Invite Test Group")
        yield {"a": a, "c": c, "group_id": int(group_id)}
        cleanup_user(a["email"])
        cleanup_user(c["email"])

    def test_admin_invites_member(self, driver, w, ctx):
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        inp = driver.find_element(By.CSS_SELECTOR,
            "form[action*='invite'] input[name='email']")
        inp.clear()
        inp.send_keys(ctx["c"]["email"])
        driver.find_element(By.ID, "btn-group-invite").click()
        time.sleep(1)
        assert "Group invitation sent" in driver.page_source or \
               ctx["c"]["email"] in driver.page_source

    def test_pending_invite_shown_to_admin(self, driver, w, ctx):
        assert "Pending invitations" in driver.page_source or \
               ctx["c"]["email"] in driver.page_source

    def test_invite_email_arrives_for_c(self, driver, w, ctx):
        body = fetch_email(ctx["c"]["email"], "Invite Test Group")
        ctx["group_invite_link"] = extract_link(body)
        assert "/buddies/group-invite/" in ctx["group_invite_link"]

    def test_c_sees_group_invite_on_buddies_page(self, driver, w, ctx):
        _login_as(driver, ctx["c"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Group invitations" in driver.page_source
        assert "Invite Test Group" in driver.page_source

    def test_c_accepts_group_invite_via_link(self, driver, w, ctx):
        driver.get(ctx["group_invite_link"])
        time.sleep(1)
        assert "You're invited!" in driver.page_source
        assert "Invite Test Group" in driver.page_source
        driver.find_element(By.ID, "btn-accept-group-invite").click()
        time.sleep(1)
        assert f"/buddies/groups/{ctx['group_id']}/" in driver.current_url

    def test_c_in_member_list_after_accept(self, driver, w, ctx):
        assert ctx["c"]["email"] in driver.page_source

    def test_buddy_link_created_between_a_and_c(self, driver, w, ctx):
        count = _shell(
            f"from buddies.models import BuddyLink; "
            f"from feusers.models import FeUser; "
            f"from django.db.models import Q; "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"c = FeUser.objects.get(email='{ctx['c']['email']}'); "
            f"print(BuddyLink.objects.filter(Q(user_a=a,user_b=c)|Q(user_a=c,user_b=a)).count())"
        )
        assert count == "1", "Accepting group invite must create a BuddyLink"


# ---------------------------------------------------------------------------
# Decline group invite
# ---------------------------------------------------------------------------

class TestGroupInviteDecline:
    """Admin invites C; C declines from the buddies page."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Hal", last_name="DecAdmin")
        c = setup_user(None, None, first_name="Clara", last_name="Decliner")
        group_id = _create_group(a["email"], "Decline Test Group")
        # Create invite directly via shell
        _shell(
            f"from buddies.services import BuddyGroupService; "
            f"from feusers.models import FeUser; from buddies.models import BuddyGroup; "
            f"admin = FeUser.objects.get(email='{a['email']}'); "
            f"g = BuddyGroup.objects.get(pk={group_id}); "
            f"BuddyGroupService.invite_member(g, admin, '{c['email']}')"
        )
        yield {"a": a, "c": c, "group_id": int(group_id)}
        cleanup_user(a["email"])
        cleanup_user(c["email"])

    def test_c_sees_group_invite(self, driver, w, ctx):
        _login_as(driver, ctx["c"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Decline Test Group" in driver.page_source

    def test_c_clicks_view_invite(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR,
            ".invite-card a[href*='group-invite']").click()
        time.sleep(1)
        assert "Decline Test Group" in driver.page_source

    def test_c_declines_group_invite(self, driver, w, ctx):
        driver.find_element(By.ID, "btn-decline-group-invite").click()
        time.sleep(1)
        assert "/buddies/" in driver.current_url

    def test_c_not_in_group_after_decline(self, driver, w, ctx):
        count = _shell(
            f"from buddies.models import BuddyGroupMember; "
            f"from feusers.models import FeUser; "
            f"c = FeUser.objects.get(email='{ctx['c']['email']}'); "
            f"print(BuddyGroupMember.objects.filter(feuser=c, group_id={ctx['group_id']}).count())"
        )
        assert count == "0"


# ---------------------------------------------------------------------------
# Revoke pending group invite
# ---------------------------------------------------------------------------

class TestGroupInviteRevoke:
    """Admin revokes a pending group invite before C responds."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Ivan", last_name="RevAdmin")
        c = setup_user(None, None, first_name="Cleo", last_name="RevokeTarget")
        group_id = _create_group(a["email"], "Revoke Test Group")
        _shell(
            f"from buddies.services import BuddyGroupService; "
            f"from feusers.models import FeUser; from buddies.models import BuddyGroup; "
            f"admin = FeUser.objects.get(email='{a['email']}'); "
            f"g = BuddyGroup.objects.get(pk={group_id}); "
            f"BuddyGroupService.invite_member(g, admin, '{c['email']}')"
        )
        yield {"a": a, "c": c, "group_id": int(group_id)}
        cleanup_user(a["email"])
        cleanup_user(c["email"])

    def test_pending_invite_shown(self, driver, w, ctx):
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        assert ctx["c"]["email"] in driver.page_source

    def test_admin_revokes_invite(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR, "[id^='btn-revoke-group-invite-']").click()
        time.sleep(1)
        assert ctx["c"]["email"] not in driver.page_source


# ---------------------------------------------------------------------------
# Error: self-invite and already-member invite
# ---------------------------------------------------------------------------

class TestGroupInviteErrors:
    """Error messages for self-invite and duplicate member invite."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Ella", last_name="ErrAdmin")
        c = setup_user(None, None, first_name="Chuck", last_name="ErrMember")
        group_id = _create_group(a["email"], "Error Test Group")
        _add_group_member(int(group_id), c["email"])
        yield {"a": a, "c": c, "group_id": int(group_id)}
        cleanup_user(a["email"])
        cleanup_user(c["email"])

    def test_self_invite_shows_error(self, driver, w, ctx):
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        inp = driver.find_element(By.CSS_SELECTOR,
            "form[action*='invite'] input[name='email']")
        inp.clear()
        inp.send_keys(ctx["a"]["email"])
        driver.find_element(By.ID, "btn-group-invite").click()
        time.sleep(1)
        assert "cannot invite yourself" in driver.page_source.lower()

    def test_already_member_invite_shows_info(self, driver, w, ctx):
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        inp = driver.find_element(By.CSS_SELECTOR,
            "form[action*='invite'] input[name='email']")
        inp.clear()
        inp.send_keys(ctx["c"]["email"])
        driver.find_element(By.ID, "btn-group-invite").click()
        time.sleep(1)
        assert "already a member" in driver.page_source.lower()


# ---------------------------------------------------------------------------
# Add and remove group dummy
# ---------------------------------------------------------------------------

class TestGroupDummyManagement:
    """Admin adds group dummy; admin removes group dummy."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Deb", last_name="DummyAdmin")
        group_id = _create_group(a["email"], "Dummy Mgmt Group")
        yield {"a": a, "group_id": int(group_id)}
        cleanup_user(a["email"])

    def test_add_group_dummy(self, driver, w, ctx):
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        inp = driver.find_element(By.CSS_SELECTOR,
            "form[action*='add-dummy'] input[name='display_name']")
        inp.clear()
        inp.send_keys("Group Offline Member")
        driver.find_element(By.ID, "btn-group-add-dummy").click()
        time.sleep(1)
        assert "Group Offline Member" in driver.page_source

    def test_remove_group_dummy(self, driver, w, ctx):
        dummy_card = driver.find_element(By.CSS_SELECTOR, ".buddy-card-dummy")
        dummy_card.find_element(By.CSS_SELECTOR, "a[href*='remove']").click()
        time.sleep(1)
        assert "remove" in driver.current_url
        driver.find_element(By.ID, "btn-confirm-kick").click()
        time.sleep(1)
        assert "Group Offline Member" not in driver.page_source


# ---------------------------------------------------------------------------
# Remove feuser member (ghost dummy created)
# ---------------------------------------------------------------------------

class TestGroupRemoveMember:
    """Admin removes feuser member C; ghost dummy appears in member list."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Moe", last_name="RemAdmin")
        c = setup_user(None, None, first_name="Cian", last_name="Removeable")
        group_id = _create_group(a["email"], "Remove Member Group")
        _add_group_member(int(group_id), c["email"])
        yield {"a": a, "c": c, "group_id": int(group_id)}
        cleanup_user(a["email"])
        cleanup_user(c["email"])

    def test_c_in_member_list(self, driver, w, ctx):
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        assert ctx["c"]["email"] in driver.page_source

    def test_remove_c_shows_confirm(self, driver, w, ctx):
        # The remove form is inside the member card for C (feuser_members loop)
        member_card = driver.find_elements(By.CSS_SELECTOR, ".buddy-card:not(.buddy-card-dummy)")
        remove_btn = None
        for card in member_card:
            if ctx["c"]["email"] in card.text:
                remove_btn = card.find_element(By.CSS_SELECTOR, "[id^='btn-remove-member-']")
                break
        assert remove_btn is not None, "Remove button not found for member C"
        remove_btn.click()
        time.sleep(0.5)
        assert driver.find_element(By.ID, "cdialog-ok").is_displayed()

    def test_confirm_removes_c(self, driver, w, ctx):
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(1)
        assert ctx["c"]["email"] not in driver.page_source

    def test_ghost_dummy_appears(self, driver, w, ctx):
        # Ghost dummy has C's display name and "Offline" pill
        assert "Cian Removeable" in driver.page_source, \
            "Ghost dummy with removed member's name must appear"
        assert "Offline" in driver.page_source


# ---------------------------------------------------------------------------
# Transfer admin rights
# ---------------------------------------------------------------------------

class TestGroupTransferAdmin:
    """Admin transfers rights to another member; roles swap in the UI."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Tara", last_name="TransAdmin")
        c = setup_user(None, None, first_name="Ned", last_name="NewAdmin")
        group_id = _create_group(a["email"], "Transfer Admin Group")
        _add_group_member(int(group_id), c["email"])
        _create_buddy_link(a["email"], c["email"])
        c_pk = int(_get_pk(c["email"]))
        yield {"a": a, "c": c, "group_id": int(group_id), "c_pk": c_pk}
        cleanup_user(a["email"])
        cleanup_user(c["email"])

    def test_admin_selects_new_admin_and_transfers(self, driver, w, ctx):
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        sel = Select(driver.find_element(By.CSS_SELECTOR, "select[name='new_admin_id']"))
        sel.select_by_value(str(ctx["c_pk"]))
        driver.find_element(By.ID, "btn-transfer-admin").click()
        _confirm(driver)
        assert "/buddies/groups/" in driver.current_url

    def test_old_admin_no_longer_sees_admin_ui(self, driver, w, ctx):
        assert "Transfer admin rights" not in driver.page_source
        assert "Dissolve group" not in driver.page_source

    def test_new_admin_sees_admin_ui(self, driver, w, ctx):
        _login_as(driver, ctx["c"])
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        assert "You are admin" in driver.page_source or "Admin" in driver.page_source
        assert "Transfer admin rights" in driver.page_source


# ---------------------------------------------------------------------------
# Leave group (non-admin member)
# ---------------------------------------------------------------------------

class TestGroupLeave:
    """Non-admin C leaves the group; flash message shown; group gone from C's list."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Lou", last_name="StayAdmin")
        c = setup_user(None, None, first_name="Lea", last_name="Leaver")
        group_id = _create_group(a["email"], "Leave Test Group")
        _add_group_member(int(group_id), c["email"])
        _create_buddy_link(a["email"], c["email"])
        yield {"a": a, "c": c, "group_id": int(group_id)}
        cleanup_user(a["email"])
        cleanup_user(c["email"])

    def test_c_can_see_leave_button(self, driver, w, ctx):
        _login_as(driver, ctx["c"])
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Leave group" in driver.page_source

    def test_c_leaves_group(self, driver, w, ctx):
        driver.find_element(By.ID, "btn-leave-group").click()
        _confirm(driver)
        assert "/buddies/" in driver.current_url

    def test_flash_message_after_leave(self, driver, w, ctx):
        assert "You have left the group" in driver.page_source

    def test_group_gone_from_c_list(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Leave Test Group" not in driver.page_source

    def test_admin_cannot_see_leave_button(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Leave group" not in driver.page_source


# ---------------------------------------------------------------------------
# Dissolve group
# ---------------------------------------------------------------------------

class TestGroupDissolve:
    """Admin dissolves group; group disappears; admin returns to /buddies/."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Dave", last_name="Dissolver")
        group_id = _create_group(a["email"], "Dissolve Test Group")
        yield {"a": a, "group_id": int(group_id)}
        cleanup_user(a["email"])

    def test_dissolve_group(self, driver, w, ctx):
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        driver.find_element(By.ID, "btn-dissolve-group").click()
        _confirm(driver)
        assert "/buddies/" in driver.current_url

    def test_flash_message_after_dissolve(self, driver, w, ctx):
        assert "dissolved" in driver.page_source.lower()

    def test_group_gone_from_my_buddies(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Dissolve Test Group" not in driver.page_source


# ---------------------------------------------------------------------------
# Group expense breakdown
# ---------------------------------------------------------------------------

class TestGroupBreakdown:
    """Group expense: breakdown table and debt settlement shown on detail page."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Faye", last_name="PayerAdmin")
        b = setup_user(None, None, first_name="Neil", last_name="Debtor")
        group_id = _create_group(a["email"], "Breakdown Group")
        _add_group_member(int(group_id), b["email"])
        _create_buddy_link(a["email"], b["email"])
        # A pays 100; B owes 50%
        _create_group_expense(
            admin_email=a["email"],
            participant_email=b["email"],
            group_id=int(group_id),
            title="Breakdown Expense",
            value="100.00",
            share="50.0",
        )
        yield {"a": a, "b": b, "group_id": int(group_id)}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_expense_in_breakdown_table(self, driver, w, ctx):
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Breakdown Expense" in driver.page_source, \
            "Group expense must appear in the Expense Breakdown section"

    def test_settlement_row_visible(self, driver, w, ctx):
        assert "owes" in driver.page_source, \
            "A settlement 'owes' row must be shown"

    def test_settlement_amount_correct(self, driver, w, ctx):
        assert "50.00" in driver.page_source, \
            "Settlement amount (50.00) must appear on the group detail page"

    def test_d3_graph_rendered(self, driver, w, ctx):
        # The group page renders two D3 graphs: raw expense flows and simplified.
        svg_elements = driver.find_elements(By.CSS_SELECTOR, "#raw-debt-graph svg, #simplified-debt-graph svg")
        assert len(svg_elements) >= 1, "D3 graph SVG must be rendered when debts exist"


# ---------------------------------------------------------------------------
# Group expense creation via UI (req 3.7)
# ---------------------------------------------------------------------------

class TestGroupExpenseCreateUI:
    """Create a group expense entirely through the expense form UI.

    Verifies group mode is selectable, members become participants, and the
    saved expense appears in the group breakdown.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Gina", last_name="GroupPayer")
        b = setup_user(None, None, first_name="Gino", last_name="GroupMember")
        group_id = _create_group(a["email"], "UI Expense Group")
        _add_group_member(int(group_id), b["email"])
        _create_buddy_link(a["email"], b["email"])
        ctx = {"a": a, "b": b, "group_id": int(group_id)}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_group_mode_radio_visible(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        driver.find_element(By.ID, "buddy-payment-cb").click()
        time.sleep(0.5)
        radios = driver.find_elements(By.ID, "buddy-mode-group")
        assert len(radios) == 1, "Group mode radio button must exist in the buddy payment section"

    def test_select_group_mode_and_group(self, driver, w, ctx):
        driver.find_element(By.ID, "buddy-mode-group").click()
        time.sleep(0.4)
        group_sel = driver.find_element(By.ID, "buddy-group-select")
        Select(group_sel).select_by_value(str(ctx["group_id"]))
        time.sleep(0.5)
        # At least one participant checkbox should appear (group member, excluding me)
        cbs = driver.find_elements(By.CSS_SELECTOR,
            "#buddy-participants-checkboxes input[type=checkbox]")
        assert len(cbs) >= 1, "Group member checkboxes must appear after selecting group"

    def test_equal_split_and_save(self, driver, w, ctx):
        today = server_today()
        driver.find_element(By.ID, "id_title").clear()
        driver.find_element(By.ID, "id_title").send_keys("UI Group Expense")
        driver.find_element(By.ID, "id_value").clear()
        driver.find_element(By.ID, "id_value").send_keys("100.00")
        driver.execute_script(
            f"document.getElementById('id_date_due').value = '{today}';"
        )
        # Check all member checkboxes
        cbs = driver.find_elements(By.CSS_SELECTOR,
            "#buddy-participants-checkboxes input[type=checkbox]")
        for cb in cbs:
            if not cb.is_selected():
                cb.click()
        time.sleep(0.3)
        driver.find_element(By.ID, "buddy-equal-btn").click()
        time.sleep(0.3)
        driver.find_element(By.XPATH, "//button[contains(text(), 'Create expense')]").click()
        time.sleep(2)
        assert "/budget/expenses/" in driver.current_url, \
            "Group expense (I pay) must redirect to expense list"

    def test_expense_appears_in_group_breakdown(self, driver, w, ctx):
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        assert "UI Group Expense" in driver.page_source, \
            "Group expense created via UI must appear in the group breakdown"
