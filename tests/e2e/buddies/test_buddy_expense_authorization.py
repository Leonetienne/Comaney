"""
Regression tests for TICKET-02 — missing authorization on buddy-expense upfront
payer & participants (cross-user record creation, IDOR).

When creating a buddy/project expense, the server trusts the FeUser / DummyUser
ids in the POST body without checking that those identities are connected to the
acting user. Three abuses:

  #1  buddy_upfront_type=feuser + a stranger's pk  -> the new expense is saved with
      owning_feuser = <victim> (and an approval email is pushed at them).
  #2  buddy_upfront_type=dummy + another user's DummyUser pk -> foreign offline-buddy
      record attached to the attacker's expense (IDOR).
  #3  a participant with a stranger's / foreign-dummy id -> unauthorised BuddySpending
      rows written.

These tests drive the real web create endpoint and the express `confirm` endpoint
as an *attacker* who has no relationship to the victim, and assert the submission
is rejected (no cross-user row created).

EXPECTED TO FAIL until authorization is enforced: today the expenses are created.

Run with (live stack at :8080 required):
    pytest tests/e2e/buddies/test_buddy_expense_authorization.py -sxv | tee logfile.log
"""
import json
import re
import time

import pytest

from helpers import (
    _url, http_session, form_login, create_confirmed_user, cleanup_user,
    mailpit_seen_ids, fetch_email,
)
from bhelpers import _shell, _get_pk


# ── Fixtures: an attacker (who logs in) and an unrelated victim ───────────────

@pytest.fixture(scope="module")
def victim():
    v = create_confirmed_user(first_name="Vic", last_name="Tim")
    v["pk"] = _get_pk(v["email"])
    # A private offline buddy owned by the victim (for the IDOR abuses).
    v["dummy_pk"] = _shell(
        f"from feusers.models import FeUser; from buddies.models import DummyUser; "
        f"o = FeUser.objects.get(email='{v['email']}'); "
        f"d = DummyUser.objects.create(owning_feuser=o, display_name='VictimsSecretDummy'); "
        f"print(d.pk)"
    )
    yield v
    cleanup_user(v["email"])


@pytest.fixture(scope="module")
def attacker():
    a = create_confirmed_user(first_name="Mal", last_name="Ice")
    a["pk"] = _get_pk(a["email"])
    yield a
    cleanup_user(a["email"])


@pytest.fixture()
def sess(attacker):
    s = http_session()
    resp = form_login(s, attacker["email"], attacker["password"])
    assert resp.status_code in (301, 302), f"attacker login failed: {resp.status_code}"
    return s


# ── Helpers ──────────────────────────────────────────────────────────────────

def _post_expense_create(session, fields: dict):
    """GET the create form (primes the session nonce + csrftoken), then POST
    `fields` merged with the required anti-duplicate nonce and csrf token."""
    get = session.get(_url("/budget/expenses/new/"), timeout=10)
    csrf = session.cookies.get("csrftoken", "")
    m = (re.search(r'name="form_nonce"[^>]*value="([^"]+)"', get.text)
         or re.search(r'value="([^"]+)"[^>]*name="form_nonce"', get.text))
    nonce = m.group(1) if m else ""
    payload = {"csrfmiddlewaretoken": csrf, "form_nonce": nonce, **fields}
    return session.post(
        _url("/budget/expenses/new/"), data=payload,
        headers={"Referer": _url("/budget/expenses/new/")},
        allow_redirects=False, timeout=10,
    )


def _count(code_expr: str) -> int:
    return int(_shell(code_expr))


# ── Abuse #1: create an expense owned by an arbitrary victim ─────────────────

class TestUpfrontFeuserAuthorization:

    def test_cannot_create_expense_owned_by_stranger(self, sess, attacker, victim):
        title = f"IDOR-OWN-{int(time.time())}"
        _post_expense_create(sess, {
            "title": title,
            "type": "expense",
            "value": "13.37",
            "settled": "on",
            "notify": "on",
            "buddy_payment": "1",
            "buddy_mode": "single",
            "buddy_upfront_type": "feuser",
            "buddy_upfront_id": victim["pk"],
            "buddy_spendings_json": json.dumps(
                [{"type": "feuser", "id": int(attacker["pk"]), "share_percent": 50}]
            ),
        })
        planted = _count(
            f"from budget.models import Expense; "
            f"print(Expense.objects.filter(owning_feuser__email='{victim['email']}', "
            f"title='{title}').count())"
        )
        assert planted == 0, \
            "Expense was planted in a stranger's account (owning_feuser=victim)"

    def test_no_approval_email_sent_to_stranger(self, sess, attacker, victim):
        seen = mailpit_seen_ids()
        title = f"IDOR-MAIL-{int(time.time())}"
        _post_expense_create(sess, {
            "title": title, "type": "expense", "value": "9.99",
            "settled": "on", "notify": "on",
            "buddy_payment": "1", "buddy_mode": "single",
            "buddy_upfront_type": "feuser", "buddy_upfront_id": victim["pk"],
            "buddy_spendings_json": json.dumps(
                [{"type": "feuser", "id": int(attacker["pk"]), "share_percent": 50}]
            ),
        })
        with pytest.raises(TimeoutError):
            # An approval-request email to the victim would be spam pushed by the
            # attacker; it must never arrive.
            fetch_email(victim["email"], "approval", timeout=8, ignore_ids=seen)


