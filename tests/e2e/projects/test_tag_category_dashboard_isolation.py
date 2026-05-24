"""
Tag and category isolation on the dashboard bar/pie chart across project members.

Scenario: User A and User B are both members of a project. A creates an expense
with A's own tag "AliceIsoTag" and A's own category "AliceIsoCat", with B as a
50% participant. B then views their shared-mode dashboard.

Expected (correct) behaviour:
  - B's tag chart must NOT list "AliceIsoTag" (owned by A)
  - B's category chart must NOT list "AliceIsoCat" (owned by A)

Fix location: _compute_chart() in budget/dashboard_cards.py now splits the
queryset into own expenses (use direct tags/category) and foreign expenses
(use the viewer's ExpenseDataOverlay, or 'Uncategorized' if none exists).

Run with: venv/bin/pytest tests/e2e/buddies/test_tag_category_dashboard_isolation.py -v
"""
import time

import pytest
import requests

from helpers import (
    _url, server_today, setup_user, cleanup_user, session_cookies, BASE_URL,
)
from bhelpers import _shell, _login_as, _create_group, _add_group_member


CARDS_URL = BASE_URL + "/budget/dashboard/cards/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _csrf(sess: requests.Session) -> str:
    return next((c.value for c in sess.cookies if c.name == "csrftoken"), "")


def _post_card(sess, csrf, yaml_str) -> requests.Response:
    return sess.post(
        CARDS_URL,
        json={"yaml_config": yaml_str},
        headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
    )


def _delete_card(sess, csrf, card_id):
    sess.delete(f"{CARDS_URL}{card_id}/", headers={"X-CSRFToken": csrf})


def _chart_labels(sess, card_id, year, month, sharing="shared"):
    r = sess.get(CARDS_URL, params={"year": year, "month": month, "sharing": sharing})
    assert r.status_code == 200, f"cards API returned {r.status_code}: {r.text}"
    cards = r.json().get("cards", [])
    card = next((c for c in cards if c["id"] == card_id), None)
    if card is None:
        return []
    return card["data"].get("labels", [])


def _create_expense_with_tag_and_category(
    owner_email: str, group_id: int, participant_email: str,
    tag_title: str, cat_title: str,
    value: str = "80.00", share: str = "50.0",
) -> str:
    """Create a project expense owned by owner with a tag and category both
    owned by owner. participant is added as a BuddySpending participant."""
    return _shell(
        f"import datetime; "
        f"from budget.models import Expense, Tag, Category; "
        f"from buddies.models import Project, BuddySpending; "
        f"from feusers.models import FeUser; from decimal import Decimal; "
        f"a = FeUser.objects.get(email='{owner_email}'); "
        f"b = FeUser.objects.get(email='{participant_email}'); "
        f"g = Project.objects.get(pk={group_id}); "
        f"tag, _ = Tag.objects.get_or_create(owning_feuser=a, title='{tag_title}'); "
        f"cat, _ = Category.objects.get_or_create(owning_feuser=a, title='{cat_title}'); "
        f"e = Expense.objects.create(owning_feuser=a, title='AliceProjectExpense', "
        f"  type='expense', value=Decimal('{value}'), settled=False, "
        f"  buddy_approved=True, project=g, category=cat, "
        f"  date_due=datetime.date.today()); "
        f"e.tags.add(tag); "
        f"BuddySpending.objects.create(expense=e, participant_feuser=b, "
        f"  share_percent=Decimal('{share}')); "
        f"print(e.pk)"
    )


def _get_session(driver, user_ctx) -> requests.Session:
    _login_as(driver, user_ctx)
    time.sleep(1)
    driver.get(_url("/budget/"))
    time.sleep(1)
    s = requests.Session()
    s.cookies.update(session_cookies(driver))
    return s


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ctx(driver, w):
    a = setup_user(driver, w, first_name="Alice", last_name="IsoTest")
    b = setup_user(None, None, first_name="Bob", last_name="IsoTest")

    gid = int(_create_group(a["email"], "TagCatIsoProject"))
    _add_group_member(gid, b["email"])

    _create_expense_with_tag_and_category(
        owner_email=a["email"],
        group_id=gid,
        participant_email=b["email"],
        tag_title="AliceIsoTag",
        cat_title="AliceIsoCat",
    )

    yield {"a": a, "b": b, "gid": gid}

    cleanup_user(a["email"])
    cleanup_user(b["email"])


