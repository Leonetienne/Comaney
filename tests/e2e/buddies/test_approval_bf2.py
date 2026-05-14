"""
BF-2 regression: the debtor must not be able to approve their own settlement expense.

The approve_expense endpoint now requires settled=False. A direct HTTP POST
by the debtor to /buddies/expense/<uid>/approve/ on a settlement expense
must return 404 and must NOT flip buddy_approved to True.
"""
import time

import pytest
import requests as req

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as, _create_buddy_link, _get_pk, _create_personal_expense_with_buddy


class TestApproveOwnSettlementBlocked:
    """Debtor POSTs to approve their own settlement: must get 404, not approved."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Abel", last_name="Debtor")
        b = setup_user(None, None, first_name="Bea", last_name="Creditor")
        _create_buddy_link(a["email"], b["email"])
        a_pk = int(_get_pk(a["email"]))
        # B paid 80; A owes 50% = 40
        _create_personal_expense_with_buddy(
            owner_email=b["email"],
            participant_pk=a_pk,
            title="BF2 Source Expense",
            value="80.00",
            share="50.0",
            approved=True,
        )
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_a_creates_settlement(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Settle Up" in driver.page_source, \
            "Settle Up section must be visible before test can run"
        driver.find_element(
            "css selector", ".direct-settle-form button[type=submit]"
        ).click()
        time.sleep(0.5)
        driver.find_element("id", "cdialog-ok").click()
        time.sleep(1)

    def test_settlement_expense_uid_exists(self, driver, w, ctx):
        uid = _shell(
            f"from budget.models import Expense; "
            f"from feusers.models import FeUser; "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"e = Expense.objects.filter(owning_feuser=a, is_buddies_settlement=True).first(); "
            f"print(e.uid if e else 'none')"
        )
        assert uid != "none", "Settlement expense must exist after A submits"
        ctx["settlement_uid"] = uid

    def test_debtor_post_approve_returns_404(self, driver, w, ctx):
        uid = ctx.get("settlement_uid")
        assert uid, "Settlement UID must be present from previous test"

        # Build a plain dict from Selenium cookies; dict deduplication avoids
        # CookieConflictError that arises when multiple csrftoken entries exist
        # (e.g. one per path).  Pass cookies explicitly to requests.post so
        # no Session cookiejar is involved.
        cookie_dict = {c["name"]: c["value"] for c in driver.get_cookies()}
        csrftoken = cookie_dict.get("csrftoken", "")
        sessionid = cookie_dict.get("sessionid", "")

        resp = req.post(
            _url(f"/buddies/expense/{uid}/approve/"),
            headers={
                "X-CSRFToken": csrftoken,
                "Referer": _url("/buddies/summary/"),
            },
            cookies={"csrftoken": csrftoken, "sessionid": sessionid},
            timeout=10,
            allow_redirects=False,
        )
        assert resp.status_code == 404, (
            f"POSTing to approve own settlement must return 404, got {resp.status_code}"
        )

    def test_settlement_still_pending_after_post(self, driver, w, ctx):
        uid = ctx.get("settlement_uid")
        approved = _shell(
            f"from budget.models import Expense; "
            f"e = Expense.objects.get(uid='{uid}'); "
            f"print(e.buddy_approved)"
        )
        assert approved == "False", \
            "buddy_approved must remain False; the debtor must not be able to self-approve"
