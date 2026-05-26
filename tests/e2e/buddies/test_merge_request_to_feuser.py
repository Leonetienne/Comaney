"""
Personal offline-buddy-into-real-buddy merge requests: requires the target's approval.
Only an already-linked direct buddy can be selected as a target.
"""
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from helpers import _url, setup_user, cleanup_user, fetch_email, extract_link, mailpit_seen_ids
from bhelpers import _shell, _login_as, _confirm, _create_buddy_link, _get_pk


# ---------------------------------------------------------------------------
# Only already-linked buddies appear as merge targets
# ---------------------------------------------------------------------------

class TestPersonalMergeRequestOnlyListsLinkedBuddies:
    """A dummy's target dropdown lists B (already a buddy) but not C (not yet a buddy)."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Lena", last_name="Requester")
        b = setup_user(None, None, first_name="Beth", last_name="Linked")
        c = setup_user(None, None, first_name="Cara", last_name="Unlinked")
        _create_buddy_link(a["email"], b["email"])
        dummy_uid = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Pickable Dummy'); "
            f"print(d.uid)"
        )
        ctx = {"a": a, "b": b, "c": c, "dummy_uid": dummy_uid.strip(), "b_pk": _get_pk(b["email"]), "c_pk": _get_pk(c["email"])}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])
        cleanup_user(c["email"])

    def test_only_linked_buddy_is_a_candidate(self, driver, w, ctx):
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        select_el = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['dummy_uid']} select[name='target_key']")
        values = [o.get_attribute("value") for o in select_el.find_elements(By.TAG_NAME, "option")]
        assert f"f{ctx['b_pk']}" in values, "Already-linked buddy B must be a candidate"
        assert f"f{ctx['c_pk']}" not in values, "Unlinked user C must not be a candidate"


# ---------------------------------------------------------------------------
# Sender can revoke an outgoing merge request before the target responds
# ---------------------------------------------------------------------------

class TestPersonalMergeRequestRevoke:
    """A sends a merge request to B; A revokes it before B responds."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Wade", last_name="Requester")
        b = setup_user(None, None, first_name="Xander", last_name="Pending")
        _create_buddy_link(a["email"], b["email"])
        dummy_uid = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Revoke Dummy'); "
            f"print(d.uid)"
        )
        ctx = {"a": a, "b": b, "dummy_uid": dummy_uid.strip(), "b_pk": _get_pk(b["email"])}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_a_sends_request(self, driver, w, ctx):
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['dummy_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['dummy_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"f{ctx['b_pk']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)

    def test_a_sees_sent_request_and_revokes(self, driver, w, ctx):
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        assert "Merge requests you sent" in driver.page_source
        assert "Revoke Dummy" in driver.page_source
        token = _shell(
            f"from buddies.models import DummyMergeInvite, DummyUser; "
            f"d = DummyUser.objects.get(uid={ctx['dummy_uid']}); "
            f"print(DummyMergeInvite.objects.get(dummy=d).token)"
        ).strip()
        driver.find_element(By.ID, f"btn-revoke-merge-{token}").click()
        time.sleep(1)
        assert "/buddies/" in driver.current_url

    def test_invite_gone_dummy_untouched(self, driver, w, ctx):
        count = _shell(
            f"from buddies.models import DummyMergeInvite, DummyUser; "
            f"d = DummyUser.objects.get(uid={ctx['dummy_uid']}); "
            f"print(DummyMergeInvite.objects.filter(dummy=d).count())"
        )
        assert count == "0", "Revoked invite must be gone"
        exists = _shell(
            f"from buddies.models import DummyUser; print(DummyUser.objects.filter(uid={ctx['dummy_uid']}).exists())"
        )
        assert exists == "True", "Dummy must still exist after revoke, untouched"


# ---------------------------------------------------------------------------
# A second merge request for the same dummy is blocked while one is pending
# ---------------------------------------------------------------------------

class TestPersonalMergeRequestBlocksDuplicate:
    """A sends a merge request to B; sending another for the same dummy to C
    (also already a buddy) must be blocked until the first is resolved."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Yara", last_name="Requester")
        b = setup_user(None, None, first_name="Zeke", last_name="FirstTarget")
        c = setup_user(None, None, first_name="Amir", last_name="SecondTarget")
        _create_buddy_link(a["email"], b["email"])
        _create_buddy_link(a["email"], c["email"])
        dummy_uid = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Duplicate Dummy'); "
            f"print(d.uid)"
        )
        ctx = {
            "a": a, "b": b, "c": c, "dummy_uid": dummy_uid.strip(),
            "b_pk": _get_pk(b["email"]), "c_pk": _get_pk(c["email"]),
        }
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])
        cleanup_user(c["email"])

    def test_first_request_succeeds(self, driver, w, ctx):
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['dummy_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['dummy_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"f{ctx['b_pk']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)
        assert "Merge request sent" in driver.page_source

    def test_second_request_is_blocked(self, driver, w, ctx):
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['dummy_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['dummy_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"f{ctx['c_pk']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)
        assert "pending merge request" in driver.page_source.lower()
        count = _shell(
            f"from buddies.models import DummyMergeInvite, DummyUser; "
            f"d = DummyUser.objects.get(uid={ctx['dummy_uid']}); "
            f"print(DummyMergeInvite.objects.filter(dummy=d).count())"
        )
        assert count == "1", "Only the first invite must exist"


# ---------------------------------------------------------------------------
# Send a merge request, B accepts
# ---------------------------------------------------------------------------

class TestPersonalMergeRequestAcceptFlow:
    """A and B are already buddies. A requests merging a dummy's history into B; B accepts."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Fay", last_name="Requester")
        b = setup_user(None, None, first_name="Glen", last_name="Approver")
        _create_buddy_link(a["email"], b["email"])
        dummy_uid = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Request Dummy'); "
            f"print(d.uid)"
        )
        dummy_uid = dummy_uid.strip()
        _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import BuddySpending, DummyUser; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d = DummyUser.objects.get(uid={dummy_uid}); "
            f"e = Expense.objects.create(owning_feuser=u, title='Request Merge Expense', "
            f"  type='expense', value=Decimal('70.00'), settled=False, buddy_approved=True); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=d, share_percent=Decimal('50'))"
        )
        ctx = {"a": a, "b": b, "dummy_uid": dummy_uid, "b_pk": _get_pk(b["email"])}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_a_sends_merge_request_to_b(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        ctx["seen_before"] = seen_before
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['dummy_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['dummy_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"f{ctx['b_pk']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)
        assert "Merge request sent" in driver.page_source

    def test_dummy_still_present_for_a_until_accepted(self, driver, w, ctx):
        assert "Request Dummy" in driver.page_source

    def test_merge_request_email_arrives(self, driver, w, ctx):
        body = fetch_email(
            ctx["b"]["email"],
            "link your account with their buddy record",
            ignore_ids=ctx.get("seen_before"),
        )
        ctx["merge_link"] = extract_link(body)
        assert "/buddies/merge/" in ctx["merge_link"]

    def test_b_sees_navbar_bell_and_pending_card(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        bell = driver.find_elements(By.ID, "notif-badge")
        assert bell and int(bell[0].text.strip()) >= 1, "B's navbar bell must show at least one notification"
        assert "Offline record link requests" in driver.page_source
        assert "Request Dummy" in driver.page_source

    def test_b_accepts_merge_request(self, driver, w, ctx):
        driver.get(ctx["merge_link"])
        time.sleep(1)
        driver.find_element(By.ID, "btn-accept-merge").click()
        time.sleep(1)
        assert "/buddies/" in driver.current_url

    def test_dummy_gone_history_transferred_no_duplicate_link(self, driver, w, ctx):
        gone = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['dummy_uid']}).count())"
        )
        assert gone == "0"
        link_count = _shell(
            f"from buddies.models import BuddyLink; from feusers.models import FeUser; "
            f"from django.db.models import Q; "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"print(BuddyLink.objects.filter(Q(user_a=a,user_b=b)|Q(user_a=b,user_b=a)).count())"
        )
        assert link_count == "1", "Accepting must not create a duplicate BuddyLink for an already-linked buddy"
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Request Merge Expense" in driver.page_source


