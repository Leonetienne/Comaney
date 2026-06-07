"""
Search: tag= / cat= filters must respect ownership in shared mode.

Regression test: the query parser used to match `tag=`/`cat=` against the raw
`Expense.tags`/`Expense.category` fields regardless of who owned them, so a
buddy could search for expenses using the OTHER participant's tag/category
names and find them, even without an overlay of their own. Fix location:
`_tag_q()`/`_cat_q()` in budget/query_parser.py, which now only match a
foreign expense through the searching feuser's own ExpenseDataOverlay, never
through the owner's direct tags/category (mirrors the isolation already
enforced for dashboard charts, see test_tag_category_dashboard_isolation.py).

All test expenses carry the unique keyword "TagCatSrch" so other data never
interferes. Uses the REST API (Bearer token) exclusively; no browser needed.

Run with: venv/bin/pytest tests/e2e/expenses/test_search_tag_cat_isolation.py -v
"""
import subprocess

import pytest

from helpers import api_get, setup_user, cleanup_user, DOCKER_WEB
from bhelpers import _create_group, _add_group_member

FIXED_YEAR = 2025
DATE_2025 = "2025-06-15"


def _shell(code: str) -> str:
    r = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c", code],
        capture_output=True, text=True, timeout=20,
    )
    assert r.returncode == 0, f"Shell failed:\n{r.stderr}"
    return r.stdout.strip()


def _api_titles(ctx, q, sharing="shared"):
    resp = api_get("/api/v1/expenses/", ctx,
                   params={"q": q, "year": FIXED_YEAR, "view": "year", "sharing": sharing})
    assert resp.status_code == 200, resp.text
    return [e["title"] for e in resp.json()["expenses"]]


@pytest.fixture(scope="module")
def ctx(driver, w):
    a = setup_user(driver, w, first_name="Alice", last_name="TagCatSrch")
    b = setup_user(None, None, first_name="Bob", last_name="TagCatSrch")

    gid = int(_create_group(a["email"], "TagCatSrchGroup"))
    _add_group_member(gid, b["email"])

    exp_id = int(_shell(
        f"import datetime; "
        f"from budget.models import Expense, Tag, Category; "
        f"from buddies.models import Project, BuddySpending; "
        f"from feusers.models import FeUser; from decimal import Decimal; "
        f"a = FeUser.objects.get(email='{a['email']}'); "
        f"b = FeUser.objects.get(email='{b['email']}'); "
        f"g = Project.objects.get(pk={gid}); "
        f"tag, _ = Tag.objects.get_or_create(owning_feuser=a, title='AliceTagCatSrchTag'); "
        f"cat, _ = Category.objects.get_or_create(owning_feuser=a, title='AliceTagCatSrchCat'); "
        f"e = Expense.objects.create(owning_feuser=a, title='TagCatSrch AliceExpense', "
        f"  type='expense', value=Decimal('80.00'), settled=False, "
        f"  buddy_approved=True, project=g, category=cat, "
        f"  date_due=datetime.date.fromisoformat('{DATE_2025}')); "
        f"e.tags.add(tag); "
        f"BuddySpending.objects.create(expense=e, participant_feuser=b, share_percent=Decimal('50')); "
        f"print(e.uid)"
    ))

    yield {"a": a, "b": b, "gid": gid, "exp_id": exp_id}

    cleanup_user(a["email"])
    cleanup_user(b["email"])


class TestTagCatSearchIsolation:

    def test_b_tag_search_does_not_find_alice_tag(self, ctx):
        """B searching by A's tag must not find A's expense: B owns neither
        the tag nor an overlay referencing it."""
        titles = _api_titles(ctx["b"], "TagCatSrch tag=AliceTagCatSrchTag")
        assert "TagCatSrch AliceExpense" not in titles, (
            f"B's tag search leaked A's tag 'AliceTagCatSrchTag'. Got titles: {titles}"
        )

    def test_b_cat_search_does_not_find_alice_category(self, ctx):
        """B searching by A's category must not find A's expense."""
        titles = _api_titles(ctx["b"], "TagCatSrch cat=AliceTagCatSrchCat")
        assert "TagCatSrch AliceExpense" not in titles, (
            f"B's category search leaked A's category 'AliceTagCatSrchCat'. Got titles: {titles}"
        )

    def test_a_tag_search_finds_own_tag(self, ctx):
        """Sanity check: A searching by A's own tag DOES find A's expense."""
        titles = _api_titles(ctx["a"], "TagCatSrch tag=AliceTagCatSrchTag")
        assert "TagCatSrch AliceExpense" in titles, (
            f"A's own tag search should find A's expense. Got titles: {titles}"
        )

    def test_a_cat_search_finds_own_category(self, ctx):
        """Sanity check: A searching by A's own category DOES find A's expense."""
        titles = _api_titles(ctx["a"], "TagCatSrch cat=AliceTagCatSrchCat")
        assert "TagCatSrch AliceExpense" in titles, (
            f"A's own category search should find A's expense. Got titles: {titles}"
        )

    def test_b_tag_none_matches_alice_expense_without_overlay(self, ctx):
        """B has no overlay on A's expense, so it counts as untagged for B
        and must match tag=none."""
        titles = _api_titles(ctx["b"], "TagCatSrch tag=none")
        assert "TagCatSrch AliceExpense" in titles, (
            f"Foreign expense with no overlay should count as untagged for B. Got titles: {titles}"
        )

    def test_b_overlay_tag_search_finds_alice_expense(self, ctx):
        """Once B sets their own overlay tag on A's expense, searching by
        that overlay tag (and only that tag) finds the expense."""
        _shell(
            f"from budget.services import upsert_overlay; "
            f"from budget.models import Tag, Expense; "
            f"from feusers.models import FeUser; "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"e = Expense.objects.get(uid={ctx['exp_id']}); "
            f"tag, _ = Tag.objects.get_or_create(owning_feuser=b, title='BobTagCatSrchOverlayTag'); "
            f"upsert_overlay(e, b, None, [tag])"
        )
        try:
            titles = _api_titles(ctx["b"], "TagCatSrch tag=BobTagCatSrchOverlayTag")
            assert "TagCatSrch AliceExpense" in titles, (
                f"B's overlay tag search should find A's expense. Got titles: {titles}"
            )
            # A's own tag must still not match for B, even with an overlay present.
            titles_alice_tag = _api_titles(ctx["b"], "TagCatSrch tag=AliceTagCatSrchTag")
            assert "TagCatSrch AliceExpense" not in titles_alice_tag, (
                f"A's tag must not leak to B even once B has an overlay. Got titles: {titles_alice_tag}"
            )
        finally:
            _shell(
                f"from budget.models import ExpenseDataOverlay, Tag, Expense; "
                f"from feusers.models import FeUser; "
                f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
                f"e = Expense.objects.get(uid={ctx['exp_id']}); "
                f"ExpenseDataOverlay.objects.filter(expense=e, feuser=b).delete(); "
                f"Tag.objects.filter(owning_feuser=b, title='BobTagCatSrchOverlayTag').delete()"
            )
