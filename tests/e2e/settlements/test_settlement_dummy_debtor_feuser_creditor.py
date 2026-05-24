"""
Bug regression: admin must not be able to approve a group settlement where
the debtor is an offline member (dummy) and the creditor is a real user.

Setup: admin A, real member B, offline member D in one group.
Admin creates a settlement: D (dummy debtor) pays B (real-user creditor).
=> buddy_approved=False, creditor is B.

  [B1] /buddies/summary/ must NOT show this settlement in the
       "Waiting for your approval" section for the admin.
  [B2] The admin_approve_dummy_settlement endpoint must reject the admin's POST
       with an error and must not mark the expense as approved.
  [B3] The real creditor B sees the settlement in their "Waiting for your approval"
       section and CAN approve it.
"""
import time

import pytest
import requests as _requests
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as, _create_group, _add_group_member


def _create_group_dummy(group_id: int, display_name: str) -> str:
    return _shell(
        f"from buddies.models import Project, BuddyGroupMember, DummyUser; "
        f"g = Project.objects.get(pk={group_id}); "
        f"d = DummyUser.objects.create(owning_group=g, display_name='{display_name}'); "
        f"BuddyGroupMember.objects.create(group=g, dummy=d); "
        f"print(d.pk)"
    )


def _create_settlement_dummy_debtor_feuser_creditor(
    admin_email: str, dummy_pk: int, creditor_pk: int, group_id: int,
    value: str = "60.00",
) -> str:
    """Admin creates a settlement: dummy D owes real user B; returns expense pk."""
    return _shell(
        f"from buddies.services import BuddySettlementService; "
        f"from buddies.models import Project; "
        f"from feusers.models import FeUser; "
        f"from decimal import Decimal; "
        f"admin = FeUser.objects.get(email='{admin_email}'); "
        f"g = Project.objects.get(pk={group_id}); "
        f"BuddySettlementService.create_individual_group_settlement("
        f"  admin, g, 'd{dummy_pk}', 'f{creditor_pk}', Decimal('{value}')); "
        f"from budget.models import Expense; "
        f"e = Expense.objects.filter("
        f"  is_buddies_settlement=True, project=g, buddy_approved=False,"
        f"  upfront_payee_dummy_id={dummy_pk}"
        f").first(); "
        f"print(e.pk if e else 'none')"
    )


def _get_expense_approved(expense_pk: str) -> str:
    return _shell(
        f"from budget.models import Expense; "
        f"e = Expense.objects.filter(pk={expense_pk}).first(); "
        f"print(e.buddy_approved if e else 'deleted')"
    )


class TestSettlementDummyDebtorFeuserCreditor:
    """
    Regression: admin must not see or approve a dummy->real-user settlement
    in their /buddies/summary/ page.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Ada", last_name="Admin")
        creditor = setup_user(driver, w, first_name="Cred", last_name="Itor")
        group_id = int(_create_group(admin["email"], "BugGroup"))
        _add_group_member(group_id, creditor["email"])
        creditor_email = creditor["email"]
        creditor_pk = int(_shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{creditor_email}').pk)"
        ))
        dummy_pk = int(_create_group_dummy(group_id, "Dumpling"))
        exp_pk = _create_settlement_dummy_debtor_feuser_creditor(
            admin["email"], dummy_pk, creditor_pk, group_id, "60.00"
        )
        assert exp_pk != "none", "Settlement expense must have been created"
        yield {
            "admin": admin,
            "creditor": creditor,
            "group_id": group_id,
            "dummy_pk": dummy_pk,
            "creditor_pk": creditor_pk,
            "exp_pk": exp_pk,
        }
        cleanup_user(admin["email"])
        cleanup_user(creditor["email"])

    # B1: admin must NOT see the settlement in the offline-member approval section
    def test_b1_admin_summary_no_approval_item_for_settlement(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        src = driver.page_source
        assert f"btn-admin-approve-{ctx['exp_pk']}" not in src, \
            "[B1] Admin must not see an Approve button for a dummy->real-user settlement"
        assert f"btn-review-dummy-{ctx['exp_pk']}" not in src, \
            "[B1] Admin must not see a Review button for a dummy->real-user settlement"

    # B2: admin POST to admin_approve_dummy_settlement must be rejected
    def test_b2_admin_cannot_approve_via_endpoint(self, driver, w, ctx):
        group_id = ctx["group_id"]
        exp_pk = ctx["exp_pk"]
        # Get CSRF token and session cookie from admin browser session
        cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
        csrftoken = cookies.get("csrftoken", "")
        resp = _requests.post(
            _url(f"/projects/{group_id}/expense/{exp_pk}/approve-dummy/"),
            data={"csrfmiddlewaretoken": csrftoken},
            cookies=cookies,
            allow_redirects=False,
        )
        # Must redirect (302) back to group page, not approve
        assert resp.status_code == 302, \
            f"[B2] Endpoint must redirect, got {resp.status_code}"

    def test_b2_expense_still_unapproved_after_admin_attempt(self, driver, w, ctx):
        approved = _get_expense_approved(ctx["exp_pk"])
        assert approved == "False", \
            "[B2] Expense must still be buddy_approved=False after admin's rejected attempt"

    def test_b2_admin_sees_error_flash_after_attempt(self, driver, w, ctx):
        group_id = ctx["group_id"]
        exp_pk = ctx["exp_pk"]
        driver.get(_url(f"/projects/{group_id}/"))
        time.sleep(1)
        cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
        csrftoken = cookies.get("csrftoken", "")
        resp = _requests.post(
            _url(f"/projects/{group_id}/expense/{exp_pk}/approve-dummy/"),
            data={"csrfmiddlewaretoken": csrftoken},
            cookies=cookies,
            allow_redirects=True,
        )
        assert "Only the creditor can confirm" in resp.text, \
            "[B2] Response must contain error message 'Only the creditor can confirm'"

    # B3: creditor sees the settlement in their summary and can approve it
    def test_b3_creditor_sees_settlement_in_summary(self, driver, w, ctx):
        _login_as(driver, ctx["creditor"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Waiting for your approval" in driver.page_source, \
            "[B3] Creditor must see 'Waiting for your approval' section"

    def test_b3_creditor_sees_review_button(self, driver, w, ctx):
        links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/approve-settlement/']")
        assert links, "[B3] Creditor must see a Review button for the settlement"

    def test_b3_creditor_can_approve(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR, "a[href*='/approve-settlement/']").click()
        time.sleep(1)
        driver.find_element(By.ID, "btn-approve-settlement").click()
        time.sleep(1)
        assert "confirmed" in driver.page_source.lower(), \
            "[B3] Flash must confirm receipt after creditor approves"

    def test_b3_expense_approved_after_creditor_confirms(self, driver, w, ctx):
        approved = _get_expense_approved(ctx["exp_pk"])
        assert approved == "True", \
            "[B3] Expense must be buddy_approved=True after creditor confirms"