# ---------------------------------------------------------------------------
# Merging a dummy into an already-linked buddy who is ALSO already an explicit
# co-participant on the same expense: shares must sum into one row, not
# duplicate. anna 10%, frank 20%, mario 35%, tom 35% -> anna 10, frank 20, tom 70.
# ---------------------------------------------------------------------------

class TestMergeRequestSumsConflictingCoParticipantShares:
    """A owns an expense split between her dummies anna/frank/mario and her
    already-linked real buddy tom. Requesting a merge of mario into tom, and
    tom accepting, must combine mario's and tom's shares into a single row."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Sven", last_name="Owner")
        tom = setup_user(None, None, first_name="Tomas", last_name="Approver")
        _create_buddy_link(a["email"], tom["email"])
        ids = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"anna = DummyUser.objects.create(owning_feuser=u, display_name='Anna Co'); "
            f"frank = DummyUser.objects.create(owning_feuser=u, display_name='Frank Co'); "
            f"mario = DummyUser.objects.create(owning_feuser=u, display_name='Mario Co'); "
            f"print(anna.uid, frank.uid, mario.uid)"
        )
        anna_uid, frank_uid, mario_uid = ids.split()
        expense_pk = _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import BuddySpending, DummyUser; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"tom = FeUser.objects.get(email='{tom['email']}'); "
            f"anna = DummyUser.objects.get(uid={anna_uid}); "
            f"frank = DummyUser.objects.get(uid={frank_uid}); "
            f"mario = DummyUser.objects.get(uid={mario_uid}); "
            f"e = Expense.objects.create(owning_feuser=u, title='Four Way Split With Buddy', "
            f"  type='expense', value=Decimal('200.00'), settled=False, buddy_approved=True); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=anna, share_percent=Decimal('10')); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=frank, share_percent=Decimal('20')); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=mario, share_percent=Decimal('35')); "
            f"BuddySpending.objects.create(expense=e, participant_feuser=tom, share_percent=Decimal('35')); "
            f"print(e.pk)"
        )
        sched_pk = _shell(
            f"from budget.models import ScheduledExpense; "
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; from decimal import Decimal; import json; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"tom = FeUser.objects.get(email='{tom['email']}'); "
            f"mario = DummyUser.objects.get(uid={mario_uid}); "
            f"se = ScheduledExpense.objects.create(owning_feuser=u, title='Recurring With Buddy', "
            f"  type='expense', value=Decimal('90.00'), assign_buddy_mode='single', assign_upfront_type='me', "
            f"  assign_spendings_json=json.dumps(["
            f"    {{'type': 'dummy', 'id': mario.uid, 'share_percent': 35.0}},"
            f"    {{'type': 'feuser', 'id': tom.pk, 'share_percent': 35.0}},"
            f"  ])); "
            f"print(se.pk)"
        )
        ctx = {
            "a": a, "tom": tom, "expense_pk": expense_pk.strip(), "sched_pk": sched_pk.strip(),
            "mario_uid": mario_uid, "tom_pk": _get_pk(tom["email"]),
        }
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(tom["email"])

    def test_a_requests_merge_and_tom_accepts(self, driver, w, ctx):
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['mario_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['mario_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"f{ctx['tom_pk']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)

        token = _shell(
            f"from buddies.models import DummyMergeInvite, DummyUser; "
            f"d = DummyUser.objects.get(uid={ctx['mario_uid']}); "
            f"print(DummyMergeInvite.objects.get(dummy=d).token)"
        ).strip()
        _login_as(driver, ctx["tom"])
        driver.get(_url(f"/buddies/merge/{token}/"))
        time.sleep(1)
        driver.find_element(By.ID, "btn-accept-merge").click()
        time.sleep(1)
        assert "/buddies/" in driver.current_url

    def test_expense_not_lost_shares_summed_others_untouched(self, driver, w, ctx):
        assert _shell(
            f"from budget.models import Expense; print(Expense.objects.filter(pk={ctx['expense_pk']}).exists())"
        ) == "True", "The expense itself must not be lost"

        rows = _shell(
            f"from budget.models import Expense; "
            f"e = Expense.objects.get(pk={ctx['expense_pk']}); "
            f"print(chr(10).join(f'{{bs.participant_feuser or bs.participant_dummy}}|{{bs.share_percent}}' for bs in e.buddy_spendings.all()))"
        )
        lines = [l for l in rows.splitlines() if l.strip()]
        shares = {l.split('|')[0]: l.split('|')[1] for l in lines}
        assert len(lines) == 3, \
            f"Expected exactly 3 rows (anna, frank, tom merged once), got: {shares}"
        assert shares.get("Anna Co") == "10.000", shares
        assert shares.get("Frank Co") == "20.000", shares
        assert shares.get(ctx["tom"]["email"]) == "70.000", shares

        mario_gone = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['mario_uid']}).count())"
        )
        assert mario_gone == "0", "Mario must be deleted, with no stale references left behind"
        stale = _shell(
            f"from buddies.models import BuddySpending; "
            f"print(BuddySpending.objects.filter(participant_dummy_id={ctx['mario_uid']}).count())"
        )
        assert stale == "0", "No BuddySpending row may still reference the deleted dummy"

    def test_recurring_schedule_sums_shares_no_stale_reference(self, driver, w, ctx):
        sched_json = _shell(
            f"from budget.models import ScheduledExpense; "
            f"se = ScheduledExpense.objects.get(pk={ctx['sched_pk']}); "
            f"print(se.assign_spendings_json)"
        )
        assert f'"id": {ctx["mario_uid"]}' not in sched_json, \
            f"Recurring schedule must not keep a stale reference to the deleted dummy: {sched_json}"
        assert f'"share_percent": 70.0' in sched_json, \
            f"Recurring schedule must sum mario's and tom's shares into one 70% entry: {sched_json}"


# ---------------------------------------------------------------------------
# Merging an offline buddy who was the UPFRONT PAYER of an expense into an
# already-linked real buddy who already has an explicit (now stale) row on
# that same expense: the stale row must be removed; ownership and the
# implicit owner share must transfer correctly.
# ---------------------------------------------------------------------------

class TestMergeRequestUpfrontPayerBecomesRealOwner:
    """mario (dummy) fronted the cash for an expense. anna (dummy, 30%) and tom
    (real, already a buddy, 30%) are explicit participants; mario's implicit
    share is 40%. Merging mario into tom must: transfer ownership to tom,
    flip is_dummy off, clear upfront_payee_dummy, remove tom's now-stale 30%
    row, and leave only anna's 30% row (tom's new implicit share is 70%)."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Uschi", last_name="Owner")
        tom = setup_user(None, None, first_name="Theo", last_name="Approver")
        _create_buddy_link(a["email"], tom["email"])
        ids = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"mario = DummyUser.objects.create(owning_feuser=u, display_name='Mario Payer'); "
            f"anna = DummyUser.objects.create(owning_feuser=u, display_name='Anna Payer'); "
            f"print(mario.uid, anna.uid)"
        )
        mario_uid, anna_uid = ids.split()
        expense_pk = _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import BuddySpending, DummyUser; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"tom = FeUser.objects.get(email='{tom['email']}'); "
            f"mario = DummyUser.objects.get(uid={mario_uid}); "
            f"anna = DummyUser.objects.get(uid={anna_uid}); "
            f"e = Expense.objects.create(owning_feuser=u, title='Mario Fronted The Cash', "
            f"  type='expense', value=Decimal('100.00'), settled=False, buddy_approved=True, "
            f"  is_dummy=True, upfront_payee_dummy=mario); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=anna, share_percent=Decimal('30')); "
            f"BuddySpending.objects.create(expense=e, participant_feuser=tom, share_percent=Decimal('30')); "
            f"print(e.pk)"
        )
        ctx = {
            "a": a, "tom": tom, "expense_pk": expense_pk.strip(),
            "mario_uid": mario_uid, "tom_pk": _get_pk(tom["email"]),
        }
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(tom["email"])

    def test_a_requests_merge_and_tom_accepts(self, driver, w, ctx):
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['mario_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['mario_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"f{ctx['tom_pk']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)

        token = _shell(
            f"from buddies.models import DummyMergeInvite, DummyUser; "
            f"d = DummyUser.objects.get(uid={ctx['mario_uid']}); "
            f"print(DummyMergeInvite.objects.get(dummy=d).token)"
        ).strip()
        _login_as(driver, ctx["tom"])
        driver.get(_url(f"/buddies/merge/{token}/"))
        time.sleep(1)
        driver.find_element(By.ID, "btn-accept-merge").click()
        time.sleep(1)
        assert "/buddies/" in driver.current_url

    def test_ownership_transferred_stale_row_removed_anna_untouched(self, driver, w, ctx):
        assert _shell(
            f"from budget.models import Expense; print(Expense.objects.filter(pk={ctx['expense_pk']}).exists())"
        ) == "True", "The expense itself must not be lost"

        state = _shell(
            f"from budget.models import Expense; "
            f"e = Expense.objects.get(pk={ctx['expense_pk']}); "
            f"print(e.owning_feuser_id, e.is_dummy, e.upfront_payee_dummy_id)"
        )
        owning_feuser_id, is_dummy, upfront_payee_dummy_id = state.split()
        assert owning_feuser_id == ctx["tom_pk"], "Ownership must transfer to tom"
        assert is_dummy == "False"
        assert upfront_payee_dummy_id == "None"

        rows = _shell(
            f"from budget.models import Expense; "
            f"e = Expense.objects.get(pk={ctx['expense_pk']}); "
            f"print(chr(10).join(f'{{bs.participant_feuser or bs.participant_dummy}}|{{bs.share_percent}}' for bs in e.buddy_spendings.all()))"
        )
        lines = [l for l in rows.splitlines() if l.strip()]
        shares = {l.split('|')[0]: l.split('|')[1] for l in lines}
        assert len(lines) == 1, \
            f"tom's stale self-participation row must be removed once he owns the expense, got: {shares}"
        assert shares.get("Anna Payer") == "30.000", shares
        implied_owner_share = 100 - sum(float(v) for v in shares.values())
        assert implied_owner_share == 70.0, \
            f"tom's implicit owner share must be 70 (his old 30 + mario's implicit 40), got {implied_owner_share}"

        mario_gone = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.filter(uid={ctx['mario_uid']}).count())"
        )
        assert mario_gone == "0", "Mario must be deleted, with no stale references left behind"


