"""
Expense list controls: live search, select-all/deselect, visible total,
and bulk settle/unsettle/delete/add-tag/remove-tag/set-category actions.
"""
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select as SeleniumSelect
from selenium.webdriver.support.ui import WebDriverWait

import subprocess

from helpers import (
    _url, click, wait_text, server_today,
    api_get, api_post, api_patch, api_delete, CLICK_PACE,
    setup_user, cleanup_user, DOCKER_WEB,
)


def _shell(code: str) -> str:
    r = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c", code],
        capture_output=True, text=True, timeout=20,
    )
    assert r.returncode == 0, f"Shell failed:\n{r.stderr}"
    return r.stdout.strip()


def _login_as(driver, ctx_user: dict) -> None:
    driver.delete_all_cookies()
    driver.execute_script("sessionStorage.clear(); localStorage.clear();")
    driver.get(_url("/login/"))
    time.sleep(1)
    email_el = driver.find_element(By.ID, "id_email")
    driver.execute_script("arguments[0].value = arguments[1];", email_el, ctx_user["email"])
    pass_el = driver.find_element(By.ID, "id_password")
    driver.execute_script("arguments[0].value = arguments[1];", pass_el, ctx_user["password"])
    driver.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
    time.sleep(2)

# Titles scoped with a prefix so they are easy to isolate via the search box.
PREFIX   = "BulkTest"
TITLE_A  = f"{PREFIX} Alpha"
TITLE_B  = f"{PREFIX} Beta"
TITLE_C  = f"{PREFIX} Gamma Income"


def _wait_search_idle(driver, timeout=4.0):
    WebDriverWait(driver, timeout).until(
        lambda d: (
            not d.find_element(By.ID, "exp-list").get_attribute("data-search-pending") and
            not d.find_element(By.ID, "exp-list").get_attribute("data-search-loading")
        )
    )


def search_type(driver, value):
    el = driver.find_element(By.ID, "exp-search")
    driver.execute_script(
        "arguments[0].value = arguments[1];"
        "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));",
        el, value,
    )
    _wait_search_idle(driver)
    time.sleep(1)


def search_clear(driver):
    search_type(driver, "")


def visible_cards(driver):
    return [c for c in driver.find_elements(By.CSS_SELECTOR, "#exp-list .exp-card")
            if c.value_of_css_property("display") != "none"]


def visible_titles(driver):
    return [c.find_element(By.CSS_SELECTOR, ".exp-title").text for c in visible_cards(driver)]


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestBulkSetup:

    def test_create_expenses(self, driver, w, ctx):
        today = server_today()
        a = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_A, "type": "expense", "value": "100.00",
            "date_due": today, "settled": False,
        })
        b = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_B, "type": "expense", "value": "200.00",
            "date_due": today, "settled": False,
        })
        c_exp = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_C, "type": "income", "value": "300.00",
            "date_due": today, "settled": False,
        })
        assert a.status_code == 201
        assert b.status_code == 201
        assert c_exp.status_code == 201
        ctx["uid_a"] = a.json()["id"]
        ctx["uid_b"] = b.json()["id"]
        ctx["uid_c"] = c_exp.json()["id"]


