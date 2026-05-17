"""
Settlement creation email notifications.

When a settlement to a real-user creditor is created via the UI, the creditor
must receive a confirmation-request email immediately.

Settlements to dummy (offline) creditors are auto-approved and send no email
(the dummy cannot receive one), so those paths are not covered here.

Scenarios:
  CN1: Personal settlement (feuser debtor to feuser creditor) sends confirmation email
  CN2: Group settlement (feuser debtor to feuser creditor) sends confirmation email
  CN3: Group settlement (dummy debtor to feuser creditor) sends confirmation email,
       naming the offline member as the debtor, not the admin who submitted the form
"""
import time

import pytest

from helpers import _url, setup_user, cleanup_user, fetch_email, mailpit_seen_ids
from bhelpers import (
    _shell, _login_as, _get_pk,
    _create_buddy_link, _create_group, _add_group_member,
    _create_group_expense, _create_personal_expense_with_buddy,
)


def _mk_group_dummy(group_pk: int, name: str) -> int:
    return int(_shell(
        f"from buddies.models import DummyUser, BuddyGroup, BuddyGroupMember; "
        f"g=BuddyGroup.objects.get(pk={group_pk}); "
        f"d=DummyUser.objects.create(owning_group=g, display_name='{name}'); "
        f"BuddyGroupMember.objects.create(group=g, dummy=d); "
        f"print(d.pk)"
    ))


# ============================================================================
# CN1: Personal settlement creation to real-user creditor
# ============================================================================

