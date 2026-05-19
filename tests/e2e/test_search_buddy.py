"""
Search: buddy= filter and buddy name free-text.

Covers:
  - buddy=true / buddy=yes / buddy=1   -> only buddy expenses
  - buddy=false / buddy=no / buddy=0   -> only non-buddy expenses
  - buddy=<dummy_name>                 -> match by participant display name
  - buddy=<group_name>                 -> match by group name
  - buddy=<group_member_name>          -> match by group member name
  - free-text <dummy_name>             -> free-text hits participant name
  - free-text <group_name>             -> free-text hits group name

All test expenses carry the unique keyword "BuddySrch" so other data never
interferes.  Setup is done via django shell commands (docker exec) because
buddy spendings are not exposed through the public REST API.
"""
import subprocess
import time

import pytest

from helpers import (
    _url, api_get, api_post, api_delete,
    setup_user, cleanup_user,
    DOCKER_WEB,
)

FIXED_YEAR = 2025
DATE_2025 = "2025-06-15"
DUMMY_NAME = "BuddySrchDummy"
GROUP_NAME = "BuddySrchGroup"
MEMBER_NAME = "BuddySrchMember"


def _shell(code: str) -> str:
    r = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c", code],
        capture_output=True, text=True, timeout=20,
    )
    assert r.returncode == 0, f"Shell failed:\n{r.stderr}"
    return r.stdout.strip()


def _api_titles(ctx, q, year=FIXED_YEAR):
    resp = api_get("/api/v1/expenses/", ctx,
                   params={"q": q, "year": year, "view": "year"})
    assert resp.status_code == 200
    return [e["title"] for e in resp.json()["expenses"]]


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


@pytest.fixture(scope="module", autouse=True)
def setup_data(ctx):
    """Create test expenses (plain and buddy) via ORM shell commands."""
    email = ctx["email"]

    # Plain expense (no buddy spending)
    r = api_post("/api/v1/expenses/", ctx, json={
        "title": "BuddySrch Plain",
        "type": "expense",
        "value": "10.00",
        "date_due": DATE_2025,
    })
    assert r.status_code == 201, r.text
    plain_id = r.json()["id"]
    ctx["bsrch_plain_id"] = plain_id

    # Create a DummyUser owned by this user
    dummy_pk = int(_shell(
        f"from buddies.models import DummyUser; from feusers.models import FeUser; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"d = DummyUser.objects.create(owning_feuser=u, display_name='{DUMMY_NAME}'); "
        f"print(d.pk)"
    ))
    ctx["bsrch_dummy_pk"] = dummy_pk

    # Buddy expense with DummyUser participant
    r = api_post("/api/v1/expenses/", ctx, json={
        "title": "BuddySrch WithDummy",
        "type": "expense",
        "value": "20.00",
        "date_due": DATE_2025,
    })
    assert r.status_code == 201, r.text
    dummy_exp_id = r.json()["id"]
    ctx["bsrch_dummy_exp_id"] = dummy_exp_id
    _shell(
        f"from buddies.models import BuddySpending; "
        f"from budget.models import Expense; "
        f"e = Expense.objects.get(uid={dummy_exp_id}); "
        f"BuddySpending.objects.create(expense=e, participant_dummy_id={dummy_pk}, share_percent=50)"
    )

    # Create a BuddyGroup and link it to another expense
    group_pk = int(_shell(
        f"from buddies.models import Project, BuddyGroupMember, DummyUser; "
        f"from feusers.models import FeUser; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"g = Project.objects.create(name='{GROUP_NAME}', admin_feuser=u); "
        f"d = DummyUser.objects.create(owning_group=g, display_name='{MEMBER_NAME}'); "
        f"BuddyGroupMember.objects.create(group=g, dummy=d); "
        f"print(g.pk)"
    ))
    ctx["bsrch_group_pk"] = group_pk

    r = api_post("/api/v1/expenses/", ctx, json={
        "title": "BuddySrch WithGroup",
        "type": "expense",
        "value": "30.00",
        "date_due": DATE_2025,
    })
    assert r.status_code == 201, r.text
    group_exp_id = r.json()["id"]
    ctx["bsrch_group_exp_id"] = group_exp_id
    _shell(
        f"from budget.models import Expense; "
        f"e = Expense.objects.get(uid={group_exp_id}); "
        f"e.project_id = {group_pk}; "
        f"e.save(update_fields=['project'])"
    )

    yield

    for key in ("bsrch_plain_id", "bsrch_dummy_exp_id", "bsrch_group_exp_id"):
        eid = ctx.get(key)
        if eid:
            api_delete(f"/api/v1/expenses/{eid}/", ctx)
    # Delete dummy user and group via shell (cascade handles spending rows and group members)
    if "bsrch_dummy_pk" in ctx:
        _shell(
            f"from buddies.models import DummyUser; "
            f"DummyUser.objects.filter(pk={ctx['bsrch_dummy_pk']}).delete()"
        )
    if "bsrch_group_pk" in ctx:
        _shell(
            f"from buddies.models import Project; "
            f"Project.objects.filter(pk={ctx['bsrch_group_pk']}).delete()"
        )


