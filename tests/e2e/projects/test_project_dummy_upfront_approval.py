"""
Regression tests for: non-admin user creating a project expense with an
offline member (dummy) as the upfront payer must require admin approval.

Rules under test
----------------
- upfront_payer != creating feuser AND expense is in a project
  → buddy_approved=False (admin must confirm)
- Exception 1: creating feuser IS the project admin → buddy_approved=True
- Exception 2: direct buddy expense (no project) → buddy_approved=True

Also covers:
- Admin confirm page shows correct wording (not settlement language) for the
  non-settlement dummy-upfront case.
- Admin approve flow marks the expense as approved.
- Admin reject flow deletes the expense.
"""
import time

import pytest
import requests as req

from helpers import _url, setup_user, cleanup_user, server_today
from bhelpers import _shell, _login_as, _create_group, _add_group_member


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _create_group_dummy(group_id: int, display_name: str) -> str:
    """Create a DummyUser member in a project; return dummy pk as string."""
    return _shell(
        f"from buddies.models import Project, ProjectMember, DummyUser; "
        f"g = Project.objects.get(pk={group_id}); "
        f"d = DummyUser.objects.create(owning_group=g, display_name='{display_name}'); "
        f"ProjectMember.objects.create(group=g, dummy=d); "
        f"print(d.pk)"
    )


def _create_dummy_upfront_project_expense(owner_email: str, group_id: int,
                                          dummy_pk: int, title: str,
                                          buddy_approved: bool = False) -> str:
    """Create a project expense where a dummy is the upfront payer.
    Returns expense pk as string."""
    approved_val = "True" if buddy_approved else "False"
    return _shell(
        f"from budget.models import Expense; "
        f"from buddies.models import Project, BuddySpending; "
        f"from feusers.models import FeUser; from decimal import Decimal; "
        f"from datetime import date; "
        f"owner = FeUser.objects.get(email='{owner_email}'); "
        f"g = Project.objects.get(pk={group_id}); "
        f"e = Expense.objects.create(owning_feuser=owner, title='{title}', "
        f"  type='expense', value=Decimal('80.00'), settled=False, "
        f"  date_due=date.today(), is_dummy=True, "
        f"  upfront_payee_dummy_id={dummy_pk}, "
        f"  buddy_approved={approved_val}, project=g); "
        f"BuddySpending.objects.create(expense=e, participant_feuser=owner, "
        f"  share_percent=Decimal('100')); "
        f"print(e.pk)"
    )


def _post_expense_with_dummy_payer(driver, project_id: int, dummy_pk: int,
                                   member_pk: int, title: str) -> str:
    """POST to the expense-create view as the currently logged-in Selenium user.
    Returns the uid of the created expense."""
    import json as _json
    import re as _re
    today = server_today()
    cookie_dict = {c["name"]: c["value"] for c in driver.get_cookies()}
    csrftoken = cookie_dict.get("csrftoken", "")
    sessionid = cookie_dict.get("sessionid", "")
    session_cookies = {"csrftoken": csrftoken, "sessionid": sessionid}

    # Fetch the form to get the one-time nonce
    get_r = req.get(
        _url("/budget/expenses/new/"),
        cookies=session_cookies,
        timeout=10,
    )
    m = _re.search(r'name="form_nonce"\s+value="([^"]+)"', get_r.text)
    form_nonce = m.group(1) if m else ""

    spendings_json = _json.dumps([
        {"type": "feuser", "id": member_pk, "share_percent": "100"}
    ])
    data = {
        "title": title,
        "type": "expense",
        "value": "60.00",
        "date_due": today,
        "settled": "on",
        "buddy_payment": "on",
        "buddy_mode": "group",
        "buddy_upfront_type": "dummy",
        "buddy_upfront_id": str(dummy_pk),
        "project_id": str(project_id),
        "buddy_spendings_json": spendings_json,
        "form_nonce": form_nonce,
    }
    req.post(
        _url("/budget/expenses/new/"),
        data=data,
        headers={"X-CSRFToken": csrftoken, "Referer": _url("/budget/expenses/new/")},
        cookies=session_cookies,
        timeout=10,
        allow_redirects=True,
    )
    uid = _shell(
        f"from budget.models import Expense; "
        f"e = Expense.objects.filter(title='{title}', is_dummy=True).order_by('-date_created').first(); "
        f"print(e.uid if e else 'none')"
    )
    return uid


# ---------------------------------------------------------------------------
# buddy_approved state on creation
# ---------------------------------------------------------------------------

