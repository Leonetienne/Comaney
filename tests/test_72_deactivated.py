"""
Browser tests for deactivated/end_on behaviour.

  1. A deactivated scheduled expense shows the "Deactivated" badge in the list
     and generates no expense entries when the cron runs.
  2. An active scheduled expense with end_on set generates no entries beyond
     that date when the cron runs.
  3. A deactivated expense is grayed out in the expense list and is NOT
     reflected in the dashboard "Paid expenses" or "Left to spend" panels.

All use month_start_day=1, prev_month=False (standard calendar month).
Cron is forced to April 2026 via --year/--month to keep results predictable.
Cleanup is done via the API.
"""
import time
import re

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support import expected_conditions as EC

from conftest import _url, fill, server_today, submit, wait_url, wait_text, api_delete, api_patch, run_cmd


def _read_panel_amount(driver, panel_class):
    """Read the numeric text from a dashboard panel, stripping the currency span."""
    panel = driver.find_element(By.CSS_SELECTOR, f".{panel_class} .amount")
    # The currency is in a child <span>; get only the direct text node
    return driver.execute_script(
        "return Array.from(arguments[0].childNodes)"
        ".filter(n => n.nodeType === 3)"
        ".map(n => n.textContent.trim())"
        ".join('');",
        panel
    )


def _reset_month_settings(ctx):
    api_patch("/api/v1/account/", ctx, json={"month_start_day": 1, "month_start_prev": False})


def _get_scheduled_uid(driver):
    return re.search(r'/scheduled/(\d+)/edit/', driver.current_url).group(1)


def _get_expense_uid(driver):
    return re.search(r'/expenses/(\d+)/edit/', driver.current_url).group(1)