class TestBuddyBooleanFilter:

    def test_buddy_true_returns_buddy_expenses(self, driver, w, ctx):
        titles = _api_titles(ctx, "BuddySrch buddy=true")
        assert "BuddySrch WithDummy" in titles
        assert "BuddySrch WithGroup" not in titles  # group expense has no BuddySpending row
        assert "BuddySrch Plain" not in titles

    def test_buddy_yes_alias(self, driver, w, ctx):
        titles = _api_titles(ctx, "BuddySrch buddy=yes")
        assert "BuddySrch WithDummy" in titles
        assert "BuddySrch Plain" not in titles

    def test_buddy_false_returns_non_buddy_expenses(self, driver, w, ctx):
        titles = _api_titles(ctx, "BuddySrch buddy=false")
        assert "BuddySrch Plain" in titles
        assert "BuddySrch WithGroup" in titles  # no BuddySpending row
        assert "BuddySrch WithDummy" not in titles

    def test_buddy_no_alias(self, driver, w, ctx):
        titles = _api_titles(ctx, "BuddySrch buddy=no")
        assert "BuddySrch Plain" in titles
        assert "BuddySrch WithDummy" not in titles


class TestBuddyNameFilter:

    def test_buddy_dummy_name(self, driver, w, ctx):
        titles = _api_titles(ctx, f"BuddySrch buddy={DUMMY_NAME}")
        assert "BuddySrch WithDummy" in titles
        assert "BuddySrch Plain" not in titles
        assert "BuddySrch WithGroup" not in titles

    def test_buddy_group_name(self, driver, w, ctx):
        titles = _api_titles(ctx, f"BuddySrch buddy={GROUP_NAME}")
        assert "BuddySrch WithGroup" in titles
        assert "BuddySrch Plain" not in titles
        assert "BuddySrch WithDummy" not in titles

    def test_buddy_group_member_name(self, driver, w, ctx):
        titles = _api_titles(ctx, f"BuddySrch buddy={MEMBER_NAME}")
        assert "BuddySrch WithGroup" in titles
        assert "BuddySrch Plain" not in titles
        assert "BuddySrch WithDummy" not in titles

    def test_buddy_name_partial_match(self, driver, w, ctx):
        # Partial substring of DUMMY_NAME
        partial = DUMMY_NAME[:8]
        titles = _api_titles(ctx, f"buddy={partial}")
        assert "BuddySrch WithDummy" in titles


class TestBuddyFreeTextSearch:

    def test_freetext_dummy_name_matches_buddy_expense(self, driver, w, ctx):
        titles = _api_titles(ctx, DUMMY_NAME)
        assert "BuddySrch WithDummy" in titles
        assert "BuddySrch Plain" not in titles

    def test_freetext_group_name_matches_group_expense(self, driver, w, ctx):
        titles = _api_titles(ctx, GROUP_NAME)
        assert "BuddySrch WithGroup" in titles
        assert "BuddySrch Plain" not in titles

    def test_freetext_group_member_name_matches_group_expense(self, driver, w, ctx):
        titles = _api_titles(ctx, MEMBER_NAME)
        assert "BuddySrch WithGroup" in titles
        assert "BuddySrch Plain" not in titles