class TestNonAdminDummyUpfrontRequiresApproval:
    """
    Non-admin member creates a project expense with a dummy as upfront payer.
    buddy_approved must be False — admin approval is required.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(None, None, first_name="Adele", last_name="AdminDUP")
        member = setup_user(driver, w, first_name="Mike", last_name="MemberDUP")
        group_id = int(_create_group(admin["email"], "DummyUpfrontTestGroup"))
        _add_group_member(group_id, member["email"])
        member_pk = int(_shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{member['email']}').pk)"
        ))
        dummy_pk = int(_create_group_dummy(group_id, "Offline Franz"))
        yield {
            "admin": admin,
            "member": member,
            "group_id": group_id,
            "dummy_pk": dummy_pk,
            "member_pk": member_pk,
        }
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_non_admin_expense_requires_approval(self, driver, w, ctx):
        _login_as(driver, ctx["member"])
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(0.5)
        uid = _post_expense_with_dummy_payer(
            driver, ctx["group_id"], ctx["dummy_pk"],
            ctx["member_pk"], "NonAdminDummyPaidExpense"
        )
        assert uid != "none", "Expense must have been created"
        ctx["expense_uid"] = uid
        approved = _shell(
            f"from budget.models import Expense; "
            f"e = Expense.objects.get(uid='{uid}'); "
            f"print(e.buddy_approved)"
        )
        assert approved == "False", (
            "Non-admin creating a project expense with dummy upfront payer "
            "must have buddy_approved=False"
        )

    def test_expense_appears_as_pending_in_project(self, driver, w, ctx):
        uid = ctx.get("expense_uid")
        if not uid or uid == "none":
            pytest.skip("expense not created")
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        assert "NonAdminDummyPaidExpense" in driver.page_source, \
            "Pending expense must appear in the project detail page for the admin"


class TestAdminDummyUpfrontAutoApproved:
    """
    Admin creates a project expense with a dummy as upfront payer.
    buddy_approved must be True — admin exception, no extra approval needed.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Alma", last_name="AdminDUP2")
        group_id = int(_create_group(admin["email"], "AdminDummyUpfrontGroup"))
        admin_pk = int(_shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{admin['email']}').pk)"
        ))
        dummy_pk = int(_create_group_dummy(group_id, "Offline Greta"))
        yield {
            "admin": admin,
            "group_id": group_id,
            "dummy_pk": dummy_pk,
            "admin_pk": admin_pk,
        }
        cleanup_user(admin["email"])

    def test_admin_expense_auto_approved(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(0.5)
        uid = _post_expense_with_dummy_payer(
            driver, ctx["group_id"], ctx["dummy_pk"],
            ctx["admin_pk"], "AdminDummyPaidExpense"
        )
        assert uid != "none", "Expense must have been created"
        approved = _shell(
            f"from budget.models import Expense; "
            f"e = Expense.objects.get(uid='{uid}'); "
            f"print(e.buddy_approved)"
        )
        assert approved == "True", (
            "Admin creating a project expense with dummy upfront payer "
            "must be auto-approved (buddy_approved=True)"
        )


# ---------------------------------------------------------------------------
# Admin confirm page: correct wording for non-settlement dummy-upfront expense
# ---------------------------------------------------------------------------

class TestAdminConfirmPageWordingNonSettlement:
    """
    Admin visits the approve-dummy page for a non-settlement expense where
    an offline member paid upfront. The page must show expense-specific
    wording, NOT settlement wording ('received the money').
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Anke", last_name="AdminWording")
        member = setup_user(None, None, first_name="Leo", last_name="MemberWording")
        group_id = int(_create_group(admin["email"], "WordingTestGroup"))
        _add_group_member(group_id, member["email"])
        dummy_pk = int(_create_group_dummy(group_id, "Offline Helga"))
        expense_pk = _create_dummy_upfront_project_expense(
            member["email"], group_id, dummy_pk,
            "WordingTestExpense", buddy_approved=False,
        )
        yield {
            "admin": admin,
            "group_id": group_id,
            "expense_pk": expense_pk,
        }
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_confirm_page_shows_expense_wording(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(
            f"/projects/{ctx['group_id']}/expense/{ctx['expense_pk']}/approve-dummy/"
        ))
        time.sleep(1)
        src = driver.page_source
        assert "Offline Helga" in src, \
            "Confirm page must mention the offline member's name"
        assert "pay" in src.lower() or "paid" in src.lower(), \
            "Confirm page must use 'pay'/'paid' language for expense confirmation"
        assert "received the money" not in src.lower(), \
            "Confirm page must NOT use settlement language ('received the money')"
        assert "got the money" not in src.lower(), \
            "Confirm page must NOT use settlement language ('got the money')"

    def test_confirm_page_has_confirm_expense_button(self, driver, w, ctx):
        src = driver.page_source
        assert "confirm expense" in src.lower(), \
            "Approve button must say 'Confirm expense' (not settlement language)"

    def test_confirm_page_has_reject_button(self, driver, w, ctx):
        src = driver.page_source
        assert "reject" in src.lower(), \
            "Reject button must be present on the confirm page"


# ---------------------------------------------------------------------------
# Admin approve flow
# ---------------------------------------------------------------------------

class TestAdminApprovesNonSettlementDummyUpfront:
    """Admin confirms that an offline member actually paid upfront; expense is approved."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Anton", last_name="Approver")
        member = setup_user(None, None, first_name="Kai", last_name="Creator")
        group_id = int(_create_group(admin["email"], "ApproveFlowGroup"))
        _add_group_member(group_id, member["email"])
        dummy_pk = int(_create_group_dummy(group_id, "Offline Boris"))
        expense_pk = _create_dummy_upfront_project_expense(
            member["email"], group_id, dummy_pk,
            "ApproveFlowExpense", buddy_approved=False,
        )
        yield {
            "admin": admin,
            "group_id": group_id,
            "expense_pk": expense_pk,
        }
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_expense_pending_before_approval(self, driver, w, ctx):
        approved = _shell(
            f"from budget.models import Expense; "
            f"print(Expense.objects.get(pk={ctx['expense_pk']}).buddy_approved)"
        )
        assert approved == "False"

    def test_admin_approves_expense(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(
            f"/projects/{ctx['group_id']}/expense/{ctx['expense_pk']}/approve-dummy/"
        ))
        time.sleep(1)
        driver.find_element("id", "btn-approve-settlement").click()
        time.sleep(1)
        assert f"/projects/{ctx['group_id']}/" in driver.current_url, \
            "After approval admin must be redirected to project detail"

    def test_expense_approved_after_click(self, driver, w, ctx):
        approved = _shell(
            f"from budget.models import Expense; "
            f"print(Expense.objects.get(pk={ctx['expense_pk']}).buddy_approved)"
        )
        assert approved == "True", \
            "buddy_approved must be True after admin clicks approve"


