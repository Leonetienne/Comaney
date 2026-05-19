"""
Tests: admin is the only real member and cannot leave; can only delete.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _create_group


class TestAdminSoloCannotLeave:
    """When admin is the only real member, leave button is absent."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Lone", last_name="Admin")
        gid = _create_group(a["email"], "Solo Admin Project")
        yield {"a": a, "gid": int(gid)}
        cleanup_user(a["email"])

    def test_no_leave_button_for_solo_admin(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['gid']}/"))
        time.sleep(1)
        assert "Leave project" not in driver.page_source

    def test_delete_project_section_present(self, driver, w, ctx):
        assert "Delete project" in driver.page_source

    def test_delete_project_requires_name(self, driver, w, ctx):
        btn = driver.find_element(By.ID, "btn-delete-project")
        assert btn.get_attribute("disabled") is not None or \
               btn.get_attribute("disabled") == "true"

    def test_delete_project_with_correct_name(self, driver, w, ctx):
        inp = driver.find_element(By.ID, "delete-confirm-name")
        driver.execute_script("arguments[0].value = arguments[1];", inp, "Solo Admin Project")
        driver.execute_script("arguments[0].dispatchEvent(new Event('input'));", inp)
        time.sleep(0.3)
        btn = driver.find_element(By.ID, "btn-delete-project")
        assert btn.get_attribute("disabled") is None, "Button should be enabled after correct name"
        btn.click()
        time.sleep(1)
        assert "/projects/" in driver.current_url

    def test_project_gone_from_list(self, driver, w, ctx):
        driver.get(_url("/projects/"))
        time.sleep(1)
        assert "Solo Admin Project" not in driver.page_source


class TestAdminWithDummyCannotLeave:
    """Admin with only dummy members (no other real feuser) also cannot leave."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="DummyBoss", last_name="Admin")
        gid = _create_group(a["email"], "Dummy Only Project")
        _shell(
            f"from buddies.services import ProjectService; "
            f"from feusers.models import FeUser; "
            f"from buddies.models import Project; "
            f"a = FeUser.objects.get(email='{a['email']}'); "
            f"g = Project.objects.get(pk={gid}); "
            f"ProjectService.create_group_dummy(g, a, 'Tom Offline')"
        )
        yield {"a": a, "gid": int(gid)}
        cleanup_user(a["email"])

    def test_no_leave_button_when_only_dummies(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['gid']}/"))
        time.sleep(1)
        assert "Leave project" not in driver.page_source

    def test_delete_section_still_available(self, driver, w, ctx):
        assert "Delete project" in driver.page_source
