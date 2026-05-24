"""
Group settlement where the dummy is the debtor and a real user is the creditor.

Requirements: req 10.7 - admin creates a settlement on behalf of a group dummy
(debtor) toward a real-user creditor. The real-user creditor must confirm receipt
via the "Waiting for approval" / Review flow on the group detail page.
"""
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as, _create_group


def _create_group_dummy(group_id: int, display_name: str) -> str:
    """Add a DummyUser to a group; return dummy pk as string."""
    return _shell(
        f"from buddies.models import Project, BuddyGroupMember, DummyUser; "
        f"g = Project.objects.get(pk={group_id}); "
        f"d = DummyUser.objects.create(owning_group=g, display_name='{display_name}'); "
        f"BuddyGroupMember.objects.create(group=g, dummy=d); "
        f"print(d.pk)"
    )


def _create_group_dummy_paid_expense(admin_email: str, dummy_pk: int,
                                     group_id: int, value: str = "100.00") -> None:
    """Admin-owned expense where the dummy paid upfront and owes nothing back (admin is creditor)."""
    # D paid 100, no spendings for other participants means admin has 100% implicit share.
    # This creates debt: admin owes dummy = 100. But we want dummy owes admin.
    # Instead: admin paid, dummy is a participant owing 100%.
    _shell(
        f"from feusers.models import FeUser; from buddies.models import Project, DummyUser; "
        f"from budget.expense_factory import create_expense; "
        f"from budget.models import TransactionType; from decimal import Decimal; "
        f"a = FeUser.objects.get(email='{admin_email}'); "
        f"g = Project.objects.get(pk={group_id}); "
        f"d = DummyUser.objects.get(pk={dummy_pk}); "
        f"create_expense(owning_feuser=a, title='Admin Paid For Dummy', "
        f"  type=TransactionType.EXPENSE, value=Decimal('{value}'), "
        f"  buddy_approved=True, project=g, "
        f"  buddy_spendings=[{{'type': 'dummy', 'id': d.pk, 'share_percent': 100}}])"
    )


class TestGroupSettlementDummyDebtor:
    """Admin creates a settlement on behalf of dummy debtor; admin must then Review/approve."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Axel", last_name="GroupAdmin")
        group_id = int(_create_group(admin["email"], "DummyDebtorGroup"))
        dummy_pk = int(_create_group_dummy(group_id, "Sir Owes-A-Lot"))
        # Admin paid 100, dummy owes 100%; simplified: dummy -> admin
        _create_group_dummy_paid_expense(admin["email"], dummy_pk, group_id, "100.00")
        yield {"admin": admin, "group_id": group_id, "dummy_pk": dummy_pk}
        cleanup_user(admin["email"])

    def test_pay_someone_back_section_visible(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Pay someone back" in driver.page_source, \
            "Pay someone back section must appear on the group page"

    def test_admin_selects_dummy_as_debtor(self, driver, w, ctx):
        debtor_sel = Select(driver.find_element(By.ID, "settle-debtor"))
        option_texts = [o.text for o in debtor_sel.options]
        assert any("Sir Owes-A-Lot" in t for t in option_texts), \
            "Admin's debtor dropdown must include the group dummy"
        debtor_sel.select_by_visible_text("Sir Owes-A-Lot (offline member)")
        time.sleep(0.5)

    def test_amount_input_available(self, driver, w, ctx):
        amt = driver.find_element(By.ID, "settle-amount")
        # Pre-filled or empty; just ensure it exists and we can set a value
        amt.clear()
        amt.send_keys("100.00")

    def test_dialog_says_creditor_confirmation_needed(self, driver, w, ctx):
        driver.find_element(
            By.ID, "btn-settle-individual"
        ).click()
        time.sleep(0.5)
        msg = driver.find_element(By.ID, "cdialog-msg").text
        assert "confirm" in msg.lower(), \
            "Dialog must mention that the creditor will need to confirm receipt"
        driver.find_element(By.ID, "cdialog-cancel").click()
        time.sleep(0.5)

    def test_submit_creates_settlement(self, driver, w, ctx):
        amt = driver.find_element(By.ID, "settle-amount")
        amt.clear()
        amt.send_keys("100.00")
        driver.find_element(
            By.ID, "btn-settle-individual"
        ).click()
        time.sleep(0.5)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(1)
        assert "settlement record" in driver.page_source.lower(), \
            "Flash must confirm the settlement record was created"

    def test_settlement_pending_buddy_approved_false(self, driver, w, ctx):
        approved = _shell(
            f"from budget.models import Expense; "
            f"from feusers.models import FeUser; "
            f"a = FeUser.objects.get(email='{ctx['admin']['email']}'); "
            f"e = Expense.objects.filter(owning_feuser=a, is_buddies_settlement=True, "
            f"  upfront_payee_dummy_id={ctx['dummy_pk']}).first(); "
            f"print(e.buddy_approved if e else 'none')"
        )
        assert approved == "False", \
            "Settlement from dummy debtor to real creditor must start as buddy_approved=False"

    def test_waiting_for_approval_section_visible(self, driver, w, ctx):
        assert "Waiting for approval" in driver.page_source, \
            "Waiting for approval section must appear on the group page"

    def test_review_button_visible_for_creditor(self, driver, w, ctx):
        review_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/approve-settlement/']")
        assert review_links, \
            "Admin (creditor) must see a Review button for the settlement"
        assert review_links[0].text.strip() == "Review", \
            "Button must be labelled 'Review'"

    def test_creditor_approves_via_review(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR, "a[href*='/approve-settlement/']").click()
        time.sleep(1)
        driver.find_element(
            By.ID, "btn-approve-settlement"
        ).click()
        time.sleep(1)
        assert "confirmed" in driver.page_source.lower(), \
            "Flash must confirm receipt after admin approves"

    def test_waiting_section_gone_after_approval(self, driver, w, ctx):
        assert "Waiting for approval" not in driver.page_source, \
            "Waiting for approval section must disappear after the settlement is approved"

    def test_settlement_now_approved(self, driver, w, ctx):
        approved = _shell(
            f"from budget.models import Expense; "
            f"from feusers.models import FeUser; "
            f"a = FeUser.objects.get(email='{ctx['admin']['email']}'); "
            f"e = Expense.objects.filter(owning_feuser=a, is_buddies_settlement=True, "
            f"  upfront_payee_dummy_id={ctx['dummy_pk']}).first(); "
            f"print(e.buddy_approved if e else 'none')"
        )
        assert approved == "True", \
            "Settlement must be buddy_approved=True after the creditor confirms"