# ---------------------------------------------------------------------------
# Send a merge request, B declines
# ---------------------------------------------------------------------------

class TestPersonalMergeRequestDeclineFlow:
    """A and B are already buddies. A requests a merge; B declines; dummy stays with A."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Hana", last_name="Requester")
        b = setup_user(None, None, first_name="Ivo", last_name="Decliner")
        _create_buddy_link(a["email"], b["email"])
        dummy_uid = _shell(
            f"from buddies.models import DummyUser; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Decline Request Dummy'); "
            f"print(d.uid)"
        )
        ctx = {"a": a, "b": b, "dummy_uid": dummy_uid.strip(), "b_pk": _get_pk(b["email"])}
        yield ctx
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_a_sends_merge_request(self, driver, w, ctx):
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        driver.find_element(By.ID, f"merge-btn-{ctx['dummy_uid']}").click()
        time.sleep(0.3)
        form = driver.find_element(By.CSS_SELECTOR, f"#merge-form-{ctx['dummy_uid']}")
        Select(form.find_element(By.CSS_SELECTOR, "select[name='target_key']")).select_by_value(f"f{ctx['b_pk']}")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        _confirm(driver)

    def test_b_declines(self, driver, w, ctx):
        token = _shell(
            f"from buddies.models import DummyMergeInvite, DummyUser; "
            f"d = DummyUser.objects.get(uid={ctx['dummy_uid']}); "
            f"print(DummyMergeInvite.objects.get(dummy=d).token)"
        ).strip()
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        driver.find_element(By.ID, f"btn-decline-merge-{token}").click()
        time.sleep(1)
        assert "/buddies/" in driver.current_url

    def test_dummy_still_exists_for_a(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        assert "Decline Request Dummy" in driver.page_source
