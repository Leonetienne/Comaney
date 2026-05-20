"""
Direct buddy expense delete: the owning feuser can delete their own direct
(non-settlement) buddy expense from the buddy summary page.

Covers:
- Delete button is visible for the owner on /buddies/summary/
- Delete button is NOT visible for the other participant
- Confirming delete removes the expense from the page and the database
- A direct POST by the non-owner is rejected (expense survives)
"""
import time

import pytest
import requests as req

from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import (
    _shell, _login_as, _create_buddy_link, _get_pk,
    _create_personal_expense_with_buddy,
)


def _expense_exists(exp_pk: str) -> bool:
    count = _shell(
        f"from budget.models import Expense; "
        f"print(Expense.objects.filter(pk={exp_pk}).count())"
    )
    return count == "1"


# ---------------------------------------------------------------------------
# Owner sees and can use the delete button
# ---------------------------------------------------------------------------

class TestOwnerDeletesDirectBuddyExpense:
    """The owning feuser can delete their own direct buddy expense from the
    buddy summary page."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        owner = setup_user(driver, w, first_name="DirDel", last_name="Owner")
        partner = setup_user(None, None, first_name="DirDel", last_name="Partner")
        _create_buddy_link(owner["email"], partner["email"])
        partner_pk = int(_get_pk(partner["email"]))
        exp_pk = _create_personal_expense_with_buddy(
            owner_email=owner["email"],
            participant_pk=partner_pk,
            title="Direct Deletable Expense",
            value="80.00",
            share="50.0",
            approved=True,
        )
        yield {"owner": owner, "partner": partner, "exp_pk": exp_pk}
        cleanup_user(owner["email"])
        cleanup_user(partner["email"])

    def test_expense_visible_on_summary(self, driver, w, ctx):
        _login_as(driver, ctx["owner"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Direct Deletable Expense" in driver.page_source, \
            "Direct buddy expense must appear on the summary page for the owner"

    def test_delete_button_visible_for_owner(self, driver, w, ctx):
        delete_forms = driver.find_elements(
            By.CSS_SELECTOR, "form[action*='/delete/']"
        )
        assert delete_forms, \
            "Owner must see a delete button for their own direct buddy expense"

    def test_owner_deletes_expense(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR, "[id^='btn-delete-exp-']").click()
        time.sleep(0.5)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(1)
        assert "deleted" in driver.page_source.lower(), \
            "Flash message must confirm the expense was deleted"

    def test_expense_gone_from_summary(self, driver, w, ctx):
        assert "Direct Deletable Expense" not in driver.page_source, \
            "Deleted expense must no longer appear on the summary page"

    def test_expense_removed_from_database(self, driver, w, ctx):
        assert not _expense_exists(ctx["exp_pk"]), \
            "Deleted expense must be gone from the database"


# ---------------------------------------------------------------------------
# Non-owner (participant) has no delete button
# ---------------------------------------------------------------------------

class TestParticipantCannotDeleteDirectBuddyExpense:
    """The participant (non-owner) must not see a delete button and a direct
    POST must not delete the expense."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        owner = setup_user(None, None, first_name="NDirO", last_name="Owner")
        partner = setup_user(driver, w, first_name="NDirP", last_name="Partner")
        _create_buddy_link(owner["email"], partner["email"])
        partner_pk = int(_get_pk(partner["email"]))
        exp_pk = _create_personal_expense_with_buddy(
            owner_email=owner["email"],
            participant_pk=partner_pk,
            title="Owner Only Direct Expense",
            value="60.00",
            share="50.0",
            approved=True,
        )
        yield {"owner": owner, "partner": partner, "exp_pk": exp_pk}
        cleanup_user(owner["email"])
        cleanup_user(partner["email"])

    def test_expense_visible_to_participant(self, driver, w, ctx):
        _login_as(driver, ctx["partner"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "Owner Only Direct Expense" in driver.page_source, \
            "Expense must be visible to the participant"

    def test_no_delete_button_for_participant(self, driver, w, ctx):
        delete_forms = driver.find_elements(
            By.CSS_SELECTOR, "form[action*='/delete/']"
        )
        assert not delete_forms, \
            "Participant must not see a delete button for the owner's expense"

    def test_direct_post_does_not_delete_expense(self, driver, w, ctx):
        cookie_dict = {c["name"]: c["value"] for c in driver.get_cookies()}
        csrftoken = cookie_dict.get("csrftoken", "")
        sessionid = cookie_dict.get("sessionid", "")
        req.post(
            _url(f"/budget/expenses/{ctx['exp_pk']}/delete/"),
            data={"csrfmiddlewaretoken": csrftoken},
            headers={"X-CSRFToken": csrftoken, "Referer": _url("/buddies/summary/")},
            cookies={"csrftoken": csrftoken, "sessionid": sessionid},
            timeout=10,
            allow_redirects=True,
        )
        assert _expense_exists(ctx["exp_pk"]), \
            "Unauthorized direct POST must not delete the expense from the database"
