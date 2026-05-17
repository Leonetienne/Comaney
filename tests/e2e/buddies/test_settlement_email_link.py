"""
Creditor approves a direct settlement via the link sent to their email.

Requirements: req 14.9a - the approval email contains a clickable link;
following it lands on the approve-settlement confirmation page where
the creditor can confirm or reject.
"""
import time

import pytest

from helpers import _url, setup_user, cleanup_user, fetch_email, extract_link, mailpit_seen_ids
from bhelpers import _shell, _login_as, _create_buddy_link, _get_pk, _create_personal_expense_with_buddy


class TestSettlementEmailLinkApproval:
    """A settles; B receives an email with an approve link and confirms via that link."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Emil", last_name="Debtor")
        b = setup_user(None, None, first_name="Lena", last_name="Creditor")
        _create_buddy_link(a["email"], b["email"])
        a_pk = int(_get_pk(a["email"]))
        # B paid 90; A owes 50% = 45
        _create_personal_expense_with_buddy(
            owner_email=b["email"],
            participant_pk=a_pk,
            title="Email Link Source",
            value="90.00",
            share="50.0",
            approved=True,
        )
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_a_submits_settlement(self, driver, w, ctx):
        seen = mailpit_seen_ids()
        ctx["seen_before_settle"] = seen

        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Pay someone back" in driver.page_source, \
            "Settle Up section must appear before test can run"
        driver.find_element(
            "css selector", ".direct-settle-form button[type=submit]"
        ).click()
        time.sleep(0.5)
        driver.find_element("id", "cdialog-ok").click()
        time.sleep(1)

    def test_email_arrives_for_creditor(self, driver, w, ctx):
        body = fetch_email(
            ctx["b"]["email"],
            subject_fragment="settlement",
            timeout=60,
            ignore_ids=ctx.get("seen_before_settle"),
        )
        assert body, "Settlement confirmation email must arrive for the creditor"
        assert "Emil" in body or "settlement" in body.lower(), \
            "Email body must reference the debtor or the settlement"
        ctx["email_body"] = body

    def test_email_contains_approve_link(self, driver, w, ctx):
        body = ctx.get("email_body", "")
        link = extract_link(body)
        assert "/approve-settlement/" in link, \
            "Email must contain an approve-settlement URL"
        ctx["approve_link"] = link

    def test_navigating_link_shows_confirm_page(self, driver, w, ctx):
        link = ctx.get("approve_link", "")
        # Must be logged in as B (creditor) to access the link
        _login_as(driver, ctx["b"])
        driver.get(link)
        time.sleep(1)
        assert "did not receive" in driver.page_source.lower() or \
               "confirm" in driver.page_source.lower(), \
            "Email link must lead to the settlement confirmation page"

    def test_creditor_approves_via_email_link(self, driver, w, ctx):
        from selenium.webdriver.common.by import By
        driver.find_element(By.ID, "btn-approve-settlement").click()
        time.sleep(1)
        assert "confirmed" in driver.page_source.lower(), \
            "Approving via email link must show a confirmation flash"

    def test_debt_cleared_for_debtor(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Pay someone back" not in driver.page_source, \
            "Settle Up section must disappear once the creditor has confirmed via email link"

    def test_income_expense_created_for_creditor(self, driver, w, ctx):
        import requests
        api_key = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{ctx['b']['email']}').api_key)"
        )
        resp = requests.get(
            _url("/api/v1/expenses/"),
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        income = [
            e for e in resp.json()["expenses"]
            if e["type"] == "income" and "Emil" in e["title"]
        ]
        assert income, \
            "Creditor must have an income expense after approving via email link"