@pytest.fixture(scope="module")
def sess_a(driver, ctx):
    return _get_session(driver, ctx["a"])


@pytest.fixture(scope="module")
def sess_b(driver, ctx, sess_a):
    # sess_a must be set up first so its cookies are captured while A is
    # logged in; then we switch the browser to B.
    return _get_session(driver, ctx["b"])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTagCategoryDashboardIsolation:

    def test_b_tag_bar_chart_excludes_alice_tag(self, driver, w, ctx, sess_b):
        """B's tag bar chart in shared mode must not list tags owned by A.

        Foreign expenses use the viewer's ExpenseDataOverlay for tags; when
        no overlay exists the expense contributes nothing to the tag chart.
        """
        today = server_today()
        year, month = today[:4], today[5:7]
        csrf = _csrf(sess_b)

        r = _post_card(sess_b, csrf,
            "type: bar-chart\ntitle: IsoTagBarB\n"
            "method: sum\ngroup: tags\n"
            "positioning:\n  position: 90\n  width: 4\n  height: 2\n"
        )
        assert r.status_code == 201, r.text
        card_id = r.json()["card"]["id"]

        labels = _chart_labels(sess_b, card_id, year, month, sharing="shared")
        _delete_card(sess_b, csrf, card_id)

        assert "AliceIsoTag" not in labels, (
            f"B's tag bar chart leaked A's tag 'AliceIsoTag'. Got labels: {labels}"
        )

    def test_b_tag_pie_chart_excludes_alice_tag(self, driver, w, ctx, sess_b):
        """B's tag pie chart in shared mode must not list tags owned by A."""
        today = server_today()
        year, month = today[:4], today[5:7]
        csrf = _csrf(sess_b)

        r = _post_card(sess_b, csrf,
            "type: pie-chart\ntitle: IsoTagPieB\n"
            "method: sum\ngroup: tags\n"
            "positioning:\n  position: 91\n  width: 4\n  height: 2\n"
        )
        assert r.status_code == 201, r.text
        card_id = r.json()["card"]["id"]

        labels = _chart_labels(sess_b, card_id, year, month, sharing="shared")
        _delete_card(sess_b, csrf, card_id)

        assert "AliceIsoTag" not in labels, (
            f"B's tag pie chart leaked A's tag 'AliceIsoTag'. Got labels: {labels}"
        )

    def test_b_category_bar_chart_excludes_alice_category(self, driver, w, ctx, sess_b):
        """B's category bar chart in shared mode must not list categories owned by A.

        Foreign expenses without an overlay show as 'Uncategorized', not with
        the expense owner's category name.
        """
        today = server_today()
        year, month = today[:4], today[5:7]
        csrf = _csrf(sess_b)

        r = _post_card(sess_b, csrf,
            "type: bar-chart\ntitle: IsoCatBarB\n"
            "method: sum\ngroup: categories\n"
            "positioning:\n  position: 92\n  width: 4\n  height: 2\n"
        )
        assert r.status_code == 201, r.text
        card_id = r.json()["card"]["id"]

        labels = _chart_labels(sess_b, card_id, year, month, sharing="shared")
        _delete_card(sess_b, csrf, card_id)

        assert "AliceIsoCat" not in labels, (
            f"B's category bar chart leaked A's category 'AliceIsoCat'. Got labels: {labels}"
        )

    def test_b_category_pie_chart_excludes_alice_category(self, driver, w, ctx, sess_b):
        """B's category pie chart in shared mode must not list categories owned by A."""
        today = server_today()
        year, month = today[:4], today[5:7]
        csrf = _csrf(sess_b)

        r = _post_card(sess_b, csrf,
            "type: pie-chart\ntitle: IsoCatPieB\n"
            "method: sum\ngroup: categories\n"
            "positioning:\n  position: 93\n  width: 4\n  height: 2\n"
        )
        assert r.status_code == 201, r.text
        card_id = r.json()["card"]["id"]

        labels = _chart_labels(sess_b, card_id, year, month, sharing="shared")
        _delete_card(sess_b, csrf, card_id)

        assert "AliceIsoCat" not in labels, (
            f"B's category pie chart leaked A's category 'AliceIsoCat'. Got labels: {labels}"
        )

    def test_a_tag_bar_chart_shows_own_tag(self, driver, w, ctx, sess_a):
        """Sanity check: A's own tag bar chart in shared mode DOES show AliceIsoTag.

        This test should pass both before and after the bug fix, confirming
        that the fix does not remove an owner's own tags from their chart.
        """
        today = server_today()
        year, month = today[:4], today[5:7]
        csrf = _csrf(sess_a)

        r = _post_card(sess_a, csrf,
            "type: bar-chart\ntitle: IsoTagBarA\n"
            "method: sum\ngroup: tags\n"
            "positioning:\n  position: 94\n  width: 4\n  height: 2\n"
        )
        assert r.status_code == 201, r.text
        card_id = r.json()["card"]["id"]

        labels = _chart_labels(sess_a, card_id, year, month, sharing="shared")
        _delete_card(sess_a, csrf, card_id)

        assert "AliceIsoTag" in labels, (
            f"A's own tag 'AliceIsoTag' should appear in A's chart. Got labels: {labels}"
        )

    def test_a_category_bar_chart_shows_own_category(self, driver, w, ctx, sess_a):
        """Sanity check: A's own category bar chart in shared mode DOES show AliceIsoCat."""
        today = server_today()
        year, month = today[:4], today[5:7]
        csrf = _csrf(sess_a)

        r = _post_card(sess_a, csrf,
            "type: bar-chart\ntitle: IsoCatBarA\n"
            "method: sum\ngroup: categories\n"
            "positioning:\n  position: 95\n  width: 4\n  height: 2\n"
        )
        assert r.status_code == 201, r.text
        card_id = r.json()["card"]["id"]

        labels = _chart_labels(sess_a, card_id, year, month, sharing="shared")
        _delete_card(sess_a, csrf, card_id)

        assert "AliceIsoCat" in labels, (
            f"A's own category 'AliceIsoCat' should appear in A's chart. Got labels: {labels}"
        )

    # ------------------------------------------------------------------
    # Positive overlay: B's overlay tags/categories appear in B's chart
    # ------------------------------------------------------------------

    def test_b_overlay_tag_appears_in_chart(self, driver, w, ctx, sess_b):
        """When B sets an overlay tag on A's expense, that tag appears in B's chart."""
        today = server_today()
        year, month = today[:4], today[5:7]

        # Create B's own tag and attach it as an overlay to A's expense
        _shell(
            f"import datetime; "
            f"from budget.services import upsert_overlay; "
            f"from budget.models import Tag, Expense; "
            f"from feusers.models import FeUser; "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"e = Expense.objects.filter(owning_feuser__email='{ctx['a']['email']}', "
            f"  title='AliceProjectExpense').first(); "
            f"tag, _ = Tag.objects.get_or_create(owning_feuser=b, title='BobOverlayTag'); "
            f"upsert_overlay(e, b, None, [tag])"
        )

        csrf = _csrf(sess_b)
        r = _post_card(sess_b, csrf,
            "type: bar-chart\ntitle: IsoOverlayTagBar\n"
            "method: sum\ngroup: tags\n"
            "positioning:\n  position: 96\n  width: 4\n  height: 2\n"
        )
        assert r.status_code == 201, r.text
        card_id = r.json()["card"]["id"]

        labels = _chart_labels(sess_b, card_id, year, month, sharing="shared")
        _delete_card(sess_b, csrf, card_id)

        # Clean up overlay and tag
        _shell(
            f"from budget.models import ExpenseDataOverlay, Tag, Expense; "
            f"from feusers.models import FeUser; "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"e = Expense.objects.filter(owning_feuser__email='{ctx['a']['email']}', "
            f"  title='AliceProjectExpense').first(); "
            f"ExpenseDataOverlay.objects.filter(expense=e, feuser=b).delete(); "
            f"Tag.objects.filter(owning_feuser=b, title='BobOverlayTag').delete()"
        )

        assert "BobOverlayTag" in labels, (
            f"B's overlay tag 'BobOverlayTag' should appear in B's chart. Got labels: {labels}"
        )
        assert "AliceIsoTag" not in labels, (
            f"A's original tag must not appear even when B has an overlay. Got labels: {labels}"
        )

    def test_b_overlay_category_appears_in_chart(self, driver, w, ctx, sess_b):
        """When B sets an overlay category on A's expense, that category appears in B's chart."""
        today = server_today()
        year, month = today[:4], today[5:7]

        _shell(
            f"from budget.services import upsert_overlay; "
            f"from budget.models import Category, Expense; "
            f"from feusers.models import FeUser; "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"e = Expense.objects.filter(owning_feuser__email='{ctx['a']['email']}', "
            f"  title='AliceProjectExpense').first(); "
            f"cat, _ = Category.objects.get_or_create(owning_feuser=b, title='BobOverlayCat'); "
            f"upsert_overlay(e, b, cat, [])"
        )

        csrf = _csrf(sess_b)
        r = _post_card(sess_b, csrf,
            "type: bar-chart\ntitle: IsoOverlayCatBar\n"
            "method: sum\ngroup: categories\n"
            "positioning:\n  position: 97\n  width: 4\n  height: 2\n"
        )
        assert r.status_code == 201, r.text
        card_id = r.json()["card"]["id"]

        labels = _chart_labels(sess_b, card_id, year, month, sharing="shared")
        _delete_card(sess_b, csrf, card_id)

        # Clean up
        _shell(
            f"from budget.models import ExpenseDataOverlay, Category, Expense; "
            f"from feusers.models import FeUser; "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"e = Expense.objects.filter(owning_feuser__email='{ctx['a']['email']}', "
            f"  title='AliceProjectExpense').first(); "
            f"ExpenseDataOverlay.objects.filter(expense=e, feuser=b).delete(); "
            f"Category.objects.filter(owning_feuser=b, title='BobOverlayCat').delete()"
        )

        assert "BobOverlayCat" in labels, (
            f"B's overlay category 'BobOverlayCat' should appear in B's chart. Got labels: {labels}"
        )
        assert "AliceIsoCat" not in labels, (
            f"A's original category must not appear even when B has an overlay. Got labels: {labels}"
        )

    # ------------------------------------------------------------------
    # Explicit Uncategorized assertion
    # ------------------------------------------------------------------

    def test_b_category_chart_shows_uncategorized_for_no_overlay(self, driver, w, ctx, sess_b):
        """Foreign expenses with no overlay appear as 'Uncategorized' in B's category chart,
        not under the expense owner's category name."""
        today = server_today()
        year, month = today[:4], today[5:7]
        csrf = _csrf(sess_b)

        r = _post_card(sess_b, csrf,
            "type: bar-chart\ntitle: IsoUncatBar\n"
            "method: sum\ngroup: categories\n"
            "positioning:\n  position: 98\n  width: 4\n  height: 2\n"
        )
        assert r.status_code == 201, r.text
        card_id = r.json()["card"]["id"]

        labels = _chart_labels(sess_b, card_id, year, month, sharing="shared")
        _delete_card(sess_b, csrf, card_id)

        assert "Uncategorized" in labels, (
            f"Foreign expense with no overlay should show as 'Uncategorized'. Got labels: {labels}"
        )
        assert "AliceIsoCat" not in labels, (
            f"Owner's category must not leak. Got labels: {labels}"
        )

    # ------------------------------------------------------------------
    # B's own project expense — own tags still visible
    # ------------------------------------------------------------------

    def test_b_own_project_expense_tag_visible(self, driver, w, ctx, sess_b):
        """B's own tag on B's own project expense must appear in B's shared-mode chart."""
        today = server_today()
        year, month = today[:4], today[5:7]

        _shell(
            f"import datetime; "
            f"from budget.models import Expense, Tag; "
            f"from buddies.models import Project, BuddySpending; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"g = Project.objects.get(pk={ctx['gid']}); "
            f"tag, _ = Tag.objects.get_or_create(owning_feuser=b, title='BobOwnTag'); "
            f"e = Expense.objects.create(owning_feuser=b, title='BobProjectExpense', "
            f"  type='expense', value=Decimal('60.00'), settled=False, "
            f"  buddy_approved=True, project=g, date_due=datetime.date.today()); "
            f"e.tags.add(tag); "
            f"BuddySpending.objects.create(expense=e, "
            f"  participant_feuser=FeUser.objects.get(email='{ctx['a']['email']}'), "
            f"  share_percent=Decimal('50')); "
            f"print(e.pk)"
        )

        csrf = _csrf(sess_b)
        r = _post_card(sess_b, csrf,
            "type: bar-chart\ntitle: IsoBobOwnTagBar\n"
            "method: sum\ngroup: tags\n"
            "positioning:\n  position: 99\n  width: 4\n  height: 2\n"
        )
        assert r.status_code == 201, r.text
        card_id = r.json()["card"]["id"]

        labels = _chart_labels(sess_b, card_id, year, month, sharing="shared")
        _delete_card(sess_b, csrf, card_id)

        assert "BobOwnTag" in labels, (
            f"B's own tag 'BobOwnTag' on B's own expense must appear. Got labels: {labels}"
        )

    # ------------------------------------------------------------------
    # Same tag name, two users — no cross-user total merging
    # ------------------------------------------------------------------

    def test_same_tag_name_totals_not_merged(self, driver, w, ctx, sess_b):
        """If A and B both own a tag named 'SharedName', B's chart shows only B's
        total — A's expenses tagged 'SharedName' must not bleed into B's total."""
        today = server_today()
        year, month = today[:4], today[5:7]

        # Create A's expense with A's "SharedName" tag (B is participant, no overlay)
        _shell(
            f"import datetime; "
            f"from budget.models import Expense, Tag; "
            f"from buddies.models import Project, BuddySpending; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"g = Project.objects.get(pk={ctx['gid']}); "
            f"tag_a, _ = Tag.objects.get_or_create(owning_feuser=a, title='SharedName'); "
            f"e = Expense.objects.create(owning_feuser=a, title='ASharedNameExp', "
            f"  type='expense', value=Decimal('200.00'), settled=False, "
            f"  buddy_approved=True, project=g, date_due=datetime.date.today()); "
            f"e.tags.add(tag_a); "
            f"BuddySpending.objects.create(expense=e, participant_feuser=b, "
            f"  share_percent=Decimal('50'))"
        )
        # Create B's own expense with B's "SharedName" tag
        _shell(
            f"import datetime; "
            f"from budget.models import Expense, Tag; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"tag_b, _ = Tag.objects.get_or_create(owning_feuser=b, title='SharedName'); "
            f"e = Expense.objects.create(owning_feuser=b, title='BSharedNameExp', "
            f"  type='expense', value=Decimal('30.00'), settled=False, "
            f"  buddy_approved=True, date_due=datetime.date.today()); "
            f"e.tags.add(tag_b)"
        )

        csrf = _csrf(sess_b)
        r = _post_card(sess_b, csrf,
            "type: bar-chart\ntitle: IsoSharedNameBar\n"
            "method: sum\ngroup: tags\n"
            "positioning:\n  position: 100\n  width: 4\n  height: 2\n"
        )
        assert r.status_code == 201, r.text
        card_id = r.json()["card"]["id"]

        labels = _chart_labels(sess_b, card_id, year, month, sharing="shared")
        data = sess_b.get(CARDS_URL, params={"year": year, "month": month, "sharing": "shared"}).json()
        card_data = next((c["data"] for c in data.get("cards", []) if c["id"] == card_id), {})
        _delete_card(sess_b, csrf, card_id)

        idx = labels.index("SharedName") if "SharedName" in labels else None
        assert idx is not None, f"'SharedName' should appear in B's chart. Got labels: {labels}"

        shared_name_total = card_data.get("values", [])[idx]
        # B's own expense is 30; A's expense (200) must not inflate this to 230 or 100
        assert shared_name_total == pytest.approx(30.0), (
            f"'SharedName' total should be 30 (B's own expense only), "
            f"got {shared_name_total}. A's 200 must not bleed in."
        )
