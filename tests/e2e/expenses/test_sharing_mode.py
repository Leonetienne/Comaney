"""
Sharing-mode queryset, effective_value annotation, and search-filter tests.

Two users are created: A (primary) and B (for foreign expenses).

Expense fixtures
----------------
sm_plain        – A, no spendings,   value=100
sm_dummy_part   – A, DummyShrMode is participant at 50%,  value=80
sm_dummy_payer  – A, is_dummy=True, DummyShrMode paid upfront;
                    B owes 40% via BuddySpending -> A's implied share 60%,
                    effective_value = 60 * 0.60 = 36.00
sm_foreign      – B owns it, A is BuddySpending participant at 30%,
                    effective_value = 90 * 0.30 = 27.00
sm_settlement   – A, is_buddies_settlement=True (always excluded from shared qs)

Queryset tests
--------------
personal mode  : sm_plain, sm_dummy_part  INCLUDED
                 sm_dummy_payer (is_dummy=True), sm_foreign, sm_settlement  EXCLUDED
shared mode    : all four non-settlement expenses INCLUDED; sm_settlement EXCLUDED

effective_value tests (shared mode)
------------------------------------
sm_plain        -> effective_value == 100.00
sm_dummy_part   -> effective_value ==  40.00   (80 * 50/100 owner residual)
sm_dummy_payer  -> effective_value ==  36.00   (60 * 60/100 owner residual)
sm_foreign      -> effective_value ==  27.00   (90 * 30/100 participant share)

payer= filter tests
--------------------
personal, payer=DummyShrMode  -> nothing   (dummy is not owning_feuser)
personal, payer=me            -> sm_plain, sm_dummy_part  (own expenses)
shared,   payer=DummyShrMode  -> sm_dummy_payer only   (upfront payer)
shared,   payer=DummyShrMode  NOT sm_dummy_part        (participant, not payer)
shared,   payer=B_last_name   -> sm_foreign

participant= filter tests
--------------------------
personal, participant=me           -> sm_plain, sm_dummy_part
personal, participant=DummyShrMode -> sm_dummy_part   (dummy is participant there)
shared,   participant=me           -> all four non-settlement expenses
shared,   participant=DummyShrMode -> sm_dummy_part (participant) + sm_dummy_payer (owner)

shared= filter tests
---------------------
shared=true   -> sm_dummy_part, sm_dummy_payer, sm_foreign  (have BuddySpending rows)
shared=false  -> sm_plain
"""
import subprocess
import time
from decimal import Decimal

import pytest

from helpers import (
    api_get, api_post, api_delete,
    setup_user, cleanup_user,
    DOCKER_WEB,
)

FIXED_YEAR = 2024
DATE = "2024-07-20"
DUMMY_NAME = "DummyShrMode"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _shell(code: str) -> str:
    r = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c", code],
        capture_output=True, text=True, timeout=20,
    )
    assert r.returncode == 0, f"Shell failed:\n{r.stderr}"
    return r.stdout.strip()


def _expenses(ctx, q, sharing="", year=FIXED_YEAR):
    params = {"q": q, "year": year, "view": "year"}
    if sharing:
        params["sharing"] = sharing
    resp = api_get("/api/v1/expenses/", ctx, params=params)
    assert resp.status_code == 200
    return resp.json()["expenses"]


def _titles(ctx, q, sharing=""):
    return [e["title"] for e in _expenses(ctx, q=q, sharing=sharing)]


