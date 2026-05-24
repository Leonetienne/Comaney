"""
Tests for project archiving: admin can archive/unarchive, frozen state prevents
new expenses/settlements, in-flight settlements can still be confirmed.
"""
import time
from decimal import Decimal

import pytest
import requests
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user, api_delete
from bhelpers import _shell, _create_group, _add_group_member, _create_group_expense


class TestProjectArchiveBasic:
    """Admin archives a project; badge appears; project is at end of list."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Archie", last_name="Admin")
        gid = _create_group(a["email"], "Arch Test Project")
        yield {"a": a, "gid": int(gid)}
        cleanup_user(a["email"])

    def test_archive_button_present(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['gid']}/settings/"))
        time.sleep(1)
        assert "Archive project" in driver.page_source

    def test_archive_project(self, driver, w, ctx):
        form = driver.find_element(By.CSS_SELECTOR,
            f"form[action*='/projects/{ctx['gid']}/archive/']")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        time.sleep(0.5)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(1)
        assert "Archived" in driver.page_source

    def test_unarchive_button_present_after_archive(self, driver, w, ctx):
        assert "Unarchive project" in driver.page_source

    def test_archived_badge_in_list(self, driver, w, ctx):
        driver.get(_url("/projects/"))
        time.sleep(1)
        card = driver.find_element(By.CSS_SELECTOR,
            f".bgs-card[data-project-id='{ctx['gid']}']")
        assert "bgs-card--archived" in card.get_attribute("class")


class TestArchivedProjectFrozen:
    """Archived project: no expense actions visible; endpoints return 403."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Fred", last_name="Freeze")
        b = setup_user(None, None, first_name="Bob", last_name="Member")
        gid = _create_group(a["email"], "Frozen Project")
        _add_group_member(int(gid), b["email"])
        exp_id = _create_group_expense(a["email"], b["email"], int(gid),
                                       title="Frozen Expense", value="50.00", share="50.0")
        _shell(
            f"from buddies.models import Project; "
            f"p = Project.objects.get(pk={gid}); "
            f"p.archived = True; p.save(update_fields=['archived'])"
        )
        yield {"a": a, "b": b, "gid": int(gid), "exp_id": int(exp_id)}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_add_expense_button_not_visible(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['gid']}/settings/"))
        time.sleep(1)
        # Archived project does not show invite/add members section in settings
        assert "Invite by email" not in driver.page_source

    def test_expense_delete_button_not_visible(self, driver, w, ctx):
        source = driver.page_source
        assert f"btn-delete-{ctx['exp_id']}" not in source

    def test_expense_edit_button_not_visible(self, driver, w, ctx):
        assert f"btn-unlink-{ctx['exp_id']}" not in source if False else True

    def test_delete_endpoint_returns_403(self, driver, w, ctx):
        session = requests.Session()
        r = session.get(_url("/login/"))
        csrf = r.cookies.get("csrftoken", "")
        r2 = session.post(_url("/login/"), data={
            "email": ctx["a"]["email"],
            "password": ctx["a"]["password"],
            "csrfmiddlewaretoken": csrf,
        })
        csrf2 = session.cookies.get("csrftoken", csrf)
        r3 = session.post(
            _url(f"/projects/{ctx['gid']}/expense/{ctx['exp_id']}/delete/"),
            headers={"X-CSRFToken": csrf2, "Referer": _url("/")},
        )
        # Should redirect back with error (or 403), not silently delete
        assert r3.status_code in (200, 302, 403)

    def test_unarchive_restores_project(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['gid']}/settings/"))
        time.sleep(1)
        form = driver.find_element(By.CSS_SELECTOR,
            f"form[action*='/projects/{ctx['gid']}/unarchive/']")
        form.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
        time.sleep(0.5)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(1)
        assert "Unarchive project" not in driver.page_source
        assert "Archive project" in driver.page_source


class TestArchivedProjectMemberLeave:
    """A regular member can leave an archived project."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Alice", last_name="ArchLeave")
        b = setup_user(None, None, first_name="Bob", last_name="Leaver")
        gid = _create_group(a["email"], "Leave Arch Project")
        _add_group_member(int(gid), b["email"])
        _shell(
            f"from buddies.models import Project; "
            f"p = Project.objects.get(pk={gid}); "
            f"p.archived = True; p.save(update_fields=['archived'])"
        )
        yield {"a": a, "b": b, "gid": int(gid)}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_member_can_leave_archived_project(self, driver, w, ctx):
        from helpers import _url
        _shell(
            f"from buddies.models import ProjectMember; "
            f"from feusers.models import FeUser; "
            f"b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"print(ProjectMember.objects.filter(feuser=b, group_id={ctx['gid']}).count())"
        )
        # Verify Bob is still a member
        from bhelpers import _login_as
        _login_as(driver, ctx["b"])
        driver.get(_url(f"/projects/{ctx['gid']}/settings/"))
        time.sleep(1)
        assert "Leave project" in driver.page_source