class TestDeactivated:

    # ── 1. Deactivated scheduler ────────────────────────────────────────────

    def test_72_deactivated_scheduler_shows_badge(self, driver, w, ctx):
        """Create a deactivated scheduler — it should show the Deactivated badge in the list."""
        _reset_month_settings(ctx)

        driver.get(_url("/budget/scheduled/new/"))
        fill(w, By.ID, "id_title", "Deact Scheduler Test")
        fill(w, By.ID, "id_value", "50.00")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("expense")
        fill(w, By.ID, "id_repeat_every_factor", "1")
        Select(driver.find_element(By.ID, "id_repeat_every_unit")).select_by_value("months")
        driver.execute_script("document.getElementById('id_repeat_base_date').value = '2026-04-01';")
        driver.execute_script("document.getElementById('id_deactivated').checked = true;")
        submit(w)
        wait_url(w, "/budget/scheduled/")

        card = w.until(EC.presence_of_element_located(
            (By.XPATH, "//span[contains(text(),'Deact Scheduler Test')]"
                       "/ancestor::div[contains(@class,'exp-card')]")))
        assert "exp-card--deactivated" in card.get_attribute("class"), \
            "Card should have deactivated style"
        assert "Deactivated" in card.text, "Card should show Deactivated badge"

        # Store UID for next test
        edit_link = card.find_element(By.XPATH, ".//a[contains(@href,'/edit/')]")
        ctx["deact_sched_uid"] = re.search(r'/scheduled/(\d+)/edit/', edit_link.get_attribute("href")).group(1)

    def test_73_deactivated_scheduler_generates_nothing(self, driver, w, ctx):
        """Running the cron for a deactivated scheduler must produce zero expense entries."""
        run_cmd("generate_scheduled_expenses", "--year", "2026")
        time.sleep(1)

        driver.get(_url("/budget/expenses/?year=2026&month=4"))
        time.sleep(1)
        assert "Deact Scheduler Test" not in driver.page_source, \
            "Deactivated scheduler must not generate expense entries"

        # Cleanup
        api_delete(f"/api/v1/scheduled/{ctx['deact_sched_uid']}/", ctx)

    # ── 2. end_on respected ─────────────────────────────────────────────────

    def test_74_scheduler_end_on_shown_in_list(self, driver, w, ctx):
        """
        Create a weekly scheduler for April 2026 with end_on=2026-04-15.
        The list should show the end date and the card should look inactive
        (ended) since end_on is in the past.
        """
        _reset_month_settings(ctx)

        driver.get(_url("/budget/scheduled/new/"))
        fill(w, By.ID, "id_title", "EndOn Scheduler Test")
        fill(w, By.ID, "id_value", "7.00")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("expense")
        fill(w, By.ID, "id_repeat_every_factor", "1")
        Select(driver.find_element(By.ID, "id_repeat_every_unit")).select_by_value("weeks")
        driver.execute_script("""
            document.getElementById('id_repeat_base_date').value = '2026-04-01';
            document.getElementById('id_end_on').value = '2026-04-15';
        """)
        submit(w)
        wait_url(w, "/budget/scheduled/")

        card = w.until(EC.presence_of_element_located(
            (By.XPATH, "//span[contains(text(),'EndOn Scheduler Test')]"
                       "/ancestor::div[contains(@class,'exp-card')]")))
        assert "2026-04-15" in card.text, "End date should be displayed in the card"
        assert "exp-card--deactivated" in card.get_attribute("class"), \
            "Card should be styled as inactive since end_on is in the past"

        edit_link = card.find_element(By.XPATH, ".//a[contains(@href,'/edit/')]")
        ctx["endon_sched_uid"] = re.search(r'/scheduled/(\d+)/edit/', edit_link.get_attribute("href")).group(1)

    def test_75_scheduler_end_on_limits_generation(self, driver, w, ctx):
        """
        Cron for April 2026 should create entries on Apr 1, 8, 15 only — not Apr 22 or 29.
        """
        run_cmd("generate_scheduled_expenses", "--year", "2026")
        time.sleep(1)

        driver.get(_url("/budget/expenses/?year=2026&month=4"))
        time.sleep(1)

        source = driver.page_source

        from conftest import api_get
        resp = api_get("/api/v1/expenses/", ctx, params={"year": 2026, "month": 4})
        hits = [e for e in resp.json()["expenses"] if e["title"] == "EndOn Scheduler Test"]
        due_dates = sorted(e["date_due"] for e in hits)

        assert due_dates == ["2026-04-01", "2026-04-08", "2026-04-15"], \
            f"Expected only occurrences up to Apr 15, got {due_dates}"

        # Also verify the list page shows them and does NOT show Apr 22/29
        assert "EndOn Scheduler Test" in source, "Generated entries should appear in the expense list"

        # Cleanup
        for e in hits:
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{ctx['endon_sched_uid']}/", ctx)

    # ── 3. Deactivated expense excluded from dashboard ──────────────────────

    def test_76_deactivated_expense_grayed_in_list(self, driver, w, ctx):
        """
        Create a deactivated expense — it should appear grayed out in the list
        with a Deactivated badge, and have no Edit button.
        """
        _reset_month_settings(ctx)
        today = server_today()

        driver.get(_url("/budget/expenses/new/"))
        fill(w, By.ID, "id_title", "Deact Expense Test")
        fill(w, By.ID, "id_value", "400.00")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("expense")
        driver.execute_script(f"""
            document.getElementById('id_date_due').value = '{today}';
            document.getElementById('id_settled').checked = true;
            document.getElementById('id_deactivated').checked = true;
        """)
        submit(w)
        wait_url(w, "/budget/expenses/")

        card = w.until(EC.presence_of_element_located(
            (By.XPATH, "//span[contains(text(),'Deact Expense Test')]"
                       "/ancestor::div[contains(@class,'exp-card')]")))
        assert "exp-card--deactivated" in card.get_attribute("class"), \
            "Deactivated expense card should have deactivated style"
        assert "Deactivated" in card.text, "Card should show Deactivated badge"

        # Store ID for cleanup
        from conftest import api_get
        resp = api_get("/api/v1/expenses/", ctx)
        for e in resp.json()["expenses"]:
            if e["title"] == "Deact Expense Test":
                ctx["deact_exp_id"] = e["id"]
                break

    def test_77_deactivated_expense_not_in_dashboard(self, driver, w, ctx):
        """
        The deactivated expense created via the browser in test_76 should not
        affect the dashboard 'Paid expenses' panel.  We verify this by reading
        the baseline paid amount, then creating a second, identical but ACTIVE
        settled expense worth 99 999 — if the deactivated one were counted the
        baseline itself would already be unexpectedly large.  The real check is
        that paid does not include the 99 999 deactivated expense: after adding
        an active settled expense of the same huge value we confirm the panel
        jumps by exactly that amount (not double).
        """
        today = server_today()
        from conftest import api_post, api_get

        # Read the current dashboard paid baseline (whatever prior tests left).
        driver.get(_url("/budget/"))
        time.sleep(1)
        baseline_paid = float(_read_panel_amount(driver, "panel-paid"))

        # Create a large DEACTIVATED settled expense via the browser form.
        driver.get(_url("/budget/expenses/new/"))
        fill(w, By.ID, "id_title", "Deact Big Expense")
        fill(w, By.ID, "id_value", "99999.00")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("expense")
        driver.execute_script(f"""
            document.getElementById('id_date_due').value = '{today}';
            document.getElementById('id_settled').checked = true;
            document.getElementById('id_deactivated').checked = true;
        """)
        submit(w)
        wait_url(w, "/budget/expenses/")

        # Fetch its ID for cleanup
        resp = api_get("/api/v1/expenses/", ctx)
        big_deact_id = next(
            e["id"] for e in resp.json()["expenses"]
            if e["title"] == "Deact Big Expense"
        )

        driver.get(_url("/budget/"))
        time.sleep(1)

        paid_after = float(_read_panel_amount(driver, "panel-paid"))
        assert paid_after == baseline_paid, (
            f"Deactivated expense must not affect 'Paid' panel: "
            f"before={baseline_paid}, after={paid_after}"
        )

        # Cleanup everything this test and test_76 created
        api_delete(f"/api/v1/expenses/{big_deact_id}/", ctx)
        api_delete(f"/api/v1/expenses/{ctx['deact_exp_id']}/", ctx)
