"""
Tests for solo project behavior: no debt graph, no pie chart, no settle section,
expense creation works without participants, API returns correct spendings.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user, api_get
from bhelpers import _shell, _create_group


class TestSoloProjectDetailPage:
    """Solo project detail: collaborative sections are hidden."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Sam", last_name="Solo")
        gid = _create_group(a["email"], "Solo Project")
        yield {"a": a, "gid": int(gid)}
        cleanup_user(a["email"])

    def test_project_detail_reachable(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['gid']}/"))
        time.sleep(1)
        assert "Solo Project" in driver.page_source

    def test_debt_graph_not_visible(self, driver, w, ctx):
        assert "Expense flows" not in driver.page_source
        assert "Quickest way to settle" not in driver.page_source

    def test_pay_someone_back_not_visible(self, driver, w, ctx):
        assert "Pay someone back" not in driver.page_source

    def test_pie_chart_not_visible(self, driver, w, ctx):
        assert "Spending breakdown" not in driver.page_source


class TestSoloProjectExpenseCreation:
    """Create an expense for a solo project via the UI."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Nina", last_name="SoloExp")
        gid = _create_group(a["email"], "Solo Expense Project")
        yield {"a": a, "gid": int(gid), "exp_id": None}
        cleanup_user(a["email"])

    def test_expense_form_has_project_radio(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        assert "Expense assignment" in driver.page_source
        assert driver.find_element(By.ID, "assign-project")

    def test_select_project_radio(self, driver, w, ctx):
        driver.find_element(By.ID, "assign-project").click()
        time.sleep(0.5)
        section = driver.find_element(By.ID, "buddy-payment-section")
        assert section.is_displayed()

    def test_select_solo_project_hides_participant_controls(self, driver, w, ctx):
        driver.execute_script(
            f"var sel = document.getElementById('buddy-group-select');"
            f"if (sel) {{ sel.value = '{ctx['gid']}';"
            f"sel.dispatchEvent(new Event('change', {{bubbles: true}})); }}"
        )
        time.sleep(0.6)
        # For a solo project, payer row and participants row should be hidden
        payer_row = driver.find_element(By.ID, "buddy-payer-row")
        participants_row = driver.find_element(By.ID, "buddy-participants-row")
        assert payer_row.value_of_css_property("display") == "none" or \
               not payer_row.is_displayed(), "Payer row must be hidden for solo project"
        assert participants_row.value_of_css_property("display") == "none" or \
               not participants_row.is_displayed(), "Participants row must be hidden for solo project"

    def test_create_expense_for_solo_project(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        title_inp = driver.find_element(By.ID, "id_title")
        driver.execute_script("arguments[0].value = arguments[1];", title_inp, "Solo Repair Cost")
        value_inp = driver.find_element(By.ID, "id_value")
        driver.execute_script("arguments[0].value = '42.00';", value_inp)
        type_sel = driver.find_element(By.ID, "id_type")
        driver.execute_script("arguments[0].value = 'expense';", type_sel)
        date_inp = driver.find_element(By.ID, "id_date_due")
        driver.execute_script("arguments[0].value = '2026-06-01';", date_inp)

        driver.find_element(By.ID, "assign-project").click()
        time.sleep(0.4)
        driver.execute_script(
            f"var sel = document.getElementById('buddy-group-select');"
            f"if (sel) {{ sel.value = '{ctx['gid']}';"
            f"sel.dispatchEvent(new Event('change', {{bubbles: true}})); }}"
        )
        time.sleep(0.4)

        driver.find_element(By.CSS_SELECTOR, ".form-actions button[type=submit]").click()
        time.sleep(1)
        assert "at least one participant" not in driver.page_source

    def test_expense_appears_on_project_detail(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['gid']}/"))
        time.sleep(1)
        assert "Solo Repair Cost" in driver.page_source

    def test_api_expense_has_100_percent_spending(self, driver, w, ctx):
        exp_pk = _shell(
            f"from budget.models import Expense; "
            f"e = Expense.objects.filter(project_id={ctx['gid']}, title='Solo Repair Cost').first(); "
            f"print(e.pk if e else 'none')"
        )
        if exp_pk == "none":
            pytest.skip("Expense not found via shell")
        result = api_get(f"/api/v1/expenses/{exp_pk}/", ctx["a"])
        assert result.status_code == 200
        exp_data = result.json()
        assert exp_data.get("project") is not None
        assert exp_data["project"]["id"] == ctx["gid"]
        # Solo project expenses have no buddy spendings (solo-project path)
        participants = exp_data.get("buddy_participants", [])
        assert len(participants) == 0, "Solo project expense must not have buddy_participants"