# ── Abuse #2: IDOR on another user's DummyUser (upfront payer) ───────────────

class TestUpfrontDummyIdor:

    def test_cannot_attach_foreign_dummy_as_upfront_payer(self, sess, attacker, victim):
        title = f"IDOR-DUMMY-{int(time.time())}"
        _post_expense_create(sess, {
            "title": title, "type": "expense", "value": "20.00",
            "settled": "on", "notify": "on",
            "buddy_payment": "1", "buddy_mode": "single",
            "buddy_upfront_type": "dummy", "buddy_upfront_id": victim["dummy_pk"],
            "buddy_spendings_json": json.dumps(
                [{"type": "feuser", "id": int(attacker["pk"]), "share_percent": 50}]
            ),
        })
        leaked = _count(
            f"from budget.models import Expense; "
            f"print(Expense.objects.filter(owning_feuser__email='{attacker['email']}', "
            f"upfront_payee_dummy__pk={victim['dummy_pk']}).count())"
        )
        assert leaked == 0, \
            "Attacker attached the victim's private DummyUser as the upfront payer (IDOR)"


# ── Abuse #3: foreign dummy injected as a participant ────────────────────────

class TestParticipantDummyIdor:

    def test_cannot_add_foreign_dummy_as_participant(self, sess, attacker, victim):
        title = f"IDOR-PART-{int(time.time())}"
        _post_expense_create(sess, {
            "title": title, "type": "expense", "value": "42.00",
            "settled": "on", "notify": "on",
            "buddy_payment": "1", "buddy_mode": "single",
            "buddy_upfront_type": "me",
            "buddy_spendings_json": json.dumps(
                [{"type": "dummy", "id": int(victim["dummy_pk"]), "share_percent": 50}]
            ),
        })
        rows = _count(
            f"from buddies.models import BuddySpending; "
            f"print(BuddySpending.objects.filter(participant_dummy__pk={victim['dummy_pk']}, "
            f"expense__owning_feuser__email='{attacker['email']}').count())"
        )
        assert rows == 0, \
            "Attacker attached the victim's private DummyUser as a participant (IDOR)"


# ── Express confirm path: same authorization gap via _parse_buddy_item ───────

class TestExpressConfirmAuthorization:

    def test_express_confirm_cannot_create_expense_for_stranger(self, sess, attacker, victim):
        # The confirm branch needs an API key present (else it redirects to profile).
        # The confirm path itself never calls the AI, so a dummy key is fine.
        _shell(
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{attacker['email']}'); "
            f"u.anthropic_api_key = 'sk-ant-dummy-for-test'; "
            f"u.save(update_fields=['anthropic_api_key'])"
        )
        title = f"EXPRESS-IDOR-{int(time.time())}"
        preview = [{
            "title": title,
            "type": "expense",
            "value": "5.00",
            "buddy_payment": True,
            "buddy_mode": "single",
            "buddy_upfront_type": "feuser",
            "buddy_upfront_id": int(victim["pk"]),
            "buddy_spendings": [{"type": "feuser", "id": int(attacker["pk"]), "share_percent": 50}],
        }]
        get = sess.get(_url("/budget/ai/express-creation/"), timeout=10)
        csrf = sess.cookies.get("csrftoken", "")
        sess.post(
            _url("/budget/ai/express-creation/"),
            data={
                "csrfmiddlewaretoken": csrf,
                "action": "confirm",
                "preview_json": json.dumps(preview),
            },
            headers={"Referer": _url("/budget/ai/express-creation/")},
            allow_redirects=False, timeout=10,
        )
        planted = _count(
            f"from budget.models import Expense; "
            f"print(Expense.objects.filter(owning_feuser__email='{victim['email']}', "
            f"title='{title}').count())"
        )
        assert planted == 0, \
            "Express confirm planted an expense in a stranger's account (owning_feuser=victim)"
