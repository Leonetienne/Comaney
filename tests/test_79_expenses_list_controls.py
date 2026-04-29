"""
Expense list controls: fuzzy search, select-all, visible total, bulk actions.
Requires expenses created here; all cleaned up at the end.
"""
from datetime import date

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select as SeleniumSelect

from conftest import _url, click, wait_text, api_post, api_get, api_delete, CLICK_PACE
import time


TODAY = date.today().isoformat()

TITLE_A = "BulkCtrl Alpha"
TITLE_B = "BulkCtrl Beta"
TITLE_C = "BulkCtrl Gamma Income"


def search_type(driver, value):
    """Set the search field value and dispatch the input event."""
    el = driver.find_element(By.ID, "exp-search")
    el.clear()
    if value:
        el.send_keys(value)
    driver.execute_script(
        "arguments[0].dispatchEvent(new Event('input', {bubbles:true}))", el
    )
    time.sleep(CLICK_PACE)


def search_clear(driver):
    search_type(driver, "")


def visible_cards(driver):
    cards = driver.find_elements(By.CSS_SELECTOR, "#exp-list .exp-card")
    return [c for c in cards if c.value_of_css_property("display") != "none"]


class TestExpensesListControls:

    # ── Setup ───────────────────────────────────────────────────────────────

    def test_79_00_create_test_expenses(self, driver, w, ctx):
        """Create three expenses via API: two expenses + one income, all unsettled."""
        a = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_A, "type": "expense", "value": "100.00",
            "date_due": TODAY, "settled": False,
        })
        assert a.status_code == 201, a.text
        ctx["bulk_uid_a"] = a.json()["id"]

        b = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_B, "type": "expense", "value": "200.00",
            "date_due": TODAY, "settled": False,
        })
        assert b.status_code == 201, b.text
        ctx["bulk_uid_b"] = b.json()["id"]

        c = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_C, "type": "income", "value": "300.00",
            "date_due": TODAY, "settled": False,
        })
        assert c.status_code == 201, c.text
        ctx["bulk_uid_c"] = c.json()["id"]

    # ── Fuzzy search ────────────────────────────────────────────────────────

    def test_79_10_search_filters_cards(self, driver, w, ctx):
        """Typing in the search box hides non-matching cards in real time."""
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)

        search_type(driver, "BulkCtrl Alpha")

        vis = visible_cards(driver)
        titles = [c.find_element(By.CSS_SELECTOR, ".exp-title").text for c in vis]
        assert any(TITLE_A in t for t in titles), "Alpha should be visible"
        assert not any(TITLE_B in t for t in titles), "Beta should be hidden"
        assert not any(TITLE_C in t for t in titles), "Gamma should be hidden"

    def test_79_11_clear_search_restores_all(self, driver, w, ctx):
        """Clearing the search input shows all cards again."""
        search_clear(driver)

        titles = [c.find_element(By.CSS_SELECTOR, ".exp-title").text for c in visible_cards(driver)]
        assert any(TITLE_A in t for t in titles)
        assert any(TITLE_B in t for t in titles)
        assert any(TITLE_C in t for t in titles)

    # ── Select all / Deselect all ───────────────────────────────────────────

    def test_79_20_select_all_checks_all_visible(self, driver, w, ctx):
        """Select all checks every visible card's checkbox."""
        click(w, By.ID, "exp-select-all")

        vis = visible_cards(driver)
        assert vis, "Expected visible cards"
        for card in vis:
            assert card.find_element(By.CSS_SELECTOR, ".exp-checkbox").is_selected()

        assert driver.find_element(By.ID, "exp-select-all").text.strip().lower() == "deselect all"

    def test_79_21_deselect_all_unchecks_all(self, driver, w, ctx):
        """Clicking again unchecks all."""
        click(w, By.ID, "exp-select-all")

        for card in visible_cards(driver):
            assert not card.find_element(By.CSS_SELECTOR, ".exp-checkbox").is_selected()

        assert driver.find_element(By.ID, "exp-select-all").text.strip().lower() == "select all"

    def test_79_22_select_all_scoped_to_search(self, driver, w, ctx):
        """Select all only checks cards that are visible under the active search."""
        search_type(driver, "BulkCtrl Alpha")
        click(w, By.ID, "exp-select-all")

        for card in driver.find_elements(By.CSS_SELECTOR, "#exp-list .exp-card"):
            cb = card.find_element(By.CSS_SELECTOR, ".exp-checkbox")
            title = card.find_element(By.CSS_SELECTOR, ".exp-title").text
            if TITLE_A in title:
                assert cb.is_selected(), "Alpha should be checked"
            elif card.value_of_css_property("display") != "none":
                assert not cb.is_selected(), "Visible non-matching cards should not be checked"

        search_clear(driver)
        click(w, By.ID, "exp-select-all")  # deselect all

    # ── Visible total ───────────────────────────────────────────────────────

    def test_79_30_visible_total_income_minus_expenses(self, driver, w, ctx):
        """Visible total = income 300 - expense 100 - expense 200 = 0."""
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        search_type(driver, "BulkCtrl")

        raw = driver.find_element(By.ID, "exp-sum-value").text.strip()
        assert raw != "–", "Sum should be calculated"
        assert abs(float(raw)) < 0.01, f"Expected 0.00, got {raw}"

    def test_79_31_visible_total_updates_on_search(self, driver, w, ctx):
        """Filtering to one expense card updates the total accordingly."""
        search_type(driver, "BulkCtrl Alpha")
        raw = driver.find_element(By.ID, "exp-sum-value").text.strip()
        assert abs(float(raw) - (-100.0)) < 0.01, f"Expected -100.00, got {raw}"
        search_clear(driver)

    # ── Bulk actions ────────────────────────────────────────────────────────

    def _select_our_cards(self, driver, w):
        search_type(driver, "BulkCtrl")
        click(w, By.ID, "exp-select-all")

    def _bulk_action_and_wait(self, driver, w, action_value):
        """Select action, click Go, confirm dialog, wait for page reload."""
        anchor = driver.find_element(By.ID, "exp-list")
        SeleniumSelect(driver.find_element(By.ID, "exp-bulk-action")).select_by_value(action_value)
        driver.find_element(By.CSS_SELECTOR, "#exp-bulk-form button[type=submit]").click()
        time.sleep(CLICK_PACE)
        w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok"))).click()
        # Wait for the page to actually navigate (form POST + redirect)
        w.until(EC.staleness_of(anchor))
        wait_text(driver, w, "Expenses")

    def test_79_40_bulk_settle(self, driver, w, ctx):
        """Bulk settle marks all selected expenses as settled."""
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        self._select_our_cards(driver, w)
        self._bulk_action_and_wait(driver, w, "settle")

        for key in ("bulk_uid_a", "bulk_uid_b", "bulk_uid_c"):
            assert api_get(f"/api/v1/expenses/{ctx[key]}/", ctx).json()["settled"] is True

    def test_79_41_bulk_unsettle(self, driver, w, ctx):
        """Bulk unsettle reverses the previous settle."""
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        self._select_our_cards(driver, w)
        self._bulk_action_and_wait(driver, w, "unsettle")

        for key in ("bulk_uid_a", "bulk_uid_b", "bulk_uid_c"):
            assert api_get(f"/api/v1/expenses/{ctx[key]}/", ctx).json()["settled"] is False

    def test_79_42_bulk_delete_with_confirmation(self, driver, w, ctx):
        """Bulk delete shows confirmation dialog and removes the expenses on confirm."""
        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        self._select_our_cards(driver, w)

        anchor = driver.find_element(By.ID, "exp-list")
        SeleniumSelect(driver.find_element(By.ID, "exp-bulk-action")).select_by_value("delete")
        driver.find_element(By.CSS_SELECTOR, "#exp-bulk-form button[type=submit]").click()
        time.sleep(CLICK_PACE)

        ok = w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok")))
        assert "delete" in ok.text.strip().lower()
        ok.click()
        w.until(EC.staleness_of(anchor))

        w.until(lambda d: TITLE_A not in d.page_source)
        assert TITLE_B not in driver.page_source
        assert TITLE_C not in driver.page_source

        for key in ("bulk_uid_a", "bulk_uid_b", "bulk_uid_c"):
            ctx.pop(key, None)

    def test_79_42b_bulk_action_only_affects_filtered_items(self, driver, w, ctx):
        """Filtering to a subset and doing bulk settle must NOT touch unfiltered expenses.
        This guards against the fatal bug: filter + select all + action = acts on everything.
        """
        # Re-create all three (42 deleted them)
        a = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_A, "type": "expense", "value": "100.00",
            "date_due": TODAY, "settled": False,
        })
        assert a.status_code == 201
        ctx["bulk_uid_a"] = a.json()["id"]

        b = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_B, "type": "expense", "value": "200.00",
            "date_due": TODAY, "settled": False,
        })
        assert b.status_code == 201
        ctx["bulk_uid_b"] = b.json()["id"]

        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)

        # Filter to Alpha only, select all, settle
        search_type(driver, TITLE_A)
        click(w, By.ID, "exp-select-all")
        self._bulk_action_and_wait(driver, w, "settle")

        # Alpha must be settled, Beta must still be unsettled
        assert api_get(f"/api/v1/expenses/{ctx['bulk_uid_a']}/", ctx).json()["settled"] is True
        assert api_get(f"/api/v1/expenses/{ctx['bulk_uid_b']}/", ctx).json()["settled"] is False

        # Cleanup
        api_delete(f"/api/v1/expenses/{ctx.pop('bulk_uid_a')}/", ctx)
        api_delete(f"/api/v1/expenses/{ctx.pop('bulk_uid_b')}/", ctx)

    def test_79_43_bulk_delete_cancel_keeps_expenses(self, driver, w, ctx):
        """Cancelling the confirmation dialog leaves expenses untouched."""
        e = api_post("/api/v1/expenses/", ctx, json={
            "title": TITLE_A, "type": "expense", "value": "100.00",
            "date_due": TODAY, "settled": False,
        })
        assert e.status_code == 201
        ctx["bulk_uid_cancel"] = e.json()["id"]

        driver.get(_url("/budget/expenses/"))
        wait_text(driver, w, TITLE_A)
        search_type(driver, TITLE_A)
        click(w, By.ID, "exp-select-all")

        SeleniumSelect(driver.find_element(By.ID, "exp-bulk-action")).select_by_value("delete")
        driver.find_element(By.CSS_SELECTOR, "#exp-bulk-form button[type=submit]").click()
        time.sleep(CLICK_PACE)
        w.until(EC.element_to_be_clickable((By.ID, "cdialog-cancel"))).click()
        time.sleep(CLICK_PACE)

        assert TITLE_A in driver.page_source

    # ── Cleanup ─────────────────────────────────────────────────────────────

    def test_79_99_cleanup(self, driver, w, ctx):
        for key in ("bulk_uid_a", "bulk_uid_b", "bulk_uid_c", "bulk_uid_cancel"):
            if key in ctx:
                api_delete(f"/api/v1/expenses/{ctx.pop(key)}/", ctx)