class TestSearch:

    def test_filters_cards(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        search_type(driver, TITLE_A)
        titles = visible_titles(driver)
        assert any(TITLE_A in t for t in titles)
        assert not any(TITLE_B in t for t in titles)
        assert not any(TITLE_C in t for t in titles)

    def test_clear_restores_all(self, driver, w, ctx):
        search_clear(driver)
        titles = visible_titles(driver)
        assert any(TITLE_A in t for t in titles)
        assert any(TITLE_B in t for t in titles)
        assert any(TITLE_C in t for t in titles)


class TestSelectAll:

    def test_select_all_checks_visible(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        search_type(driver, PREFIX)
        click(w, By.ID, "exp-select-all")
        for card in visible_cards(driver):
            assert card.find_element(By.CSS_SELECTOR, ".exp-checkbox").is_selected()
        assert driver.find_element(By.ID, "exp-select-all").text.strip().lower() == "deselect all"

    def test_deselect_all(self, driver, w, ctx):
        click(w, By.ID, "exp-select-all")
        for card in visible_cards(driver):
            assert not card.find_element(By.CSS_SELECTOR, ".exp-checkbox").is_selected()
        search_clear(driver)

    def test_scoped_to_search(self, driver, w, ctx):
        """Select all only checks the cards visible under the active search filter."""
        search_type(driver, TITLE_A)
        click(w, By.ID, "exp-select-all")
        for card in driver.find_elements(By.CSS_SELECTOR, "#exp-list .exp-card"):
            cb    = card.find_element(By.CSS_SELECTOR, ".exp-checkbox")
            title = card.find_element(By.CSS_SELECTOR, ".exp-title").text
            if TITLE_A in title:
                assert cb.is_selected()
            elif card.value_of_css_property("display") != "none":
                assert not cb.is_selected()
        search_clear(driver)
        click(w, By.ID, "exp-select-all")  # deselect


class TestVisibleTotal:

    def test_total_income_minus_expenses(self, driver, w, ctx):
        """Visible total: income 300 - expense 100 - expense 200 = 0."""
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        search_type(driver, PREFIX)
        raw = driver.find_element(By.ID, "exp-sum-value").text.strip()
        assert raw != "-", "Sum should be calculated"
        assert abs(float(raw)) < 0.01, f"Expected 0.00, got {raw}"

    def test_total_updates_on_search(self, driver, w, ctx):
        search_type(driver, TITLE_A)
        raw = driver.find_element(By.ID, "exp-sum-value").text.strip()
        assert abs(float(raw) - (-100.0)) < 0.01, f"Expected -100.00, got {raw}"
        search_clear(driver)


def _select_prefix(driver, w):
    search_type(driver, PREFIX)
    click(w, By.ID, "exp-select-all")


def _bulk_action(driver, w, action_value, secondary_id=None, secondary_value=None):
    SeleniumSelect(driver.find_element(By.ID, "exp-bulk-action")).select_by_value(action_value)
    if secondary_id and secondary_value is not None:
        time.sleep(0.3)
        SeleniumSelect(driver.find_element(By.ID, secondary_id)).select_by_value(str(secondary_value))
    driver.find_element(By.ID, "exp-bulk-go").click()
    time.sleep(CLICK_PACE)
    w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok"))).click()
    time.sleep(CLICK_PACE)
    w.until(lambda d: d.execute_script("return document.readyState") == "complete")
    wait_text(driver, w, "Expenses")


class TestBulkActions:

    def test_bulk_settle(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        _select_prefix(driver, w)
        _bulk_action(driver, w, "settle")
        for key in ("uid_a", "uid_b", "uid_c"):
            assert api_get(f"/api/v1/expenses/{ctx[key]}/", ctx).json()["settled"] is True

    def test_bulk_unsettle(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        _select_prefix(driver, w)
        _bulk_action(driver, w, "unsettle")
        for key in ("uid_a", "uid_b", "uid_c"):
            assert api_get(f"/api/v1/expenses/{ctx[key]}/", ctx).json()["settled"] is False

    def test_bulk_action_scoped_to_filter(self, driver, w, ctx):
        """Settling only Alpha via filtered bulk action must not touch Beta."""
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        search_type(driver, TITLE_A)
        click(w, By.ID, "exp-select-all")
        _bulk_action(driver, w, "settle")
        assert api_get(f"/api/v1/expenses/{ctx['uid_a']}/", ctx).json()["settled"] is True
        assert api_get(f"/api/v1/expenses/{ctx['uid_b']}/", ctx).json()["settled"] is False
        # restore
        driver.get(_url("/budget/expenses/"))
        _select_prefix(driver, w)
        _bulk_action(driver, w, "unsettle")

    def test_bulk_delete_cancel_keeps_expenses(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        search_type(driver, PREFIX)
        click(w, By.ID, "exp-select-all")
        SeleniumSelect(driver.find_element(By.ID, "exp-bulk-action")).select_by_value("delete")
        driver.find_element(By.ID, "exp-bulk-go").click()
        time.sleep(CLICK_PACE)
        w.until(EC.element_to_be_clickable((By.ID, "cdialog-cancel"))).click()
        time.sleep(CLICK_PACE)
        assert TITLE_A in driver.page_source

    def test_bulk_delete(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        anchor = driver.find_element(By.ID, "exp-list")
        _select_prefix(driver, w)
        SeleniumSelect(driver.find_element(By.ID, "exp-bulk-action")).select_by_value("delete")
        driver.find_element(By.ID, "exp-bulk-go").click()
        time.sleep(CLICK_PACE)
        w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok"))).click()
        w.until(EC.staleness_of(anchor))
        w.until(lambda d: TITLE_A not in d.page_source)
        for key in ("uid_a", "uid_b", "uid_c"):
            ctx.pop(key, None)


TAG_TITLE = f"{PREFIX}_tag_bulk"
CAT_TITLE = f"{PREFIX}_cat_bulk"


class TestBulkTagCategory:

    @pytest.fixture(autouse=True)
    def setup_expenses(self, driver, w, ctx):
        today = server_today()
        a = api_post("/api/v1/expenses/", ctx, json={
            "title": f"{PREFIX} TagCat Alpha", "type": "expense", "value": "10.00",
            "date_due": today, "settled": False,
        })
        b = api_post("/api/v1/expenses/", ctx, json={
            "title": f"{PREFIX} TagCat Beta", "type": "expense", "value": "20.00",
            "date_due": today, "settled": False,
        })
        assert a.status_code == 201
        assert b.status_code == 201
        ctx["tc_uid_a"] = a.json()["id"]
        ctx["tc_uid_b"] = b.json()["id"]

        tag = api_post("/api/v1/tags/", ctx, json={"title": TAG_TITLE})
        assert tag.status_code == 201
        ctx["tag_id"] = tag.json()["id"]

        cat = api_post("/api/v1/categories/", ctx, json={"title": CAT_TITLE})
        assert cat.status_code == 201
        ctx["cat_id"] = cat.json()["id"]

        yield

        api_delete(f"/api/v1/expenses/{ctx['tc_uid_a']}/", ctx)
        api_delete(f"/api/v1/expenses/{ctx['tc_uid_b']}/", ctx)
        api_delete(f"/api/v1/tags/{ctx['tag_id']}/", ctx)
        api_delete(f"/api/v1/categories/{ctx['cat_id']}/", ctx)
        for key in ("tc_uid_a", "tc_uid_b", "tag_id", "cat_id"):
            ctx.pop(key, None)

    def _select_tc(self, driver, w):
        search_type(driver, f"{PREFIX} TagCat")
        click(w, By.ID, "exp-select-all")

    def test_bulk_add_tag(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, f"{PREFIX} TagCat Alpha")
        self._select_tc(driver, w)
        _bulk_action(driver, w, "add-tag", "exp-bulk-tag", str(ctx["tag_id"]))
        for key in ("tc_uid_a", "tc_uid_b"):
            tags = [t["title"] for t in api_get(f"/api/v1/expenses/{ctx[key]}/", ctx).json()["tags"]]
            assert TAG_TITLE in tags, f"Expected tag on expense {key}"

    def test_bulk_add_tag_idempotent(self, driver, w, ctx):
        """Adding the same tag twice must not duplicate it."""
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, f"{PREFIX} TagCat Alpha")
        self._select_tc(driver, w)
        _bulk_action(driver, w, "add-tag", "exp-bulk-tag", str(ctx["tag_id"]))
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, f"{PREFIX} TagCat Alpha")
        self._select_tc(driver, w)
        _bulk_action(driver, w, "add-tag", "exp-bulk-tag", str(ctx["tag_id"]))
        for key in ("tc_uid_a", "tc_uid_b"):
            tags = [t["title"] for t in api_get(f"/api/v1/expenses/{ctx[key]}/", ctx).json()["tags"]]
            assert tags.count(TAG_TITLE) == 1, f"Tag should appear exactly once on expense {key}"

    def test_bulk_remove_tag(self, driver, w, ctx):
        # First add the tag
        api_patch(f"/api/v1/expenses/{ctx['tc_uid_a']}/", ctx, json={"tags": [ctx["tag_id"]]})
        api_patch(f"/api/v1/expenses/{ctx['tc_uid_b']}/", ctx, json={"tags": [ctx["tag_id"]]})

        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, f"{PREFIX} TagCat Alpha")
        self._select_tc(driver, w)
        _bulk_action(driver, w, "remove-tag", "exp-bulk-tag", str(ctx["tag_id"]))
        for key in ("tc_uid_a", "tc_uid_b"):
            tags = [t["title"] for t in api_get(f"/api/v1/expenses/{ctx[key]}/", ctx).json()["tags"]]
            assert TAG_TITLE not in tags, f"Tag should be removed from expense {key}"

    def test_bulk_set_category(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, f"{PREFIX} TagCat Alpha")
        self._select_tc(driver, w)
        _bulk_action(driver, w, "set-category", "exp-bulk-category", str(ctx["cat_id"]))
        for key in ("tc_uid_a", "tc_uid_b"):
            cat = api_get(f"/api/v1/expenses/{ctx[key]}/", ctx).json()["category"]
            assert cat is not None, f"Category should be set on expense {key}"
            assert cat["title"] == CAT_TITLE

    def test_bulk_clear_category(self, driver, w, ctx):
        # First set category
        api_patch(f"/api/v1/expenses/{ctx['tc_uid_a']}/", ctx, json={"category": ctx["cat_id"]})
        api_patch(f"/api/v1/expenses/{ctx['tc_uid_b']}/", ctx, json={"category": ctx["cat_id"]})

        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, f"{PREFIX} TagCat Alpha")
        self._select_tc(driver, w)
        # Select "— No category —" (empty value)
        _bulk_action(driver, w, "set-category", "exp-bulk-category", "")
        for key in ("tc_uid_a", "tc_uid_b"):
            cat = api_get(f"/api/v1/expenses/{ctx[key]}/", ctx).json()["category"]
            assert cat is None, f"Category should be cleared on expense {key}"


# ---------------------------------------------------------------------------
# Pentest: A in shared mode acting on B's foreign expenses
# ---------------------------------------------------------------------------

PENTEST_PREFIX = "BulkPentest"
PENTEST_TAG    = f"{PENTEST_PREFIX}_tag"
PENTEST_CAT    = f"{PENTEST_PREFIX}_cat"


class TestBulkPentest:
    """
    A is in shared mode and selects B's (foreign) expense.

    delete / settle / unsettle  -> blocked; flash "could not be updated"
    add-tag / remove-tag        -> goes to A's overlay only; flash "personal view only"
    set-category                -> goes to A's overlay only; flash "personal view only"
    """

    @pytest.fixture(scope="class")
    def setup_users(self, driver, w):
        ctx_a = setup_user(driver, w, first_name="PentestA", last_name="Alpha")
        ctx_b = setup_user(None, None, first_name="PentestB", last_name="Beta")

        # Buddy link so shared mode shows B's expense to A
        _shell(
            f"from feusers.models import FeUser; from buddies.models import BuddyLink; "
            f"a = FeUser.objects.get(email='{ctx_a['email']}'); "
            f"b = FeUser.objects.get(email='{ctx_b['email']}'); "
            f"lo, hi = sorted([a, b], key=lambda u: u.pk); "
            f"BuddyLink.objects.get_or_create(user_a=lo, user_b=hi)"
        )

        # B creates the foreign expense
        r = api_post("/api/v1/expenses/", ctx_b, json={
            "title": f"{PENTEST_PREFIX} Foreign",
            "type": "expense", "value": "55.00",
            "date_due": server_today(), "settled": False,
        })
        assert r.status_code == 201
        foreign_pk = r.json()["id"]

        # Add A as a BuddySpending participant so the expense appears in A's shared view
        _shell(
            f"from budget.models import Expense; from buddies.models import BuddySpending; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"e = Expense.objects.get(pk={foreign_pk}); "
            f"a = FeUser.objects.get(email='{ctx_a['email']}'); "
            f"BuddySpending.objects.create(expense=e, participant_feuser=a, "
            f"share_percent=Decimal('50.0'))"
        )

        # A's tag and category (needed for overlay tests)
        tag_r = api_post("/api/v1/tags/",       ctx_a, json={"title": PENTEST_TAG})
        cat_r = api_post("/api/v1/categories/", ctx_a, json={"title": PENTEST_CAT})
        assert tag_r.status_code == 201
        assert cat_r.status_code == 201

        yield {
            "ctx_a": ctx_a, "ctx_b": ctx_b,
            "foreign_pk": foreign_pk,
            "tag_id": tag_r.json()["id"],
            "cat_id": cat_r.json()["id"],
        }

        api_delete(f"/api/v1/expenses/{foreign_pk}/", ctx_b)
        cleanup_user(ctx_a["email"])
        cleanup_user(ctx_b["email"])

    # --- per-test helpers ---

    def _login_a(self, driver, data):
        _login_as(driver, data["ctx_a"])

    def _load_shared(self, driver, w):
        driver.execute_script("localStorage.setItem('sharingMode', 'shared');")
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, "Expenses")

    def _select_foreign(self, driver, w):
        search_type(driver, PENTEST_PREFIX)
        click(w, By.ID, "exp-select-all")

    def _do_bulk(self, driver, w, action, secondary_id=None, secondary_value=None):
        SeleniumSelect(driver.find_element(By.ID, "exp-bulk-action")).select_by_value(action)
        if secondary_id and secondary_value is not None:
            time.sleep(0.3)
            SeleniumSelect(driver.find_element(By.ID, secondary_id)).select_by_value(
                str(secondary_value)
            )
        driver.find_element(By.ID, "exp-bulk-go").click()
        time.sleep(CLICK_PACE)
        w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok"))).click()
        time.sleep(CLICK_PACE)
        w.until(lambda d: d.execute_script("return document.readyState") == "complete")
        wait_text(driver, w, "Expenses")

    def _overlay_tags(self, foreign_pk, email):
        return _shell(
            f"from feusers.models import FeUser; from budget.models import ExpenseDataOverlay; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"ov = ExpenseDataOverlay.objects.filter(expense_id={foreign_pk}, feuser=u).first(); "
            f"print([t.title for t in ov.tags.all()] if ov else [])"
        )

    def _overlay_category(self, foreign_pk, email):
        return _shell(
            f"from feusers.models import FeUser; from budget.models import ExpenseDataOverlay; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"ov = ExpenseDataOverlay.objects.filter(expense_id={foreign_pk}, feuser=u).first(); "
            f"print(ov.category.title if (ov and ov.category) else None)"
        )

    # --- tests ---

    def test_delete_blocked(self, driver, w, setup_users):
        d = setup_users
        self._login_a(driver, d)
        self._load_shared(driver, w)
        self._select_foreign(driver, w)
        self._do_bulk(driver, w, "delete")
        assert api_get(f"/api/v1/expenses/{d['foreign_pk']}/", d["ctx_b"]).status_code == 200, \
            "B's expense must still exist after A's blocked delete"
        assert "could not be updated" in driver.page_source

    def test_settle_blocked(self, driver, w, setup_users):
        d = setup_users
        self._login_a(driver, d)
        self._load_shared(driver, w)
        self._select_foreign(driver, w)
        self._do_bulk(driver, w, "settle")
        exp = api_get(f"/api/v1/expenses/{d['foreign_pk']}/", d["ctx_b"]).json()
        assert exp["settled"] is False, "B's expense must remain unsettled"
        assert "could not be updated" in driver.page_source

    def test_unsettle_blocked(self, driver, w, setup_users):
        d = setup_users
        api_patch(f"/api/v1/expenses/{d['foreign_pk']}/", d["ctx_b"], json={"settled": True})
        self._login_a(driver, d)
        self._load_shared(driver, w)
        self._select_foreign(driver, w)
        self._do_bulk(driver, w, "unsettle")
        exp = api_get(f"/api/v1/expenses/{d['foreign_pk']}/", d["ctx_b"]).json()
        assert exp["settled"] is True, "B's expense must remain settled — A cannot unsettle it"
        assert "could not be updated" in driver.page_source
        api_patch(f"/api/v1/expenses/{d['foreign_pk']}/", d["ctx_b"], json={"settled": False})

    def test_add_tag_goes_to_overlay(self, driver, w, setup_users):
        d = setup_users
        self._login_a(driver, d)
        self._load_shared(driver, w)
        self._select_foreign(driver, w)
        self._do_bulk(driver, w, "add-tag", "exp-bulk-tag", str(d["tag_id"]))
        # B's expense itself has no tag
        assert api_get(f"/api/v1/expenses/{d['foreign_pk']}/", d["ctx_b"]).json()["tags"] == []
        # A's overlay has it
        assert PENTEST_TAG in self._overlay_tags(d["foreign_pk"], d["ctx_a"]["email"])
        assert "personal view only" in driver.page_source

    def test_remove_tag_goes_to_overlay(self, driver, w, setup_users):
        # Depends on test_add_tag_goes_to_overlay having run first (overlay already has the tag)
        d = setup_users
        self._login_a(driver, d)
        self._load_shared(driver, w)
        self._select_foreign(driver, w)
        self._do_bulk(driver, w, "remove-tag", "exp-bulk-tag", str(d["tag_id"]))
        assert api_get(f"/api/v1/expenses/{d['foreign_pk']}/", d["ctx_b"]).json()["tags"] == []
        assert PENTEST_TAG not in self._overlay_tags(d["foreign_pk"], d["ctx_a"]["email"])
        assert "personal view only" in driver.page_source

    def test_set_category_goes_to_overlay(self, driver, w, setup_users):
        d = setup_users
        self._login_a(driver, d)
        self._load_shared(driver, w)
        self._select_foreign(driver, w)
        self._do_bulk(driver, w, "set-category", "exp-bulk-category", str(d["cat_id"]))
        # B's expense itself has no category
        assert api_get(f"/api/v1/expenses/{d['foreign_pk']}/", d["ctx_b"]).json()["category"] is None
        # A's overlay has it
        assert PENTEST_CAT in self._overlay_category(d["foreign_pk"], d["ctx_a"]["email"])
        assert "personal view only" in driver.page_source
