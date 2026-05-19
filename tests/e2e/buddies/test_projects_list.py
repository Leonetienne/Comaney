"""
Tests for the /projects/ list page: creating projects, listing, archiving badges,
and correct sorting order.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _create_group


class TestProjectsListPage:
    """The /projects/ page is reachable and shows the user's projects."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Lisa", last_name="ProjectOwner")
        group_id = _create_group(a["email"], "My Test Project")
        yield {"a": a, "group_id": int(group_id)}
        cleanup_user(a["email"])

    def test_projects_page_reachable(self, driver, w, ctx):
        driver.get(_url("/projects/"))
        time.sleep(1)
        assert driver.current_url.endswith("/projects/") or "/projects/" in driver.current_url

    def test_project_listed(self, driver, w, ctx):
        assert "My Test Project" in driver.page_source

    def test_project_card_is_link_to_detail(self, driver, w, ctx):
        link = driver.find_element(By.CSS_SELECTOR,
            f".bgs-card[data-project-id='{ctx['group_id']}'] a")
        assert f"/projects/{ctx['group_id']}/" in link.get_attribute("href")


class TestProjectCreationViaForm:
    """Create project form on /projects/ creates a project and redirects."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Matt", last_name="Creator")
        yield {"a": a, "created_id": None}
        cleanup_user(a["email"])

    def test_create_project_via_form(self, driver, w, ctx):
        driver.get(_url("/projects/"))
        time.sleep(1)
        inp = driver.find_element(By.ID, "project-name")
        driver.execute_script("arguments[0].value = arguments[1];", inp, "Form Created Project")
        driver.find_element(By.ID, "btn-create-project").click()
        time.sleep(1)
        assert "/projects/" in driver.current_url
        url = driver.current_url
        # Should have redirected to the project detail page
        parts = [p for p in url.split("/") if p.isdigit()]
        if parts:
            ctx["created_id"] = int(parts[-1])

    def test_project_name_shown_after_creation(self, driver, w, ctx):
        assert "Form Created Project" in driver.page_source

    def test_project_appears_in_list(self, driver, w, ctx):
        driver.get(_url("/projects/"))
        time.sleep(1)
        assert "Form Created Project" in driver.page_source


class TestArchivedProjectBadge:
    """Archived projects appear at the bottom with an Archived badge."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Anna", last_name="Archivist")
        active_id = _create_group(a["email"], "Active Project")
        archived_id = _create_group(a["email"], "Archived Project")
        _shell(
            f"from buddies.models import Project; "
            f"p = Project.objects.get(pk={archived_id}); "
            f"p.archived = True; p.save(update_fields=['archived'])"
        )
        yield {"a": a, "active_id": int(active_id), "archived_id": int(archived_id)}
        cleanup_user(a["email"])

    def test_archived_badge_shown(self, driver, w, ctx):
        driver.get(_url("/projects/"))
        time.sleep(1)
        archived_card = driver.find_element(By.CSS_SELECTOR,
            f".bgs-card[data-project-id='{ctx['archived_id']}']")
        assert "bgs-card--archived" in archived_card.get_attribute("class")
        assert "Archived" in archived_card.text

    def test_archived_project_at_end(self, driver, w, ctx):
        cards = driver.find_elements(By.CSS_SELECTOR, ".bgs-card")
        ids = [c.get_attribute("data-project-id") for c in cards]
        active_pos = ids.index(str(ctx["active_id"])) if str(ctx["active_id"]) in ids else -1
        archived_pos = ids.index(str(ctx["archived_id"])) if str(ctx["archived_id"]) in ids else -1
        assert active_pos < archived_pos, "Active project must come before archived project"
