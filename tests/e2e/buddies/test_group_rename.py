"""
Group rename: admin can rename the group and set a description.
Non-admin members and unauthenticated requests are rejected.
"""
import time

import pytest
import requests
from selenium.webdriver.common.by import By

from helpers import _url, BASE_URL, session_cookies, setup_user, cleanup_user, PASSWORD
from bhelpers import _shell, _create_group, _add_group_member


def _session(driver):
    s = requests.Session()
    s.cookies.update(session_cookies(driver))
    if not s.cookies.get("csrftoken"):
        s.get(BASE_URL + "/buddies/")
    return s


def _form_post(s, path, data):
    csrf = s.cookies.get("csrftoken", "")
    return s.post(
        BASE_URL + path,
        data=data,
        headers={"X-CSRFToken": csrf, "Referer": BASE_URL + path},
        allow_redirects=False,
    )


# ---------------------------------------------------------------------------
# Admin can rename the group via the UI form
# ---------------------------------------------------------------------------

class TestGroupRenameAdmin:
    """Admin can rename the group and set a description."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Rina", last_name="Admin")
        group_id = _create_group(a["email"], "Original Name")
        yield {"a": a, "group_id": int(group_id)}
        cleanup_user(a["email"])

    def test_group_detail_loads(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Original Name" in driver.page_source

    def test_rename_form_visible_for_admin(self, driver, w, ctx):
        assert "Rename project" in driver.page_source

    def test_rename_group_via_form(self, driver, w, ctx):
        name_input = driver.find_element(By.ID, "project-rename-name")
        driver.execute_script("arguments[0].value = arguments[1];", name_input, "Renamed Group")
        driver.find_element(By.ID, "btn-rename-project").click()
        time.sleep(1)
        assert "Renamed Group" in driver.page_source

    def test_old_name_gone(self, driver, w, ctx):
        assert "Original Name" not in driver.page_source

    def test_renamed_in_database(self, driver, w, ctx):
        name = _shell(
            f"from buddies.models import Project; "
            f"print(Project.objects.get(pk={ctx['group_id']}).name)"
        )
        assert name == "Renamed Group"

    def test_set_description_via_form(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        desc_input = driver.find_element(By.ID, "project-rename-desc")
        driver.execute_script("arguments[0].value = arguments[1];", desc_input, "A test description.")
        driver.find_element(By.ID, "btn-rename-project").click()
        time.sleep(1)
        assert "A test description." in driver.page_source

    def test_description_in_database(self, driver, w, ctx):
        desc = _shell(
            f"from buddies.models import Project; "
            f"print(Project.objects.get(pk={ctx['group_id']}).description)"
        )
        assert desc == "A test description."

    def test_clear_description(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        desc_input = driver.find_element(By.ID, "project-rename-desc")
        driver.execute_script("arguments[0].value = '';", desc_input)
        driver.find_element(By.ID, "btn-rename-project").click()
        time.sleep(1)
        desc = _shell(
            f"from buddies.models import Project; "
            f"print(repr(Project.objects.get(pk={ctx['group_id']}).description))"
        )
        assert desc == "''"


# ---------------------------------------------------------------------------
# Non-admin member is rejected (404)
# ---------------------------------------------------------------------------

class TestGroupRenameNonAdminRejected:
    """A non-admin group member posting to the rename endpoint gets 404."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Arnold", last_name="Admin")
        group_id = _create_group(admin["email"], "Admin Only Group")
        member = setup_user(driver, w, first_name="Mel", last_name="Member")
        _add_group_member(int(group_id), member["email"])
        # driver is now logged in as the non-admin member
        yield {"admin": admin, "member": member, "group_id": int(group_id)}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_non_admin_post_rejected(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(
            s,
            f"/projects/{ctx['group_id']}/rename/",
            {"name": "Hacked Name", "description": ""},
        )
        assert resp.status_code == 404

    def test_group_name_unchanged_in_database(self, driver, w, ctx):
        name = _shell(
            f"from buddies.models import Project; "
            f"print(Project.objects.get(pk={ctx['group_id']}).name)"
        )
        assert name == "Admin Only Group"


# ---------------------------------------------------------------------------
# Unauthenticated request is rejected (redirect to login)
# ---------------------------------------------------------------------------

class TestGroupRenameUnauthenticatedRejected:
    """An unauthenticated POST to the rename endpoint is redirected to login."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Ursula", last_name="Owner")
        group_id = _create_group(admin["email"], "Unauth Target Group")
        yield {"admin": admin, "group_id": int(group_id)}
        cleanup_user(admin["email"])

    def test_unauthenticated_post_redirected(self, driver, w, ctx):
        s = requests.Session()
        # Fetch the login page first to obtain a CSRF token
        s.get(BASE_URL + "/login/")
        csrf = s.cookies.get("csrftoken", "")
        resp = s.post(
            BASE_URL + f"/projects/{ctx['group_id']}/rename/",
            data={"name": "Hacked", "description": ""},
            headers={"X-CSRFToken": csrf},
            allow_redirects=False,
        )
        assert resp.status_code in (302, 403), (
            f"Expected redirect or forbidden for unauthenticated request, got {resp.status_code}"
        )

    def test_group_name_unchanged_in_database(self, driver, w, ctx):
        name = _shell(
            f"from buddies.models import Project; "
            f"print(Project.objects.get(pk={ctx['group_id']}).name)"
        )
        assert name == "Unauth Target Group"
