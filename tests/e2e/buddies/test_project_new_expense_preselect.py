"""
Project detail page: "New expense" FAB pre-selects the project on the expense
form, checks all members, and sets the back= URL.

Also covers the security case: a user cannot forge ?project= to pre-select a
project they are not a member of.

Tests navigate directly to the URL that the FAB links to:
  /budget/expenses/new/?project=<uid>&back=/projects/<uid>/
and verify the DOM state after JS initialisation.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _create_group, _login_as


class TestProjectNewExpensePreselect:
    """Opening the new-expense form via ?project=<uid>&back=... pre-selects the
    project, checks all participants, and embeds the back URL."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        user = setup_user(driver, w, first_name="Petra", last_name="Projector")
        email = user["email"]
        group_id = int(_create_group(email, "Preselect Test Project"))
        dummy_id = int(_shell(
            f"from buddies.services import BuddyGroupService; "
            f"from feusers.models import FeUser; from buddies.models import Project; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = BuddyGroupService.create_group_dummy(g, u, 'Alice Member'); "
            f"print(d.pk)"
        ))
        yield {**user, "group_id": group_id, "dummy_id": dummy_id}
        cleanup_user(email)

    def _open_form(self, driver, ctx):
        gid = ctx["group_id"]
        driver.get(_url(f"/budget/expenses/new/?project={gid}&back=/projects/{gid}/"))
        time.sleep(1.5)

    def test_expense_assignment_section_present(self, driver, w, ctx):
        self._open_form(driver, ctx)
        assert "Expense assignment" in driver.page_source

    def test_project_tab_is_active(self, driver, w, ctx):
        tab = driver.find_element(By.ID, "assign-project")
        classes = tab.get_attribute("class")
        assert "assign-tab--active" in classes, \
            f"Project tab must be active; got classes: {classes}"

    def test_buddy_section_visible(self, driver, w, ctx):
        section = driver.find_element(By.ID, "buddy-payment-section")
        assert section.is_displayed(), "Buddy payment section must be visible"

    def test_correct_project_selected(self, driver, w, ctx):
        sel = driver.find_element(By.ID, "buddy-group-select")
        assert sel.get_attribute("value") == str(ctx["group_id"]), \
            "Project dropdown must have the preselected project's id as value"

    def test_all_participants_checked(self, driver, w, ctx):
        checkboxes = driver.find_elements(
            By.CSS_SELECTOR,
            "#buddy-participants-checkboxes .buddy-participant-cb input[type=checkbox]"
        )
        assert len(checkboxes) >= 2, \
            f"Expected at least 2 participant checkboxes, got {len(checkboxes)}"
        unchecked = [
            cb for cb in checkboxes
            if not cb.is_selected() and cb.find_element(By.XPATH, "..").value_of_css_property("display") != "none"
        ]
        assert unchecked == [], \
            f"{len(unchecked)} participant checkbox(es) were not checked by default"

    def test_back_url_embedded_in_form(self, driver, w, ctx):
        gid = ctx["group_id"]
        back_input = driver.find_element(By.CSS_SELECTOR, "input[name='back']")
        assert back_input.get_attribute("value") == f"/projects/{gid}/", \
            f"Hidden back input must point to the project URL"


class TestProjectNewExpensePreselectForged:
    """A user who forges ?project= with another user's project id must NOT get
    that project pre-selected; the form opens without any project assignment."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        owner = setup_user(driver, w, first_name="Otto", last_name="Owner")
        attacker = setup_user(driver, w, first_name="Eve", last_name="Attacker")
        # Create a project owned by Otto; Eve is not a member
        group_id = int(_create_group(owner["email"], "Ottos Private Project"))
        yield {"owner": owner, "attacker": attacker, "group_id": group_id}
        cleanup_user(owner["email"])
        cleanup_user(attacker["email"])

    def test_forged_url_does_not_preselect_project(self, driver, w, ctx):
        _login_as(driver, ctx["attacker"])
        gid = ctx["group_id"]
        driver.get(_url(f"/budget/expenses/new/?project={gid}&back=/projects/{gid}/"))
        time.sleep(1.5)
        # Eve has no projects of her own, so the Project tab is never rendered
        tabs = driver.find_elements(By.ID, "assign-project")
        assert tabs == [], \
            "Project tab must not exist for a user with no projects of their own"

    def test_forged_url_does_not_show_victim_project_in_dropdown(self, driver, w, ctx):
        gid = ctx["group_id"]
        # The project dropdown itself must not exist (no projects at all for attacker)
        options = driver.find_elements(
            By.CSS_SELECTOR, f"#buddy-group-select option[value='{gid}']"
        )
        assert options == [], \
            "Otto's project must not appear in the attacker's form"

    def test_form_still_renders(self, driver, w, ctx):
        # The form renders normally despite the invalid ?project= param
        assert "New expense" in driver.page_source
