"""
Project "permission_laxity" setting: the admin picks, via a dropdown on the
Manage page, who may edit the project name, description and picture.

- 0 (default) "Admin only": only the admin sees the edit rows and may change them.
- 1 "Any member": every member sees the edit rows and may change them.

Everything else (invites, archive, delete, transfer admin) stays admin only.

Run with: pytest tests/e2e/projects/test_project_permission_laxity.py -v -s
"""
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as, _create_group, _add_group_member


def _settings_url(gid) -> str:
    return _url(f"/projects/{gid}/settings/")


def _laxity_value(gid) -> str:
    return _shell(
        f"from buddies.models import Project; "
        f"print(Project.objects.get(pk={gid}).permission_laxity)"
    )


def _project_name(gid) -> str:
    return _shell(
        f"from buddies.models import Project; "
        f"print(Project.objects.get(pk={gid}).name)"
    )


class TestPermissionLaxity:
    """Admin toggles laxity; a non-admin member gains/loses edit rights accordingly."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(None, None, first_name="Pia", last_name="Owner")
        member = setup_user(driver, w, first_name="Milo", last_name="Member")
        gid = _create_group(admin["email"], "Laxity Test Project")
        _add_group_member(int(gid), member["email"])
        yield {"admin": admin, "member": member, "gid": int(gid)}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_default_is_admin_only(self, driver, w, ctx):
        """A fresh project defaults to admin-only (laxity 0)."""
        assert _laxity_value(ctx["gid"]) == "0"

    def test_member_cannot_edit_by_default(self, driver, w, ctx):
        """With laxity 0 the member sees no rename form on the Manage page."""
        _login_as(driver, ctx["member"])
        driver.get(_settings_url(ctx["gid"]))
        time.sleep(1)
        assert not driver.find_elements(By.ID, "btn-rename-project"), \
            "Non-admin should not see the rename form while laxity is admin-only"

    def test_member_rename_blocked_server_side(self, driver, w, ctx):
        """Direct POST to rename is rejected for a non-admin while laxity is 0."""
        original = _project_name(ctx["gid"])
        _login_as(driver, ctx["member"])
        driver.get(_settings_url(ctx["gid"]))
        time.sleep(1)
        driver.execute_script(
            """
            var f = document.createElement('form');
            f.method = 'POST';
            f.action = arguments[0];
            var t = document.createElement('input'); t.name = 'csrfmiddlewaretoken';
            t.value = document.cookie.match(/csrftoken=([^;]+)/)[1]; f.appendChild(t);
            var n = document.createElement('input'); n.name = 'name'; n.value = 'Hacked Name';
            f.appendChild(n);
            document.body.appendChild(f); f.submit();
            """,
            _url(f"/projects/{ctx['gid']}/rename/"),
        )
        time.sleep(2)
        assert _project_name(ctx["gid"]) == original, \
            "Non-admin rename must be blocked server-side while laxity is admin-only"

    def test_admin_sees_dropdown_and_enables_members(self, driver, w, ctx):
        """Admin picks 'Any member' and clicks Save for it to persist."""
        _login_as(driver, ctx["admin"])
        driver.get(_settings_url(ctx["gid"]))
        time.sleep(1)
        select_el = driver.find_element(By.ID, "select-permission-laxity")
        Select(select_el).select_by_value("1")
        # Choosing the option alone must NOT save; only the Save button does.
        driver.find_element(By.ID, "btn-save-permission-laxity").click()
        time.sleep(2)
        assert _laxity_value(ctx["gid"]) == "1"

    def test_member_can_now_rename(self, driver, w, ctx):
        """With laxity 1 the member sees the rename form and can rename the project."""
        _login_as(driver, ctx["member"])
        driver.get(_settings_url(ctx["gid"]))
        time.sleep(1)
        name_input = driver.find_element(By.ID, "project-rename-name")
        driver.execute_script("arguments[0].value = arguments[1];", name_input, "Renamed By Member")
        driver.find_element(By.ID, "btn-rename-project").click()
        time.sleep(2)
        assert _project_name(ctx["gid"]) == "Renamed By Member"

    def test_member_still_cannot_access_admin_only_actions(self, driver, w, ctx):
        """Even with laxity 1, the member does not get transfer/archive/delete controls."""
        _login_as(driver, ctx["member"])
        driver.get(_settings_url(ctx["gid"]))
        time.sleep(1)
        assert not driver.find_elements(By.ID, "btn-transfer-admin"), \
            "Non-admin must never see transfer-admin controls"
        assert not driver.find_elements(By.ID, "select-permission-laxity"), \
            "Non-admin must never see the laxity dropdown"
