"""
Rename offline buddy: personal context and group context.
Clicking the buddy name turns it into an inline text input (Enter to save, Escape to cancel).
"""
import time

import pytest
import requests
from selenium.webdriver.common.by import By

from helpers import _url, BASE_URL, session_cookies, setup_user, cleanup_user
from bhelpers import _shell, _create_group, _add_group_member


def _session(driver):
    s = requests.Session()
    s.cookies.update(session_cookies(driver))
    if not s.cookies.get("csrftoken"):
        s.get(BASE_URL + "/buddies/")
    return s


def _json_post(s, path, payload):
    csrf = s.cookies.get("csrftoken", "")
    return s.post(
        BASE_URL + path,
        json=payload,
        headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
        allow_redirects=False,
    )


class TestRenamePersonalDummy:
    """Owner can rename their personal offline buddy by clicking the name."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Rita", last_name="Renamer")
        dummy_id = _shell(
            f"from buddies.models import DummyUser; from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{c['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Old Name'); "
            f"print(d.pk)"
        )
        c["dummy_id"] = int(dummy_id)
        yield c
        cleanup_user(c["email"])

    def test_name_shown_on_buddies_page(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Old Name" in driver.page_source

    def test_name_span_is_editable(self, driver, w, ctx):
        span = driver.find_element(By.CSS_SELECTOR, ".buddy-name--editable")
        assert span.text.strip() == "Old Name"

    def test_click_name_shows_input(self, driver, w, ctx):
        span = driver.find_element(By.CSS_SELECTOR, ".buddy-name--editable")
        span.click()
        time.sleep(0.3)
        inp = driver.find_element(By.CSS_SELECTOR, ".buddy-name--editable input")
        assert inp is not None

    def test_rename_saves_on_enter(self, driver, w, ctx):
        inp = driver.find_element(By.CSS_SELECTOR, ".buddy-name--editable input")
        driver.execute_script("arguments[0].value = arguments[1];", inp, "New Name")
        driver.execute_script(
            "arguments[0].dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));",
            inp,
        )
        time.sleep(1)
        assert "New Name" in driver.page_source

    def test_old_name_gone(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert "Old Name" not in driver.page_source

    def test_renamed_in_database(self, driver, w, ctx):
        name = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.get(pk={ctx['dummy_id']}).display_name)"
        )
        assert name == "New Name"

    def test_escape_cancels_rename(self, driver, w, ctx):
        span = driver.find_element(By.CSS_SELECTOR, ".buddy-name--editable")
        span.click()
        time.sleep(0.3)
        inp = driver.find_element(By.CSS_SELECTOR, ".buddy-name--editable input")
        driver.execute_script("arguments[0].value = 'Discard This';", inp)
        driver.execute_script(
            "arguments[0].dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));",
            inp,
        )
        time.sleep(0.3)
        assert "New Name" in driver.page_source
        assert "Discard This" not in driver.page_source


class TestRenameGroupDummy:
    """Group admin can rename an offline member by clicking the name on the group detail page."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Greg", last_name="GroupAdmin")
        group_id = _create_group(c["email"], "Rename Group")
        dummy_id = _shell(
            f"from buddies.services import BuddyGroupService; "
            f"from feusers.models import FeUser; from buddies.models import Project; "
            f"a = FeUser.objects.get(email='{c['email']}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = BuddyGroupService.create_group_dummy(g, a, 'Old Group Member'); "
            f"print(d.pk)"
        )
        c["group_id"] = int(group_id)
        c["dummy_id"] = int(dummy_id)
        yield c
        cleanup_user(c["email"])

    def test_group_detail_shows_dummy(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Old Group Member" in driver.page_source

    def test_name_span_is_editable(self, driver, w, ctx):
        span = driver.find_element(By.CSS_SELECTOR, ".buddy-name--editable")
        assert span.text.strip() == "Old Group Member"

    def test_click_name_shows_input(self, driver, w, ctx):
        span = driver.find_element(By.CSS_SELECTOR, ".buddy-name--editable")
        span.click()
        time.sleep(0.3)
        inp = driver.find_element(By.CSS_SELECTOR, ".buddy-name--editable input")
        assert inp is not None

    def test_rename_saves_on_enter(self, driver, w, ctx):
        inp = driver.find_element(By.CSS_SELECTOR, ".buddy-name--editable input")
        driver.execute_script("arguments[0].value = arguments[1];", inp, "New Group Member")
        driver.execute_script(
            "arguments[0].dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));",
            inp,
        )
        time.sleep(1)
        assert "New Group Member" in driver.page_source

    def test_old_name_gone(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1)
        assert "Old Group Member" not in driver.page_source

    def test_renamed_in_database(self, driver, w, ctx):
        name = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.get(pk={ctx['dummy_id']}).display_name)"
        )
        assert name == "New Group Member"


class TestRenamePersonalDummyUnauthorized:
    """A user cannot rename another user's offline buddy."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        owner = setup_user(driver, w, first_name="Owen", last_name="Owner")
        dummy_id = _shell(
            f"from buddies.models import DummyUser; from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{owner['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Victim Buddy'); "
            f"print(d.pk)"
        )
        attacker = setup_user(driver, w, first_name="Eve", last_name="Attacker")
        yield {"owner": owner, "attacker": attacker, "dummy_id": int(dummy_id)}
        cleanup_user(owner["email"])
        cleanup_user(attacker["email"])

    def test_rename_other_users_dummy_is_rejected(self, driver, w, ctx):
        # driver is logged in as the attacker (setup_user leaves the browser there)
        s = _session(driver)
        resp = _json_post(s, f"/buddies/dummy/{ctx['dummy_id']}/rename/",
                          {"display_name": "Hacked"})
        assert resp.status_code == 404

    def test_dummy_name_unchanged_in_database(self, driver, w, ctx):
        name = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.get(pk={ctx['dummy_id']}).display_name)"
        )
        assert name == "Victim Buddy"


class TestRenameGroupDummyNonAdminUnauthorized:
    """A non-admin group member cannot rename an offline group member."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Ada", last_name="Admin")
        group_id = _create_group(admin["email"], "Auth Test Group")
        dummy_id = _shell(
            f"from buddies.services import BuddyGroupService; "
            f"from feusers.models import FeUser; from buddies.models import Project; "
            f"a = FeUser.objects.get(email='{admin['email']}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = BuddyGroupService.create_group_dummy(g, a, 'Group Victim'); "
            f"print(d.pk)"
        )
        member = setup_user(driver, w, first_name="Mal", last_name="Member")
        _add_group_member(int(group_id), member["email"])
        # driver is now logged in as the non-admin member
        yield {"admin": admin, "member": member,
               "group_id": int(group_id), "dummy_id": int(dummy_id)}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_non_admin_rename_is_rejected(self, driver, w, ctx):
        s = _session(driver)
        resp = _json_post(
            s,
            f"/projects/{ctx['group_id']}/dummy/{ctx['dummy_id']}/rename/",
            {"display_name": "Hacked"},
        )
        assert resp.status_code == 404

    def test_dummy_name_unchanged_in_database(self, driver, w, ctx):
        name = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.get(pk={ctx['dummy_id']}).display_name)"
        )
        assert name == "Group Victim"
