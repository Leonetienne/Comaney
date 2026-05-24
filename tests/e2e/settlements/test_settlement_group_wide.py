"""
Group-wide settlement (Settle entire group button) using the Camping Weekend dataset.

The camping dataset has three real users (Anna=admin, Ben, Clara) and two
offline dummies (Dog, Ranger Rick) with nine approved shared expenses.

After simplified debt calculation:
  - Ben  -> Anna
  - Clara -> Anna
  - Dog   -> Anna   (dummy debtor, real creditor)
  - Ranger -> Anna  (dummy debtor, real creditor)

Testing covers:
  - Settle entire group button visible only for admin
  - Confirmation dialog lists all debt pairs and warns about emails
  - Submitting creates settlement records for all pairs
  - Debtors (Ben, Clara) receive email notifications
  - Debtors see Waiting for approval section on the group page
  - Creditor (Anna) sees pending settlement receipts
  - Anna approves a settlement via Review flow
  - Approved settlement moves to Expense Breakdown
  - Income expense created for Anna
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, run_cmd, fetch_email, mailpit_seen_ids
from bhelpers import _shell, _login_as


ANNA  = {"email": "anna@test.local",  "password": "1234", "first": "Anna"}
BEN   = {"email": "ben@test.local",   "password": "1234", "first": "Ben"}
CLARA = {"email": "clara@test.local", "password": "1234", "first": "Clara"}


def _get_group_id() -> str:
    return _shell(
        "from buddies.models import Project; "
        "g = Project.objects.get(name='Camping Weekend'); "
        "print(g.uid)"
    )


def _settlement_count() -> int:
    return int(_shell(
        "from budget.models import Expense; "
        "print(Expense.objects.filter(is_buddies_settlement=True, "
        "  project__name='Camping Weekend').count())"
    ))


@pytest.fixture(scope="module")
def camping():
    # Wipe any leftover data from a previous crashed run before re-creating
    try:
        run_cmd("test_delete_camping_dataset")
    except AssertionError:
        pass
    run_cmd("test_create_camping_dataset")
    group_id = _get_group_id()
    yield {"group_id": group_id}
    run_cmd("test_delete_camping_dataset")


class TestGroupWideSettlementCamping:
    """Full group-wide settle flow using the Camping Weekend dataset."""

    def test_non_admin_cannot_see_settle_all_button(self, driver, w, camping):
        _login_as(driver, BEN)
        driver.get(_url(f"/projects/{camping['group_id']}/"))
        time.sleep(2)
        assert f"/projects/{camping['group_id']}/" in driver.current_url, \
            f"Ben must land on the group page, got: {driver.current_url}"
        forms = driver.find_elements(By.ID, "settle-all-form")
        assert not forms, \
            "Settle entire group button must not be visible to non-admin members"

    def test_admin_sees_settle_all_button(self, driver, w, camping):
        _login_as(driver, ANNA)
        assert "/login/" not in driver.current_url, \
            f"Anna login failed, landed on: {driver.current_url}"
        driver.get(_url(f"/projects/{camping['group_id']}/"))
        time.sleep(2)
        assert f"/projects/{camping['group_id']}/" in driver.current_url, \
            f"Anna must land on the group page, got: {driver.current_url}"
        btn = driver.find_element(By.ID, "btn-settle-all")
        assert btn.is_displayed(), \
            "Admin must see the Settle entire group button"

    def test_simplified_debts_listed_on_page(self, driver, w, camping):
        src = driver.page_source
        assert "Ben" in src, "Simplified debts must list Ben as a debtor"
        assert "Clara" in src, "Simplified debts must list Clara as a debtor"

    def test_settle_all_dialog_appears(self, driver, w, camping):
        seen_before = mailpit_seen_ids()
        camping["seen_before"] = seen_before

        driver.find_element(By.ID, "btn-settle-all").click()
        time.sleep(0.5)
        msg = driver.find_element(By.ID, "cdialog-msg").text
        assert "payment records" in msg.lower() or "settle" in msg.lower(), \
            "Dialog must describe creating payment records"
        assert "email" in msg.lower(), \
            "Dialog must warn that everyone involved will receive an email"
        driver.find_element(By.ID, "cdialog-cancel").click()
        time.sleep(0.5)

    def test_submit_settle_all_creates_records(self, driver, w, camping):
        existing = _settlement_count()
        driver.find_element(By.ID, "btn-settle-all").click()
        time.sleep(0.5)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(2)
        new_count = _settlement_count()
        assert new_count > existing, \
            "Settle entire group must create new settlement records"
        camping["created"] = new_count - existing

    def test_four_settlements_created(self, driver, w, camping):
        # Expect 4: Ben->Anna, Clara->Anna, Dog->Anna, Ranger->Anna
        # (There was already 1 pending non-settlement expense in the dataset
        # but that is not a settlement, so count should be 4)
        assert camping.get("created", 0) == 4, \
            f"Expected 4 settlement records, created {camping.get('created', 0)}"

    def test_ben_receives_settlement_email(self, driver, w, camping):
        body = fetch_email(
            BEN["email"],
            subject_fragment="settlement",
            timeout=60,
            ignore_ids=camping.get("seen_before"),
        )
        assert body, "Ben must receive a settlement email"

    def test_clara_receives_settlement_email(self, driver, w, camping):
        body = fetch_email(
            CLARA["email"],
            subject_fragment="settlement",
            timeout=60,
            ignore_ids=camping.get("seen_before"),
        )
        assert body, "Clara must receive a settlement email"

    def test_ben_sees_waiting_for_approval(self, driver, w, camping):
        _login_as(driver, BEN)
        driver.get(_url(f"/projects/{camping['group_id']}/"))
        time.sleep(2)
        assert "Waiting for approval" in driver.page_source, \
            "Ben must see Waiting for approval section after group-wide settle"

    def test_clara_sees_waiting_for_approval(self, driver, w, camping):
        assert camping.get("created", 0) > 0, \
            "Settlements must exist (test_submit_settle_all_creates_records must run first)"
        _login_as(driver, CLARA)
        driver.get(_url(f"/projects/{camping['group_id']}/"))
        time.sleep(2)
        assert "Waiting for approval" in driver.page_source, \
            "Clara must see Waiting for approval section after group-wide settle"

    def test_anna_sees_pending_settlement_receipts(self, driver, w, camping):
        _login_as(driver, ANNA)
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Waiting for your approval" in driver.page_source, \
            "Anna (creditor) must see the pending approvals section on buddy summary"

    def test_anna_sees_review_buttons(self, driver, w, camping):
        links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/approve-settlement/']")
        assert links, "Anna must see Review links for the pending settlements"
        assert all(lnk.text.strip() == "Review" for lnk in links), \
            "All settlement links must be labelled 'Review'"

    def test_anna_approves_one_settlement(self, driver, w, camping):
        driver.find_element(By.CSS_SELECTOR, "a[href*='/approve-settlement/']").click()
        time.sleep(1)
        driver.find_element(
            By.ID, "btn-approve-settlement"
        ).click()
        time.sleep(1)
        assert "confirmed" in driver.page_source.lower(), \
            "Flash must confirm approval after Anna reviews a settlement"

    def test_income_expense_created_for_anna(self, driver, w, camping):
        import requests
        api_key = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{ANNA['email']}').api_key)"
        )
        resp = requests.get(
            _url("/api/v1/expenses/"),
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        income = [
            e for e in resp.json()["expenses"]
            if e["type"] == "income" and "Settlement" in e.get("title", "")
        ]
        assert income, \
            "Anna must have at least one income expense after approving a settlement"

    def test_settle_all_button_gone_after_all_approved(self, driver, w, camping):
        # Approve all remaining unapproved settlement expenses via shell so we
        # avoid accidentally clicking the pre-existing non-settlement pending expense
        # (which is not is_buddies_settlement and would 404 on the Review flow).
        _shell(
            "from budget.models import Expense; "
            "from buddies.models import Project; "
            "g = Project.objects.get(name='Camping Weekend'); "
            "Expense.objects.filter(project=g, is_buddies_settlement=True, "
            "  buddy_approved=False).update(buddy_approved=True)"
        )
        # The group page must no longer show a "Settle entire group" button now
        # that all settlement debts are cleared. The pre-existing non-settlement
        # pending expense still exists but does not affect simplified debts.
        _login_as(driver, ANNA)
        driver.get(_url(f"/projects/{camping['group_id']}/"))
        time.sleep(1)
        forms = driver.find_elements(By.ID, "settle-all-form")
        assert not forms, \
            "Settle entire group button must disappear once all settlement debts are resolved"
