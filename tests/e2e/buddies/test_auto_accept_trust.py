"""
Buddy auto-accept trust (buddies/services/trust.py).

B can switch on "Automatically accept expenses and settlements recorded by A"
for a direct buddy A on My Buddies. From then on, anything A records that
would otherwise wait on B is accepted right away and B only gets an
info email:
  - expenses A logs with B as the upfront payer (direct and in any project,
    as long as A and B are direct buddies),
  - settlements A records paying B back (B = creditor),
  - B's participant approval indicator on expenses A records.
Enabling the trust also accepts A's already-pending entries (never in archived
projects, never legacy rows without a known initiator).

Run: pytest tests/e2e/buddies/test_auto_accept_trust.py -v | tee logfile.log
"""
import json
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import (
    _url, setup_user, cleanup_user, fetch_email, mailpit_seen_ids,
    server_today, run_cmd,
)
from bhelpers import (
    _shell, _login_as, _confirm, _create_buddy_link, _get_pk,
    _create_group, _add_group_member, _create_group_expense,
    _create_personal_expense_with_buddy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_trust(truster_email: str, other_email: str, enabled: bool = True) -> None:
    """Set truster's auto-accept of other's entries directly (no retroactive pass)."""
    _shell(
        f"from feusers.models import FeUser; from buddies.models import BuddyLink; "
        f"t = FeUser.objects.get(email='{truster_email}'); "
        f"o = FeUser.objects.get(email='{other_email}'); "
        f"BuddyLink.between(t, o).set_auto_accepts(t, {enabled})"
    )


def _trust_flag(truster_email: str, other_email: str) -> str:
    """'True'/'False' for the truster's flag, or 'nolink' if they are not buddies."""
    return _shell(
        f"from feusers.models import FeUser; from buddies.models import BuddyLink; "
        f"t = FeUser.objects.get(email='{truster_email}'); "
        f"o = FeUser.objects.get(email='{other_email}'); "
        f"l = BuddyLink.between(t, o); "
        f"print('nolink' if l is None else l.auto_accepts(t))"
    )


def _expense_pk(owner_email: str, title: str) -> int:
    return int(_shell(
        f"from budget.models import Expense; "
        f"print(Expense.objects.filter(owning_feuser__email='{owner_email}', "
        f"title='{title}').latest('uid').pk)"
    ))


def _approved(expense_pk: int) -> str:
    return _shell(
        f"from budget.models import Expense; "
        f"print(Expense.objects.get(pk={expense_pk}).buddy_approved)"
    )


def _initiator(expense_pk: int) -> str:
    return _shell(
        f"from budget.models import Expense; "
        f"e = Expense.objects.get(pk={expense_pk}); "
        f"print(e.initiated_by_feuser.email if e.initiated_by_feuser else 'None')"
    )


def _approval_state(expense_pk: int, participant_email: str) -> str:
    return _shell(
        f"from buddies.models import BuddySpending; "
        f"print(BuddySpending.objects.get(expense_id={expense_pk}, "
        f"participant_feuser__email='{participant_email}').approval_state)"
    )


def _submit_expense_form(driver, *, title, value, upfront_type, upfront_id,
                         spendings, mode="single", project_id="",
                         url="/budget/expenses/new/", date=None):
    """
    Fill the expense form's plain and buddy-widget hidden fields and submit
    natively (form.submit() skips the widget's client-side confirm dialogs,
    which are not what these tests are about).
    """
    driver.get(_url(url))
    time.sleep(1)
    driver.execute_script(
        """
        const [title, value, date, mode, pid, utype, uid, sp] = arguments;
        document.getElementById('id_title').value = title;
        document.getElementById('id_value').value = value;
        document.getElementById('id_type').value = 'expense';
        if (date) document.getElementById('id_date_due').value = date;
        document.getElementById('buddy-payment-cb').checked = true;
        document.getElementById('buddy-mode-input').value = mode;
        document.getElementById('buddy-group-id-input').value = pid;
        document.getElementById('buddy-upfront-type-input').value = utype;
        document.getElementById('buddy-upfront-id-input').value = uid;
        document.getElementById('buddy-spendings-json').value = sp;
        document.getElementById('id_title').closest('form').submit();
        """,
        title, value, date, mode, str(project_id), upfront_type, str(upfront_id),
        json.dumps(spendings),
    )
    time.sleep(2)


def _no_email(to_email: str, subject_fragment: str, ignore_ids) -> bool:
    try:
        fetch_email(to_email, subject_fragment, timeout=5, ignore_ids=ignore_ids)
    except TimeoutError:
        return True
    return False


# ---------------------------------------------------------------------------
# Toggle UI on My Buddies
# ---------------------------------------------------------------------------

class TestAutoAcceptToggle:
    """B switches the trust for A on and off; A sees the label."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Toggle", last_name="Actor")
        b = setup_user(None, None, first_name="Toggle", last_name="Truster")
        link_pk = _create_buddy_link(a["email"], b["email"])
        yield {"a": a, "b": b, "link_pk": link_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def _toggle(self, driver, ctx):
        return driver.find_element(By.ID, f"auto-accept-{ctx['link_pk']}")

    def test_toggle_visible_and_off_by_default(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        assert "Automatically accept expenses and settlements recorded by Toggle Actor" in driver.page_source
        assert not self._toggle(driver, ctx).is_selected()

    def test_enabling_asks_for_confirmation_with_warning(self, driver, w, ctx):
        driver.execute_script("arguments[0].click();", self._toggle(driver, ctx))
        time.sleep(0.5)
        msg = driver.find_element(By.ID, "cdialog-msg").text
        assert "cannot be undone" in msg, f"Dialog must warn about the permanent change, got: {msg!r}"
        assert "Toggle Actor" in msg

    def test_cancel_keeps_it_off(self, driver, w, ctx):
        driver.find_element(By.ID, "cdialog-cancel").click()
        time.sleep(1)
        assert not self._toggle(driver, ctx).is_selected()
        assert _trust_flag(ctx["b"]["email"], ctx["a"]["email"]) == "False"

    def test_ok_saves_it(self, driver, w, ctx):
        driver.execute_script("arguments[0].click();", self._toggle(driver, ctx))
        _confirm(driver)
        time.sleep(1)
        assert "You now automatically accept entries from Toggle Actor" in driver.page_source
        assert _trust_flag(ctx["b"]["email"], ctx["a"]["email"]) == "True"

    def test_stays_on_after_reload(self, driver, w, ctx):
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        assert self._toggle(driver, ctx).is_selected()

    def test_only_one_direction(self, driver, w, ctx):
        assert _trust_flag(ctx["a"]["email"], ctx["b"]["email"]) == "False", \
            "B's trust must not turn on A's trust in the other direction"

    def test_a_sees_label(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        assert "Accepts your entries automatically" in driver.page_source

    def test_b_does_not_see_label(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        assert "Accepts your entries automatically" not in driver.page_source

    def test_disabling_needs_no_confirmation(self, driver, w, ctx):
        driver.execute_script("arguments[0].click();", self._toggle(driver, ctx))
        time.sleep(1.5)
        assert not driver.find_element(By.ID, "cdialog-backdrop").is_displayed()
        assert _trust_flag(ctx["b"]["email"], ctx["a"]["email"]) == "False"

    def test_a_label_gone_after_disabling(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        assert "Accepts your entries automatically" not in driver.page_source


# ---------------------------------------------------------------------------
# Direct buddy expense with B as payer (real UI flow)
# ---------------------------------------------------------------------------

class TestDirectExpenseAutoAccepted:
    """B trusts A; A logs a direct expense paid by B; no approval needed."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Direct", last_name="Actor")
        b = setup_user(None, None, first_name="Direct", last_name="Truster")
        _create_buddy_link(a["email"], b["email"])
        _set_trust(b["email"], a["email"])
        yield {"a": a, "b": b, "b_pk": _get_pk(b["email"])}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_a_creates_expense_with_b_as_payer(self, driver, w, ctx):
        ctx["seen_before"] = mailpit_seen_ids()
        _login_as(driver, ctx["a"])
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        driver.find_element(By.ID, "id_title").clear()
        driver.find_element(By.ID, "id_title").send_keys("Trusted Direct Expense")
        driver.find_element(By.ID, "id_value").clear()
        driver.find_element(By.ID, "id_value").send_keys("80.00")
        driver.execute_script(f"document.getElementById('id_date_due').value = '{server_today()}';")
        driver.find_element(By.ID, "assign-buddy").click()
        time.sleep(0.5)
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
        _confirm(driver)
        time.sleep(1)
        ctx["exp_pk"] = _expense_pk(ctx["b"]["email"], "Trusted Direct Expense")

    def test_expense_is_approved(self, driver, w, ctx):
        assert _approved(ctx["exp_pk"]) == "True"

    def test_initiator_is_a(self, driver, w, ctx):
        assert _initiator(ctx["exp_pk"]) == ctx["a"]["email"]

    def test_b_gets_auto_accepted_email(self, driver, w, ctx):
        body = fetch_email(ctx["b"]["email"], "accepted automatically",
                           ignore_ids=ctx["seen_before"])
        assert "Trusted Direct Expense" in body
        assert "/buddies/my-buddies/" in body, "Email must link to the buddy list to turn it off"

    def test_b_gets_no_approval_request(self, driver, w, ctx):
        assert _no_email(ctx["b"]["email"], "needs your approval", ctx["seen_before"])

    def test_b_sees_no_needs_approval(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Trusted Direct Expense" in driver.page_source
        assert "Needs approval" not in driver.page_source


# ---------------------------------------------------------------------------
# Trust is directional
# ---------------------------------------------------------------------------

class TestTrustIsDirectional:
    """Only A trusts B: an expense A logs with B as payer still needs B's approval."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Wrong", last_name="Way")
        b = setup_user(None, None, first_name="Still", last_name="Asked")
        _create_buddy_link(a["email"], b["email"])
        _set_trust(a["email"], b["email"])
        yield {"a": a, "b": b, "a_pk": _get_pk(a["email"]), "b_pk": _get_pk(b["email"])}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_expense_stays_pending(self, driver, w, ctx):
        seen = mailpit_seen_ids()
        _login_as(driver, ctx["a"])
        _submit_expense_form(
            driver, title="Directional Expense", value="30.00", date=server_today(),
            upfront_type="feuser", upfront_id=ctx["b_pk"],
            spendings=[{"type": "feuser", "id": int(ctx["a_pk"]), "share_percent": 50}],
        )
        pk = _expense_pk(ctx["b"]["email"], "Directional Expense")
        assert _approved(pk) == "False"
        body = fetch_email(ctx["b"]["email"], "needs your approval", ignore_ids=seen)
        assert "Directional Expense" in body


# ---------------------------------------------------------------------------
# Project expenses
# ---------------------------------------------------------------------------

class TestProjectExpenseAutoAccepted:
    """C is admin; A and B are members and direct buddies; B trusts A."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Proj", last_name="Actor")
        b = setup_user(None, None, first_name="Proj", last_name="Truster")
        c = setup_user(None, None, first_name="Proj", last_name="Admin")
        group_id = int(_create_group(c["email"], "Trust Project"))
        _add_group_member(group_id, a["email"])
        _add_group_member(group_id, b["email"])
        _create_buddy_link(a["email"], b["email"])
        _set_trust(b["email"], a["email"])
        yield {"a": a, "b": b, "c": c, "group_id": group_id,
               "a_pk": _get_pk(a["email"]), "b_pk": _get_pk(b["email"]),
               "c_pk": _get_pk(c["email"])}
        for u in (a, b, c):
            cleanup_user(u["email"])

    def test_a_creates_project_expense_paid_by_b(self, driver, w, ctx):
        ctx["seen_before"] = mailpit_seen_ids()
        _login_as(driver, ctx["a"])
        _submit_expense_form(
            driver, title="Trusted Project Expense", value="90.00", date=server_today(),
            mode="group", project_id=ctx["group_id"],
            upfront_type="feuser", upfront_id=ctx["b_pk"],
            spendings=[
                {"type": "feuser", "id": int(ctx["a_pk"]), "share_percent": 33.333},
                {"type": "feuser", "id": int(ctx["c_pk"]), "share_percent": 33.333},
            ],
        )
        ctx["exp_pk"] = _expense_pk(ctx["b"]["email"], "Trusted Project Expense")

    def test_expense_is_approved(self, driver, w, ctx):
        assert _approved(ctx["exp_pk"]) == "True"

    def test_b_gets_auto_accepted_email(self, driver, w, ctx):
        body = fetch_email(ctx["b"]["email"], "accepted automatically",
                           ignore_ids=ctx["seen_before"])
        assert "Trusted Project Expense" in body
        assert "Trust Project" in body

    def test_admin_participant_indicator_untouched(self, driver, w, ctx):
        assert _approval_state(ctx["exp_pk"], ctx["c"]["email"]) == "0", \
            "C does not trust A, so C's approval indicator must stay neutral"

    def test_b_sees_no_waiting_item_on_project(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Trusted Project Expense" in driver.page_source
        assert f"/buddies/expense/{ctx['exp_pk']}/review/" not in driver.page_source


class TestProjectWithoutDirectLinkNotTrusted:
    """A and B share a project but are not direct buddies: no trust is possible."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Nolink", last_name="Actor")
        b = setup_user(None, None, first_name="Nolink", last_name="Member")
        group_id = int(_create_group(a["email"], "No Link Project"))
        _add_group_member(group_id, b["email"])
        yield {"a": a, "b": b, "group_id": group_id,
               "a_pk": _get_pk(a["email"]), "b_pk": _get_pk(b["email"])}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_no_link_means_no_trust(self, driver, w, ctx):
        assert _trust_flag(ctx["b"]["email"], ctx["a"]["email"]) == "nolink"

    def test_project_expense_stays_pending(self, driver, w, ctx):
        seen = mailpit_seen_ids()
        _login_as(driver, ctx["a"])
        _submit_expense_form(
            driver, title="Untrusted Project Expense", value="40.00", date=server_today(),
            mode="group", project_id=ctx["group_id"],
            upfront_type="feuser", upfront_id=ctx["b_pk"],
            spendings=[{"type": "feuser", "id": int(ctx["a_pk"]), "share_percent": 50}],
        )
        pk = _expense_pk(ctx["b"]["email"], "Untrusted Project Expense")
        assert _approved(pk) == "False"
        fetch_email(ctx["b"]["email"], "needs your approval", ignore_ids=seen)


# ---------------------------------------------------------------------------
# Participant approval indicator
# ---------------------------------------------------------------------------

class TestParticipantIndicatorAutoApproved:
    """A pays; B participates and trusts A: B's check mark is set for them."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Indicator", last_name="Actor")
        b = setup_user(None, None, first_name="Indicator", last_name="Truster")
        _create_buddy_link(a["email"], b["email"])
        _set_trust(b["email"], a["email"])
        yield {"a": a, "b": b, "a_pk": _get_pk(a["email"]), "b_pk": _get_pk(b["email"])}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_a_creates_own_expense_with_b(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        _submit_expense_form(
            driver, title="Indicator Expense", value="50.00", date=server_today(),
            upfront_type="me", upfront_id=ctx["a_pk"],
            spendings=[{"type": "feuser", "id": int(ctx["b_pk"]), "share_percent": 50}],
        )
        ctx["exp_pk"] = _expense_pk(ctx["a"]["email"], "Indicator Expense")
        assert _approval_state(ctx["exp_pk"], ctx["b"]["email"]) == "1"

    def test_reset_by_edit_is_approved_again(self, driver, w, ctx):
        _submit_expense_form(
            driver, title="Indicator Expense", value="70.00",
            url=f"/budget/expenses/{ctx['exp_pk']}/edit/",
            upfront_type="me", upfront_id=ctx["a_pk"],
            spendings=[{"type": "feuser", "id": int(ctx["b_pk"]), "share_percent": 50}],
        )
        assert _approval_state(ctx["exp_pk"], ctx["b"]["email"]) == "1", \
            "A value change resets approvals, but B trusts A so it must be approved again"


# ---------------------------------------------------------------------------
# Payer change on edit
# ---------------------------------------------------------------------------

class TestPayerChangeOnEditAutoAccepted:
    """A edits their own expense and makes B the payer; B trusts A."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Edit", last_name="Actor")
        b = setup_user(None, None, first_name="Edit", last_name="Truster")
        _create_buddy_link(a["email"], b["email"])
        b_pk = int(_get_pk(b["email"]))
        exp_pk = int(_create_personal_expense_with_buddy(
            owner_email=a["email"], participant_pk=b_pk,
            title="Payer Change Expense", value="60.00", share="50.0",
        ))
        _set_trust(b["email"], a["email"])
        yield {"a": a, "b": b, "a_pk": _get_pk(a["email"]), "b_pk": b_pk, "exp_pk": exp_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_change_payer_to_b(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        # The shell-created expense has no date_due, which the form requires.
        _submit_expense_form(
            driver, title="Payer Change Expense", value="60.00", date=server_today(),
            url=f"/budget/expenses/{ctx['exp_pk']}/edit/",
            upfront_type="feuser", upfront_id=ctx["b_pk"],
            spendings=[{"type": "feuser", "id": int(ctx["a_pk"]), "share_percent": 50}],
        )
        assert _shell(
            f"from budget.models import Expense; "
            f"print(Expense.objects.get(pk={ctx['exp_pk']}).owning_feuser.email)"
        ) == ctx["b"]["email"]

    def test_expense_is_approved(self, driver, w, ctx):
        assert _approved(ctx["exp_pk"]) == "True"
        assert _initiator(ctx["exp_pk"]) == ctx["a"]["email"]


# ---------------------------------------------------------------------------
# Scheduled expenses
# ---------------------------------------------------------------------------

class TestScheduledExpenseAutoAccepted:
    """A's recurring expense is paid by B; generated occurrences need no approval."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Sched", last_name="Actor")
        b = setup_user(None, None, first_name="Sched", last_name="Truster")
        _create_buddy_link(a["email"], b["email"])
        _set_trust(b["email"], a["email"])
        a_pk = int(_get_pk(a["email"]))
        spendings = json.dumps([{"type": "feuser", "id": a_pk, "share_percent": 50}])
        sched_pk = int(_shell(
            f"from budget.models import ScheduledExpense; from feusers.models import FeUser; "
            f"from decimal import Decimal; from datetime import date; "
            f"a = FeUser.objects.get(email='{a['email']}'); "
            f"b = FeUser.objects.get(email='{b['email']}'); "
            f"s = ScheduledExpense.objects.create(owning_feuser=a, title='Trusted Rent', "
            f"  type='expense', value=Decimal('500.00'), repeat_base_date=date.today(), "
            f"  repeat_every_factor=1, repeat_every_unit='months', "
            f"  assign_buddy_mode='single', assign_upfront_type='feuser', "
            f"  assign_upfront_feuser=b, assign_spendings_json='{spendings}'); "
            f"print(s.pk)"
        ))
        yield {"a": a, "b": b, "sched_pk": sched_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_generated_occurrences_are_approved(self, driver, w, ctx):
        run_cmd("generate_scheduled_expenses", "--user", ctx["a"]["email"])
        states = _shell(
            f"from budget.models import Expense; "
            f"print(sorted(set(Expense.objects.filter(source_scheduled_id={ctx['sched_pk']})"
            f".values_list('buddy_approved', flat=True))))"
        )
        assert states == "[True]", f"Every generated occurrence must be approved, got {states}"

    def test_generated_occurrences_initiated_by_a(self, driver, w, ctx):
        initiators = _shell(
            f"from budget.models import Expense; "
            f"print(sorted(set(Expense.objects.filter(source_scheduled_id={ctx['sched_pk']})"
            f".values_list('initiated_by_feuser__email', flat=True))))"
        )
        assert initiators == str([ctx["a"]["email"]])


# ---------------------------------------------------------------------------
# Settlements
# ---------------------------------------------------------------------------

class TestDirectSettlementAutoConfirmed:
    """A owes B; B trusts A; A records paying B back: confirmed right away."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Payback", last_name="Actor")
        b = setup_user(None, None, first_name="Payback", last_name="Truster")
        _create_buddy_link(a["email"], b["email"])
        _create_personal_expense_with_buddy(
            owner_email=b["email"], participant_pk=int(_get_pk(a["email"])),
            title="Payback Source", value="100.00", share="50.0", approved=True,
        )
        _set_trust(b["email"], a["email"])
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_a_records_settlement(self, driver, w, ctx):
        ctx["seen_before"] = mailpit_seen_ids()
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        driver.find_element(By.ID, "btn-direct-settle").click()
        _confirm(driver)
        time.sleep(1)
        ctx["exp_pk"] = int(_shell(
            f"from budget.models import Expense; "
            f"print(Expense.objects.filter(owning_feuser__email='{ctx['a']['email']}', "
            f"is_buddies_settlement=True).latest('uid').pk)"
        ))

    def test_settlement_is_confirmed(self, driver, w, ctx):
        assert _approved(ctx["exp_pk"]) == "True"

    def test_b_gets_settlement_received_income(self, driver, w, ctx):
        count = _shell(
            f"from budget.models import Expense; "
            f"print(Expense.objects.filter(owning_feuser__email='{ctx['b']['email']}', "
            f"type='income', title__startswith='Settlement received from Payback Actor').count())"
        )
        assert count == "1"

    def test_b_gets_auto_confirmed_email(self, driver, w, ctx):
        body = fetch_email(ctx["b"]["email"], "Settlement confirmed automatically",
                           ignore_ids=ctx["seen_before"])
        assert "Payback Actor" in body

    def test_b_gets_no_confirmation_request(self, driver, w, ctx):
        assert _no_email(ctx["b"]["email"], "recorded a settlement with you", ctx["seen_before"])

    def test_debt_cleared_for_a(self, driver, w, ctx):
        # "Pay someone back" stays visible for any direct buddy (freeform
        # payments), so check the balance itself instead.
        net = _shell(
            f"from feusers.models import FeUser; from buddies.services import BuddyQueryService; "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"print(BuddyQueryService.get_net_debt(a, buddy_feuser=b))"
        )
        assert abs(float(net)) < 0.005, f"Debt must be cleared right away, got {net}"

    def test_a_sees_settled_on_my_buddies(self, driver, w, ctx):
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        row = driver.find_element(By.XPATH,
            "//div[contains(@class,'buddy-balance-row')][.//span[contains(@class,'buddy-name') and contains(., 'Payback Truster')]]")
        assert "Settled" in row.find_element(By.CSS_SELECTOR, ".bbl-balance").text


class TestProjectSettlementAutoConfirmed:
    """B (admin) and A share a project and are direct buddies; A pays B back there."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Grouppay", last_name="Actor")
        b = setup_user(None, None, first_name="Grouppay", last_name="Truster")
        group_id = int(_create_group(b["email"], "Trust Settle Project"))
        _add_group_member(group_id, a["email"])
        _create_group_expense(
            admin_email=b["email"], participant_email=a["email"], group_id=group_id,
            title="Group Payback Source", value="100.00", share="50.0",
        )
        _create_buddy_link(a["email"], b["email"])
        _set_trust(b["email"], a["email"])
        yield {"a": a, "b": b, "group_id": group_id}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_a_settles_in_project(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        amt = driver.find_element(By.ID, "settle-amount")
        driver.execute_script("arguments[0].value = '50.00';", amt)
        driver.find_element(By.ID, "btn-settle-individual").click()
        _confirm(driver)
        time.sleep(1)

    def test_settlement_is_confirmed(self, driver, w, ctx):
        state = _shell(
            f"from budget.models import Expense; "
            f"print(Expense.objects.filter(project_id={ctx['group_id']}, "
            f"is_buddies_settlement=True).latest('uid').buddy_approved)"
        )
        assert state == "True"

    def test_no_waiting_section_for_a(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Waiting for approval" not in driver.page_source


# ---------------------------------------------------------------------------
# Enabling accepts pending entries retroactively
# ---------------------------------------------------------------------------

class TestRetroactiveAcceptOnEnable:
    """
    Pending before the trust: one direct expense A logged via the form, one in
    a now-archived project, and one legacy row without a known initiator.
    Enabling accepts only the first, silently.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Retro", last_name="Actor")
        b = setup_user(None, None, first_name="Retro", last_name="Truster")
        link_pk = _create_buddy_link(a["email"], b["email"])
        group_id = int(_create_group(a["email"], "Retro Archived Project"))
        _add_group_member(group_id, b["email"])
        a_pk, b_pk = _get_pk(a["email"]), _get_pk(b["email"])
        legacy_pk = int(_create_personal_expense_with_buddy(
            owner_email=b["email"], participant_pk=int(a_pk),
            title="Retro Legacy", value="10.00", share="50.0", approved=False,
        ))
        yield {"a": a, "b": b, "link_pk": link_pk, "group_id": group_id,
               "a_pk": a_pk, "b_pk": b_pk, "legacy_pk": legacy_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_a_logs_pending_entries(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        _submit_expense_form(
            driver, title="Retro Direct", value="20.00", date=server_today(),
            upfront_type="feuser", upfront_id=ctx["b_pk"],
            spendings=[{"type": "feuser", "id": int(ctx["a_pk"]), "share_percent": 50}],
        )
        _submit_expense_form(
            driver, title="Retro Archived", value="30.00", date=server_today(),
            mode="group", project_id=ctx["group_id"],
            upfront_type="feuser", upfront_id=ctx["b_pk"],
            spendings=[{"type": "feuser", "id": int(ctx["a_pk"]), "share_percent": 50}],
        )
        ctx["direct_pk"] = _expense_pk(ctx["b"]["email"], "Retro Direct")
        ctx["archived_pk"] = _expense_pk(ctx["b"]["email"], "Retro Archived")
        _shell(f"from buddies.models import Project; "
               f"Project.objects.filter(pk={ctx['group_id']}).update(archived=True)")
        for pk in (ctx["direct_pk"], ctx["archived_pk"], ctx["legacy_pk"]):
            assert _approved(pk) == "False"

    def test_b_enables_trust(self, driver, w, ctx):
        ctx["seen_before"] = mailpit_seen_ids()
        _login_as(driver, ctx["b"])
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        cb = driver.find_element(By.ID, f"auto-accept-{ctx['link_pk']}")
        driver.execute_script("arguments[0].click();", cb)
        _confirm(driver)
        time.sleep(1)
        assert "1 pending entry accepted" in driver.page_source

    def test_pending_entry_from_a_accepted(self, driver, w, ctx):
        assert _approved(ctx["direct_pk"]) == "True"

    def test_archived_project_untouched(self, driver, w, ctx):
        assert _approved(ctx["archived_pk"]) == "False"

    def test_legacy_row_without_initiator_untouched(self, driver, w, ctx):
        assert _approved(ctx["legacy_pk"]) == "False"

    def test_no_email_for_retroactive_accept(self, driver, w, ctx):
        assert _no_email(ctx["b"]["email"], "accepted automatically", ctx["seen_before"])


# ---------------------------------------------------------------------------
# Removing the buddy removes the trust
# ---------------------------------------------------------------------------

class TestTrustRemovedWithBuddyLink:
    """B trusts A; A removes B as buddy; after reconnecting the trust is off."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Kick", last_name="Actor")
        b = setup_user(None, None, first_name="Kick", last_name="Truster")
        link_pk = _create_buddy_link(a["email"], b["email"])
        _set_trust(b["email"], a["email"])
        yield {"a": a, "b": b, "link_pk": link_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_a_removes_b(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/my-buddies/"))
        time.sleep(1)
        driver.execute_script(
            f"document.getElementById('kick-form-{ctx['link_pk']}').submit();"
        )
        time.sleep(1.5)
        assert _trust_flag(ctx["b"]["email"], ctx["a"]["email"]) == "nolink"

    def test_reconnected_link_starts_untrusted(self, driver, w, ctx):
        _create_buddy_link(ctx["a"]["email"], ctx["b"]["email"])
        assert _trust_flag(ctx["b"]["email"], ctx["a"]["email"]) == "False"
