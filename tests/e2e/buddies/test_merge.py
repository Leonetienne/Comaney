"""
Dummy-to-user merge flows: personal dummy merge and group dummy merge.

Personal merge: A has a dummy, sends merge invite to B, B accepts or declines.
Group merge: Admin has a group dummy, sends merge invite to C, C accepts.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import (
    _url, setup_user, cleanup_user,
    fetch_email, extract_link, mailpit_seen_ids,
)
from bhelpers import (
    _shell, _login_as, _create_buddy_link, _get_pk, _create_group,
)


# ---------------------------------------------------------------------------
# Personal dummy merge: B accepts
# ---------------------------------------------------------------------------

class TestPersonalDummyMergeAccept:
    """A has a dummy 'Merge Buddy'; A sends merge invite to B; B accepts."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Alice", last_name="Merger")
        b = setup_user(None, None, first_name="Bob", last_name="Mergee")
        dummy_uid = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Merge Buddy'); "
            f"print(d.uid)"
        )
        # Create an expense for A where the dummy is participant; must transfer to B after merge
        _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import BuddySpending, DummyUser; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"import datetime; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d = DummyUser.objects.get(uid='{dummy_uid.strip()}'); "
            f"e = Expense.objects.create(owning_feuser=u, title='Merge History Expense', "
            f"  type='expense', value=Decimal('100.00'), "
            f"  date_due=datetime.date.today(), settled=False, buddy_approved=True); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=d, "
            f"  share_percent=Decimal('50'))"
        )
        ctx = {"a": a, "b": b, "dummy_uid": dummy_uid.strip()}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_invite_as_user_button_visible(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        buttons = driver.find_elements(By.XPATH,
            "//*[contains(text(),'Invite as user')]")
        assert len(buttons) >= 1, "Invite as user button must be visible for personal dummy"

    def test_a_sends_merge_invite(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before"] = seen_before
        # Click "Invite as user" to reveal the hidden form
        invite_btn = driver.find_element(By.XPATH,
            "//*[contains(text(),'Invite as user')]")
        invite_btn.click()
        time.sleep(0.3)
        # Fill in B's email and submit
        merge_form = driver.find_element(
            By.CSS_SELECTOR,
            f"#merge-form-{ctx['dummy_uid']}",
        )
        merge_form.find_element(By.CSS_SELECTOR, "input[name='email']").send_keys(ctx["b"]["email"])
        merge_form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        time.sleep(1)
        assert "/buddies/" in driver.current_url

    def test_merge_invite_email_arrives(self, driver, w, ctx):
        body = fetch_email(
            ctx["b"]["email"],
            "link your account with their buddy record",
            ignore_ids=ctx.get("seen_before"),
        )
        ctx["merge_link"] = extract_link(body)
        assert "/buddies/merge/" in ctx["merge_link"]

    def test_b_sees_merge_invite_page(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(ctx["merge_link"])
        time.sleep(1)
        assert "Merge Buddy" in driver.page_source
        assert "Accept and merge" in driver.page_source

    def test_b_accepts_merge(self, driver, w, ctx):
        driver.find_element(By.ID, "btn-accept-merge").click()
        time.sleep(1)
        assert "/buddies/" in driver.current_url

    def test_b_sees_a_as_buddy_after_merge(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert ctx["a"]["email"] in driver.page_source

    def test_b_sees_transferred_expense_on_summary(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Merge History Expense" in driver.page_source, \
            "Expense previously tracked under the dummy must transfer to B after merge"

    def test_a_sees_b_not_dummy_after_merge(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert ctx["b"]["email"] in driver.page_source, \
            "After merge, A must see B as a real buddy"
        assert "Merge Buddy" not in driver.page_source, \
            "The dummy must be gone after merge"


# ---------------------------------------------------------------------------
# Personal dummy merge: B declines
# ---------------------------------------------------------------------------

class TestPersonalDummyMergeDecline:
    """A has a dummy; merge invite is sent via shell; B declines."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Dana", last_name="Decliner")
        b = setup_user(None, None, first_name="Eve", last_name="Decliner")
        # Create dummy and merge invite via shell to avoid email overhead
        dummy_uid = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Decline Dummy'); "
            f"print(d.uid)"
        )
        token = _shell(
            f"from buddies.models import DummyUser, DummyMergeInvite; "
            f"from feusers.models import FeUser; "
            f"import uuid; "
            f"from django.utils import timezone; "
            f"import datetime; "
            f"a = FeUser.objects.get(email='{a['email']}'); "
            f"b = FeUser.objects.get(email='{b['email']}'); "
            f"dummy = DummyUser.objects.get(uid='{dummy_uid.strip()}'); "
            f"inv = DummyMergeInvite.objects.create("
            f"  inviting_feuser=a, dummy=dummy, invited_feuser=b, "
            f"  expires_at=timezone.now() + datetime.timedelta(days=7)); "
            f"print(inv.token)"
        )
        ctx = {"a": a, "b": b, "token": token.strip(), "dummy_uid": dummy_uid.strip()}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_b_sees_merge_invite_page(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url(f"/buddies/merge/{ctx['token']}/"))
        time.sleep(1)
        assert "Decline Dummy" in driver.page_source
        assert "Decline" in driver.page_source

    def test_b_declines_merge(self, driver, w, ctx):
        driver.find_element(By.ID, "btn-decline-merge").click()
        time.sleep(1)
        assert "/buddies/" in driver.current_url

    def test_no_buddy_link_after_decline(self, driver, w, ctx):
        count = _shell(
            f"from buddies.models import BuddyLink; "
            f"from feusers.models import FeUser; "
            f"from django.db.models import Q; "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"print(BuddyLink.objects.filter(Q(user_a=a,user_b=b)|Q(user_a=b,user_b=a)).count())"
        )
        assert count == "0", "No BuddyLink must exist after decline"

    def test_dummy_still_exists_for_a(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Decline Dummy" in driver.page_source, \
            "Dummy must still be present on A's page after B declines"


# ---------------------------------------------------------------------------
# Group dummy merge: C accepts
# ---------------------------------------------------------------------------

class TestGroupDummyMergeAccept:
    """Admin sends merge invite for a group dummy to C; C accepts and joins the group."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Greg", last_name="GroupAdmin")
        c = setup_user(None, None, first_name="Clara", last_name="GroupJoiner")
        group_id = _create_group(admin["email"], "MergeGroup")
        # Add a group dummy
        dummy_uid = _shell(
            f"from buddies.models import DummyUser, BuddyGroup, BuddyGroupMember; "
            f"g = BuddyGroup.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='Group Dummy'); "
            f"BuddyGroupMember.objects.create(group=g, dummy=d); "
            f"print(d.uid)"
        )
        ctx = {
            "admin": admin, "c": c,
            "group_id": group_id,
            "dummy_uid": dummy_uid.strip(),
        }
        yield ctx
        cleanup_user(admin["email"])
        cleanup_user(c["email"])

    def test_invite_as_user_button_visible_on_group_detail(self, driver, w, ctx):
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        buttons = driver.find_elements(By.XPATH,
            "//*[contains(text(),'Invite as user')]")
        assert len(buttons) >= 1, "Invite as user button must appear for group dummy (admin)"

    def test_admin_sends_group_merge_invite(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before"] = seen_before
        invite_btn = driver.find_element(By.XPATH,
            "//*[contains(text(),'Invite as user')]")
        invite_btn.click()
        time.sleep(0.3)
        merge_form = driver.find_element(
            By.CSS_SELECTOR,
            f"#merge-form-{ctx['dummy_uid']}",
        )
        merge_form.find_element(By.CSS_SELECTOR, "input[name='email']").send_keys(ctx["c"]["email"])
        merge_form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        time.sleep(1)
        assert "Merge invitation sent" in driver.page_source or \
               "/buddies/groups/" in driver.current_url

    def test_group_merge_email_arrives(self, driver, w, ctx):
        body = fetch_email(
            ctx["c"]["email"],
            "add you to the group",
            ignore_ids=ctx.get("seen_before"),
        )
        ctx["merge_link"] = extract_link(body)
        assert "/buddies/merge/" in ctx["merge_link"]

    def test_c_sees_group_merge_page(self, driver, w, ctx):
        _login_as(driver, ctx["c"])
        driver.get(ctx["merge_link"])
        time.sleep(1)
        assert "MergeGroup" in driver.page_source
        assert "Group Dummy" in driver.page_source
        assert "Accept and merge" in driver.page_source

    def test_c_accepts_group_merge(self, driver, w, ctx):
        driver.find_element(By.ID, "btn-accept-merge").click()
        time.sleep(1)
        assert "/buddies/" in driver.current_url

    def test_c_is_member_after_merge(self, driver, w, ctx):
        driver.get(_url(f"/buddies/groups/{ctx['group_id']}/"))
        time.sleep(1)
        assert ctx["c"]["email"] in driver.page_source or \
               "Clara GroupJoiner" in driver.page_source, \
            "C must appear as a group member after accepting the group merge"

    def test_group_dummy_gone_after_merge(self, driver, w, ctx):
        assert "Group Dummy" not in driver.page_source, \
            "The group dummy must be replaced by C's real account after merge"