# ---------------------------------------------------------------------------
# Admin reject flow
# ---------------------------------------------------------------------------

class TestAdminRejectsNonSettlementDummyUpfront:
    """Admin rejects the expense; it must be deleted."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Arno", last_name="Rejecter")
        member = setup_user(None, None, first_name="Sam", last_name="Creator")
        group_id = int(_create_group(admin["email"], "RejectFlowGroup"))
        _add_group_member(group_id, member["email"])
        dummy_pk = int(_create_group_dummy(group_id, "Offline Petra"))
        expense_pk = _create_dummy_upfront_project_expense(
            member["email"], group_id, dummy_pk,
            "RejectFlowExpense", buddy_approved=False,
        )
        yield {
            "admin": admin,
            "group_id": group_id,
            "expense_pk": expense_pk,
        }
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_admin_rejects_expense(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(
            f"/projects/{ctx['group_id']}/expense/{ctx['expense_pk']}/approve-dummy/"
        ))
        time.sleep(1)
        driver.find_element("id", "btn-reject-settlement").click()
        time.sleep(0.5)
        # Confirm the JS dialog
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        try:
            WebDriverWait(driver, 3).until(EC.alert_is_present())
            driver.switch_to.alert.accept()
        except Exception:
            # confirmDialog may use a custom modal instead of native alert
            from selenium.webdriver.common.by import By
            ok_buttons = driver.find_elements(By.ID, "cdialog-ok")
            if ok_buttons:
                ok_buttons[0].click()
        time.sleep(1)

    def test_expense_deleted_after_rejection(self, driver, w, ctx):
        exists = _shell(
            f"from budget.models import Expense; "
            f"print(Expense.objects.filter(pk={ctx['expense_pk']}).exists())"
        )
        assert exists == "False", \
            "Rejected expense must be deleted from the database"

    def test_project_page_loads_after_rejection(self, driver, w, ctx):
        assert f"/projects/{ctx['group_id']}/" in driver.current_url, \
            "After rejection admin must be redirected to project detail"