class TestPersonalSettlementCreationNotifiesCreditor:
    """[CN1] Creating a personal settlement to a real-user creditor via the buddy
    summary form must immediately send the creditor a confirmation-request email."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="CN1Debtor", last_name="A")
        b = setup_user(None, None, first_name="CN1Creditor", last_name="B")
        _create_buddy_link(a["email"], b["email"])
        a_pk = int(_get_pk(a["email"]))
        b_pk = int(_get_pk(b["email"]))
        _create_personal_expense_with_buddy(
            owner_email=b["email"], participant_pk=a_pk,
            title="CN1Debt", value="100.00", share="50.0", approved=True,
        )
        yield {"a": a, "b": b, "a_pk": a_pk, "b_pk": b_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_creation_sends_confirmation_email_to_creditor(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)
        # Bypass the Alpine.js confirmation dialog by posting to the endpoint directly
        driver.execute_script(
            f"var f=document.createElement('form');"
            f"f.method='POST';f.action='/buddies/settle/freeform/';"
            f"var csrf=document.querySelector('[name=csrfmiddlewaretoken]').value;"
            f"[['csrfmiddlewaretoken',csrf],['debtor_key','f{ctx['a_pk']}'],"
            f" ['creditor_key','f{ctx['b_pk']}'],['amount','50.00']"
            f"].forEach(function(p){{var i=document.createElement('input');"
            f"i.name=p[0];i.value=p[1];f.appendChild(i);}});"
            f"document.body.appendChild(f);f.submit();"
        )
        time.sleep(2)
        body = fetch_email(ctx["b"]["email"], "settlement", ignore_ids=seen_before)
        assert "CN1Debtor" in body, \
            "[CN1] Confirmation email must name the debtor"

    def test_confirmation_email_contains_approve_link(self, driver, w, ctx):
        body = fetch_email(ctx["b"]["email"], "settlement")
        assert "approve-settlement" in body, \
            "[CN1] Confirmation email must contain a link to approve the settlement"


# ============================================================================
# CN2: Group settlement creation (feuser debtor) notifies feuser creditor
# ============================================================================

class TestGroupSettlementCreationNotifiesCreditor:
    """[CN2] Creating a group settlement from a real-user debtor to a real-user creditor
    via the group settle form must immediately send the creditor a confirmation-request email."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="CN2Debtor", last_name="A")
        b = setup_user(None, None, first_name="CN2Creditor", last_name="B")
        grp_pk = int(_create_group(a["email"], "CN2Group"))
        _add_group_member(grp_pk, b["email"])
        a_pk = int(_get_pk(a["email"]))
        b_pk = int(_get_pk(b["email"]))
        # Give B a paid group expense so A owes B something
        _create_group_expense(b["email"], a["email"], grp_pk, value="80.00", share="50.0")
        yield {"a": a, "b": b, "grp_pk": grp_pk, "a_pk": a_pk, "b_pk": b_pk}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_creation_sends_confirmation_email_to_creditor(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/buddies/groups/{ctx['grp_pk']}/"))
        time.sleep(2)
        driver.execute_script(
            f"var f=document.createElement('form');"
            f"f.method='POST';"
            f"f.action='/buddies/groups/{ctx['grp_pk']}/settle-individual/';"
            f"var csrf=document.querySelector('[name=csrfmiddlewaretoken]').value;"
            f"[['csrfmiddlewaretoken',csrf],['debtor_key','f{ctx['a_pk']}'],"
            f" ['creditor_key','f{ctx['b_pk']}'],['amount','40.00']"
            f"].forEach(function(p){{var i=document.createElement('input');"
            f"i.name=p[0];i.value=p[1];f.appendChild(i);}});"
            f"document.body.appendChild(f);f.submit();"
        )
        time.sleep(2)
        body = fetch_email(ctx["b"]["email"], "settlement", ignore_ids=seen_before)
        assert "CN2Debtor" in body, \
            "[CN2] Confirmation email must name the debtor"

    def test_confirmation_email_contains_approve_link(self, driver, w, ctx):
        body = fetch_email(ctx["b"]["email"], "settlement")
        assert "approve-settlement" in body, \
            "[CN2] Confirmation email must contain a link to approve the settlement"

    def test_confirmation_email_mentions_group(self, driver, w, ctx):
        body = fetch_email(ctx["b"]["email"], "settlement")
        assert "CN2Group" in body, \
            "[CN2] Confirmation email must mention the group name"


# ============================================================================
# CN3: Group settlement creation (dummy debtor) notifies feuser creditor,
#      naming the offline member, not the admin
# ============================================================================

class TestGroupDummyDebtorSettlementCreationNotifiesCreditor:
    """[CN3] When an admin creates a group settlement on behalf of an offline member
    toward a real-user creditor, the creditor receives a confirmation-request email
    naming the offline member as the debtor, not the admin."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="CN3Admin", last_name="A")
        creditor = setup_user(None, None, first_name="CN3Creditor", last_name="B")
        grp_pk = int(_create_group(admin["email"], "CN3Group"))
        _add_group_member(grp_pk, creditor["email"])
        creditor_pk = int(_get_pk(creditor["email"]))
        dummy_pk = _mk_group_dummy(grp_pk, "CN3Offline")
        yield {
            "admin": admin, "creditor": creditor,
            "grp_pk": grp_pk, "creditor_pk": creditor_pk, "dummy_pk": dummy_pk,
        }
        cleanup_user(admin["email"])
        cleanup_user(creditor["email"])

    def test_creation_sends_confirmation_email_to_creditor(self, driver, w, ctx):
        seen_before = mailpit_seen_ids()
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/buddies/groups/{ctx['grp_pk']}/"))
        time.sleep(2)
        driver.execute_script(
            f"var f=document.createElement('form');"
            f"f.method='POST';"
            f"f.action='/buddies/groups/{ctx['grp_pk']}/settle-individual/';"
            f"var csrf=document.querySelector('[name=csrfmiddlewaretoken]').value;"
            f"[['csrfmiddlewaretoken',csrf],['debtor_key','d{ctx['dummy_pk']}'],"
            f" ['creditor_key','f{ctx['creditor_pk']}'],['amount','30.00']"
            f"].forEach(function(p){{var i=document.createElement('input');"
            f"i.name=p[0];i.value=p[1];f.appendChild(i);}});"
            f"document.body.appendChild(f);f.submit();"
        )
        time.sleep(2)
        body = fetch_email(ctx["creditor"]["email"], "settlement", ignore_ids=seen_before)
        assert "CN3Offline" in body, \
            "[CN3] Confirmation email must name the offline member as the debtor"

    def test_confirmation_email_does_not_name_admin(self, driver, w, ctx):
        body = fetch_email(ctx["creditor"]["email"], "settlement")
        assert "CN3Admin" not in body, \
            "[CN3] Confirmation email must not name the admin as the debtor"

    def test_confirmation_email_contains_approve_link(self, driver, w, ctx):
        body = fetch_email(ctx["creditor"]["email"], "settlement")
        assert "approve-settlement" in body, \
            "[CN3] Confirmation email must contain a link to approve the settlement"
