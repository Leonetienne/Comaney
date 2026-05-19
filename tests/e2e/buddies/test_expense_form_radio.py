"""
Tests for the new "Expense assignment" radio group in the expense form.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _create_group, _create_buddy_link, _get_pk


class TestRadioGroupVisible:
    """Expense form shows the three radio buttons: None, Direct Buddy, Project."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Radio", last_name="Tester")
        b = setup_user(None, None, first_name="Radio", last_name="Buddy")
        _create_buddy_link(a["email"], b["email"])
        gid = _create_group(a["email"], "Radio Test Project")
        yield {"a": a, "b": b, "gid": int(gid)}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_radio_group_present(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        assert "Expense assignment" in driver.page_source

    def test_none_radio_present(self, driver, w, ctx):
        assert driver.find_element(By.ID, "assign-none")

    def test_buddy_radio_present(self, driver, w, ctx):
        assert driver.find_element(By.ID, "assign-buddy")

    def test_project_radio_present(self, driver, w, ctx):
        assert driver.find_element(By.ID, "assign-project")

    def test_default_none_selected(self, driver, w, ctx):
        none_btn = driver.find_element(By.ID, "assign-none")
        assert "assign-tab--active" in none_btn.get_attribute("class")

    def test_section_hidden_by_default(self, driver, w, ctx):
        section = driver.find_element(By.ID, "buddy-payment-section")
        assert not section.is_displayed()


class TestRadioBuddyOption:
    """Selecting 'Direct Buddy' shows the single-buddy section."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="BuddyRadio", last_name="A")
        b = setup_user(None, None, first_name="BuddyRadio", last_name="B")
        _create_buddy_link(a["email"], b["email"])
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_select_direct_buddy_shows_section(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        driver.find_element(By.ID, "assign-buddy").click()
        time.sleep(0.5)
        section = driver.find_element(By.ID, "buddy-payment-section")
        assert section.is_displayed()

    def test_switch_to_none_hides_section(self, driver, w, ctx):
        driver.find_element(By.ID, "assign-none").click()
        time.sleep(0.3)
        section = driver.find_element(By.ID, "buddy-payment-section")
        assert not section.is_displayed()


class TestRadioProjectOption:
    """Selecting 'Project' shows the project section and dropdown."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="ProjRadio", last_name="A")
        b = setup_user(None, None, first_name="ProjRadio", last_name="B")
        _create_buddy_link(a["email"], b["email"])
        gid = _create_group(a["email"], "ProjRadio Project")
        yield {"a": a, "b": b, "gid": int(gid)}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_select_project_shows_section(self, driver, w, ctx):
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        driver.find_element(By.ID, "assign-project").click()
        time.sleep(0.5)
        section = driver.find_element(By.ID, "buddy-payment-section")
        assert section.is_displayed()

    def test_project_dropdown_shown(self, driver, w, ctx):
        row = driver.find_element(By.ID, "buddy-group-select-row")
        assert row.is_displayed()

    def test_switch_to_none_hides_project_section(self, driver, w, ctx):
        driver.find_element(By.ID, "assign-none").click()
        time.sleep(0.3)
        section = driver.find_element(By.ID, "buddy-payment-section")
        assert not section.is_displayed()

    def test_archived_project_not_in_dropdown(self, driver, w, ctx):
        # Archive the project
        archived_gid = _create_group(ctx["a"]["email"], "Archived Radio Project")
        _shell(
            f"from buddies.models import Project; "
            f"p = Project.objects.get(pk={archived_gid}); "
            f"p.archived = True; p.save(update_fields=['archived'])"
        )
        driver.get(_url("/budget/expenses/new/"))
        time.sleep(1)
        driver.find_element(By.ID, "assign-project").click()
        time.sleep(0.5)
        sel = driver.find_element(By.ID, "buddy-group-select")
        options = [o.get_attribute("value") for o in sel.find_elements(By.TAG_NAME, "option")]
        assert str(archived_gid) not in options, "Archived project must not appear in dropdown"


class TestRadioPreselectedOnEdit:
    """When editing an expense with a project, 'Project' radio is pre-selected."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="EditRadio", last_name="A")
        b = setup_user(None, None, first_name="EditRadio", last_name="B")
        _create_buddy_link(a["email"], b["email"])
        gid = _create_group(a["email"], "Edit Radio Project")
        _add_group_member = lambda gid, email: _shell(
            f"from buddies.models import ProjectMember, Project; "
            f"from feusers.models import FeUser; "
            f"g = Project.objects.get(pk={gid}); "
            f"u = FeUser.objects.get(email='{email}'); "
            f"ProjectMember.objects.get_or_create(group=g, feuser=u)"
        )
        _add_group_member(int(gid), b["email"])
        exp_pk = _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import BuddySpending, Project; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"a = FeUser.objects.get(email='{a['email']}'); "
            f"b = FeUser.objects.get(email='{b['email']}'); "
            f"g = Project.objects.get(pk={gid}); "
            f"e = Expense.objects.create(owning_feuser=a, title='Edit Radio Exp', "
            f"  type='expense', value=Decimal('30.00'), settled=False, "
            f"  buddy_approved=True, project=g); "
            f"BuddySpending.objects.create(expense=e, participant_feuser=b, "
            f"  share_percent=Decimal('50.0')); "
            f"print(e.pk)"
        )
        yield {"a": a, "b": b, "gid": int(gid), "exp_pk": int(exp_pk)}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_project_radio_preselected(self, driver, w, ctx):
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit/"))
        time.sleep(1)
        project_btn = driver.find_element(By.ID, "assign-project")
        assert "assign-tab--active" in project_btn.get_attribute("class"), \
            "Project radio must be pre-selected when editing project expense"