def _by_title(ctx, title, sharing=""):
    return next((e for e in _expenses(ctx, q=title, sharing=sharing)
                 if e["title"] == title), None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ctx_a(driver, w):
    c = setup_user(driver, w, last_name="UserA")
    yield c
    cleanup_user(c["email"])


@pytest.fixture(scope="module")
def ctx_b(driver, w):
    c = setup_user(driver, w, last_name="UserB")
    yield c
    cleanup_user(c["email"])


@pytest.fixture(scope="module", autouse=True)
def setup_data(ctx_a, ctx_b):
    email_a = ctx_a["email"]
    email_b = ctx_b["email"]

    # sm_plain – A's solo expense
    r = api_post("/api/v1/expenses/", ctx_a, json={
        "title": "ShrMode Plain", "type": "expense",
        "value": "100.00", "date_due": DATE,
    })
    assert r.status_code == 201
    ctx_a["sm_plain"] = r.json()["id"]

    # Create DummyUser owned by A
    dummy_pk = int(_shell(
        f"from buddies.models import DummyUser; from feusers.models import FeUser; "
        f"u = FeUser.objects.get(email='{email_a}'); "
        f"d = DummyUser.objects.create(owning_feuser=u, display_name='{DUMMY_NAME}'); "
        f"print(d.pk)"
    ))
    ctx_a["sm_dummy_pk"] = dummy_pk

    # sm_dummy_part – A paid, dummy is participant at 50% -> owner residual 50%
    r = api_post("/api/v1/expenses/", ctx_a, json={
        "title": "ShrMode DummyParticipant", "type": "expense",
        "value": "80.00", "date_due": DATE,
    })
    assert r.status_code == 201
    ctx_a["sm_dummy_part"] = r.json()["id"]
    _shell(
        f"from buddies.models import BuddySpending; from budget.models import Expense; "
        f"e = Expense.objects.get(uid={ctx_a['sm_dummy_part']}); "
        f"BuddySpending.objects.create(expense=e, participant_dummy_id={dummy_pk}, share_percent=50)"
    )

    # sm_dummy_payer – dummy paid upfront (is_dummy=True); B owes 40%, A implied 60%
    r = api_post("/api/v1/expenses/", ctx_a, json={
        "title": "ShrMode DummyPayer", "type": "expense",
        "value": "60.00", "date_due": DATE,
    })
    assert r.status_code == 201
    ctx_a["sm_dummy_payer"] = r.json()["id"]
    _shell(
        f"from buddies.models import BuddySpending; from budget.models import Expense; "
        f"from feusers.models import FeUser; "
        f"e = Expense.objects.get(uid={ctx_a['sm_dummy_payer']}); "
        f"e.is_dummy = True; e.upfront_payee_dummy_id = {dummy_pk}; "
        f"e.save(update_fields=['is_dummy', 'upfront_payee_dummy']); "
        f"b = FeUser.objects.get(email='{email_b}'); "
        f"BuddySpending.objects.create(expense=e, participant_feuser=b, share_percent=40)"
    )

    # sm_foreign – B owns it, A is participant at 30%
    foreign_uid = int(_shell(
        f"from budget.models import Expense; from buddies.models import BuddySpending; "
        f"from feusers.models import FeUser; "
        f"a = FeUser.objects.get(email='{email_a}'); "
        f"b = FeUser.objects.get(email='{email_b}'); "
        f"e = Expense.objects.create(owning_feuser=b, title='ShrMode Foreign', "
        f"    type='expense', value='90.00', date_due='{DATE}', "
        f"    settled=True, is_dummy=False, buddy_approved=True); "
        f"BuddySpending.objects.create(expense=e, participant_feuser=a, share_percent=30); "
        f"print(e.uid)"
    ))
    ctx_a["sm_foreign"] = foreign_uid

    # sm_settlement – excluded from shared qs regardless
    r = api_post("/api/v1/expenses/", ctx_a, json={
        "title": "ShrMode Settlement", "type": "expense",
        "value": "50.00", "date_due": DATE,
    })
    assert r.status_code == 201
    ctx_a["sm_settlement"] = r.json()["id"]
    _shell(
        f"from budget.models import Expense; "
        f"e = Expense.objects.get(uid={ctx_a['sm_settlement']}); "
        f"e.is_buddies_settlement = True; e.save(update_fields=['is_buddies_settlement'])"
    )

    yield

    # Cleanup own expenses via API
    for key in ("sm_plain", "sm_dummy_part", "sm_dummy_payer", "sm_settlement"):
        uid = ctx_a.get(key)
        if uid:
            api_delete(f"/api/v1/expenses/{uid}/", ctx_a)
    # Foreign expense and dummy via shell
    if "sm_foreign" in ctx_a:
        _shell(
            f"from budget.models import Expense; "
            f"Expense.objects.filter(uid={ctx_a['sm_foreign']}).delete()"
        )
    if "sm_dummy_pk" in ctx_a:
        _shell(
            f"from buddies.models import DummyUser; "
            f"DummyUser.objects.filter(pk={ctx_a['sm_dummy_pk']}).delete()"
        )


# ---------------------------------------------------------------------------
# Queryset inclusion / exclusion
# ---------------------------------------------------------------------------

class TestQuerysetPersonalMode:

    def test_plain_own_expense_included(self, driver, w, ctx_a):
        titles = _titles(ctx_a, "ShrMode Plain")
        assert "ShrMode Plain" in titles

    def test_dummy_participant_expense_included(self, driver, w, ctx_a):
        titles = _titles(ctx_a, "ShrMode DummyParticipant")
        assert "ShrMode DummyParticipant" in titles

    def test_dummy_payer_expense_excluded(self, driver, w, ctx_a):
        # is_dummy=True expenses do not appear in personal mode
        titles = _titles(ctx_a, "ShrMode DummyPayer")
        assert "ShrMode DummyPayer" not in titles

    def test_foreign_expense_excluded(self, driver, w, ctx_a):
        titles = _titles(ctx_a, "ShrMode Foreign")
        assert "ShrMode Foreign" not in titles

    def test_settlement_visible_in_personal_mode(self, driver, w, ctx_a):
        # Personal mode does NOT filter settlements — they appear in the list
        titles = _titles(ctx_a, "ShrMode Settlement")
        assert "ShrMode Settlement" in titles


class TestQuerysetSharedMode:

    def test_plain_own_expense_included(self, driver, w, ctx_a):
        titles = _titles(ctx_a, "ShrMode Plain", sharing="shared")
        assert "ShrMode Plain" in titles

    def test_dummy_participant_expense_included(self, driver, w, ctx_a):
        titles = _titles(ctx_a, "ShrMode DummyParticipant", sharing="shared")
        assert "ShrMode DummyParticipant" in titles

    def test_dummy_payer_expense_included(self, driver, w, ctx_a):
        # is_dummy=True own expenses appear in shared mode
        titles = _titles(ctx_a, "ShrMode DummyPayer", sharing="shared")
        assert "ShrMode DummyPayer" in titles

    def test_foreign_expense_included(self, driver, w, ctx_a):
        titles = _titles(ctx_a, "ShrMode Foreign", sharing="shared")
        assert "ShrMode Foreign" in titles

    def test_settlement_excluded(self, driver, w, ctx_a):
        titles = _titles(ctx_a, "ShrMode Settlement", sharing="shared")
        assert "ShrMode Settlement" not in titles


# ---------------------------------------------------------------------------
# effective_value annotation (shared mode only)
# ---------------------------------------------------------------------------

class TestEffectiveValue:

    def test_plain_own_no_spendings(self, driver, w, ctx_a):
        e = _by_title(ctx_a, "ShrMode Plain", sharing="shared")
        assert e is not None
        assert Decimal(e["effective_value"]) == Decimal("100.00")

    def test_own_expense_dummy_participant_50pct(self, driver, w, ctx_a):
        # A paid 80, dummy owes 50% back -> A's residual share = 50% = 40.00
        e = _by_title(ctx_a, "ShrMode DummyParticipant", sharing="shared")
        assert e is not None
        assert Decimal(e["effective_value"]) == Decimal("40.00")

    def test_own_expense_dummy_payer_b_at_40pct(self, driver, w, ctx_a):
        # Dummy paid 60, B owes 40% -> A's implied residual = 60% = 36.00
        e = _by_title(ctx_a, "ShrMode DummyPayer", sharing="shared")
        assert e is not None
        assert Decimal(e["effective_value"]) == Decimal("36.00")

    def test_foreign_expense_a_at_30pct(self, driver, w, ctx_a):
        # B owns 90, A is participant at 30% -> A owes 27.00
        e = _by_title(ctx_a, "ShrMode Foreign", sharing="shared")
        assert e is not None
        assert Decimal(e["effective_value"]) == Decimal("27.00")

    def test_personal_mode_has_no_effective_value(self, driver, w, ctx_a):
        # effective_value is null in personal mode
        e = _by_title(ctx_a, "ShrMode Plain", sharing="")
        assert e is not None
        assert e["effective_value"] is None


# ---------------------------------------------------------------------------
# payer= filter
# ---------------------------------------------------------------------------

class TestPayerFilter:

    def test_payer_dummy_personal_returns_nothing(self, driver, w, ctx_a):
        # Dummy is never owning_feuser, so personal mode returns nothing
        titles = _titles(ctx_a, f"ShrMode payer={DUMMY_NAME}")
        assert not any("ShrMode" in t for t in titles)

    def test_payer_me_personal_returns_own_expenses(self, driver, w, ctx_a):
        titles = _titles(ctx_a, "ShrMode payer=me")
        assert "ShrMode Plain" in titles
        assert "ShrMode DummyParticipant" in titles
        assert "ShrMode Foreign" not in titles

    def test_payer_dummy_shared_returns_dummy_payer_expense(self, driver, w, ctx_a):
        titles = _titles(ctx_a, f"ShrMode payer={DUMMY_NAME}", sharing="shared")
        assert "ShrMode DummyPayer" in titles

    def test_payer_dummy_shared_does_not_return_participant_expense(self, driver, w, ctx_a):
        # Dummy is a participant in DummyParticipant, NOT the payer
        titles = _titles(ctx_a, f"ShrMode payer={DUMMY_NAME}", sharing="shared")
        assert "ShrMode DummyParticipant" not in titles

    def test_payer_b_name_shared_returns_foreign_expense(self, driver, w, ctx_a):
        titles = _titles(ctx_a, "ShrMode payer=UserB", sharing="shared")
        assert "ShrMode Foreign" in titles
        assert "ShrMode Plain" not in titles

    def test_payer_me_shared_returns_own_expenses_not_foreign(self, driver, w, ctx_a):
        titles = _titles(ctx_a, "ShrMode payer=me", sharing="shared")
        assert "ShrMode Plain" in titles
        assert "ShrMode DummyParticipant" in titles
        assert "ShrMode DummyPayer" in titles
        assert "ShrMode Foreign" not in titles


# ---------------------------------------------------------------------------
# participant= filter
# ---------------------------------------------------------------------------

class TestParticipantFilter:

    def test_participant_me_personal_returns_own(self, driver, w, ctx_a):
        titles = _titles(ctx_a, "ShrMode participant=me")
        assert "ShrMode Plain" in titles
        assert "ShrMode DummyParticipant" in titles
        assert "ShrMode Foreign" not in titles

    def test_participant_dummy_personal_returns_expense_with_dummy(self, driver, w, ctx_a):
        titles = _titles(ctx_a, f"ShrMode participant={DUMMY_NAME}")
        assert "ShrMode DummyParticipant" in titles
        assert "ShrMode Plain" not in titles

    def test_participant_me_shared_returns_own_and_foreign(self, driver, w, ctx_a):
        titles = _titles(ctx_a, "ShrMode participant=me", sharing="shared")
        assert "ShrMode Plain" in titles
        assert "ShrMode DummyParticipant" in titles
        assert "ShrMode DummyPayer" in titles
        assert "ShrMode Foreign" in titles

    def test_participant_dummy_shared_matches_participant_expense(self, driver, w, ctx_a):
        titles = _titles(ctx_a, f"ShrMode participant={DUMMY_NAME}", sharing="shared")
        assert "ShrMode DummyParticipant" in titles
        assert "ShrMode Plain" not in titles
        assert "ShrMode Foreign" not in titles

    def test_participant_dummy_shared_also_matches_upfront_payer_expense(self, driver, w, ctx_a):
        # Dummy is the upfront_payee_dummy on DummyPayer — participant= includes upfront payer
        titles = _titles(ctx_a, f"ShrMode participant={DUMMY_NAME}", sharing="shared")
        assert "ShrMode DummyPayer" in titles


# ---------------------------------------------------------------------------
# shared= filter (replaces old buddy=)
# ---------------------------------------------------------------------------

class TestSharedFilter:

    def test_shared_true_returns_expenses_with_spendings(self, driver, w, ctx_a):
        titles = _titles(ctx_a, "ShrMode shared=true", sharing="shared")
        assert "ShrMode DummyParticipant" in titles
        assert "ShrMode DummyPayer" in titles
        assert "ShrMode Foreign" in titles
        assert "ShrMode Plain" not in titles

    def test_shared_false_returns_expenses_without_spendings(self, driver, w, ctx_a):
        titles = _titles(ctx_a, "ShrMode shared=false", sharing="shared")
        assert "ShrMode Plain" in titles
        assert "ShrMode DummyParticipant" not in titles
        assert "ShrMode DummyPayer" not in titles

    def test_shared_true_personal_mode(self, driver, w, ctx_a):
        # In personal mode, shared=true also works on the personal queryset
        titles = _titles(ctx_a, "ShrMode shared=true")
        assert "ShrMode DummyParticipant" in titles
        assert "ShrMode Plain" not in titles

    def test_shared_false_personal_mode(self, driver, w, ctx_a):
        titles = _titles(ctx_a, "ShrMode shared=false")
        assert "ShrMode Plain" in titles
        assert "ShrMode DummyParticipant" not in titles
