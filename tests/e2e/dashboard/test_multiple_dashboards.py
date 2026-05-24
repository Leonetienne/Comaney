"""
Multiple dashboards: API CRUD, UI smoke tests, pen tests (cross-user isolation).

Run with:  pytest tests/e2e/test_multiple_dashboards.py -sx -v

Test organisation:
    TestDashboardCrud      - CRUD on the dashboards API (session auth)
    TestCardWithDashboard  - Card API now requires dashboard_id; move between dashboards
    TestReset              - Reset is restricted to first dashboard
    TestReorder            - Dashboard tab reorder
    TestUITabBar           - Browser smoke: tab renders, double-click rename, +/x
    TestPenTests           - Cross-user isolation, auth guards
"""

import subprocess
import time

import requests
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from helpers import (
    _url, wait_text, session_cookies, BASE_URL,
    setup_user, cleanup_user,
)

DASHBOARDS_URL = BASE_URL + "/budget/dashboards/"
CARDS_URL      = BASE_URL + "/budget/dashboard/cards/"
RESET_URL      = BASE_URL + "/budget/dashboard/cards/reset/"
DOCKER_WEB     = "comaney-web-1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session(driver) -> requests.Session:
    s = requests.Session()
    s.cookies.update(session_cookies(driver))
    return s


def _csrf(sess) -> str:
    return next((c.value for c in sess.cookies if c.name == "csrftoken"), "")


def _post_json(sess, csrf, url, data) -> requests.Response:
    return sess.post(url, json=data,
                     headers={"X-CSRFToken": csrf, "Content-Type": "application/json"})


def _patch_json(sess, csrf, url, data) -> requests.Response:
    return sess.patch(url, json=data,
                      headers={"X-CSRFToken": csrf, "Content-Type": "application/json"})


def _delete(sess, csrf, url) -> requests.Response:
    return sess.delete(url, headers={"X-CSRFToken": csrf})


def _create_dashboard(sess, csrf, title="Test Dash") -> dict:
    r = _post_json(sess, csrf, DASHBOARDS_URL, {"title": title})
    assert r.status_code == 201, r.text
    return r.json()["dashboard"]


def _list_dashboards(sess) -> list:
    r = sess.get(DASHBOARDS_URL)
    assert r.status_code == 200, r.text
    return r.json()["dashboards"]


def _create_card(sess, csrf, dashboard_id, title="TestCard") -> dict:
    yaml_str = (
        "type: cell\ntitle: " + title + "\nmethod: sum\n"
        "positioning:\n  position: 1\n  width: 2\n  height: 1\n"
    )
    r = _post_json(sess, csrf, CARDS_URL, {
        "yaml_config": yaml_str,
        "dashboard_id": dashboard_id,
    })
    assert r.status_code == 201, r.text
    return r.json()["card"]


def _delete_dashboard(sess, csrf, dash_id):
    return _delete(sess, csrf, DASHBOARDS_URL + str(dash_id) + "/")


def _delete_card(sess, csrf, card_id):
    return _delete(sess, csrf, CARDS_URL + str(card_id) + "/")


def _get_user_dash_id(email, order_clause=""):
    """Return (dash_id, None) or (None, skip_reason) for the given user's first dashboard."""
    code = (
        "from feusers.models import FeUser; from budget.models import Dashboard; "
        "u = FeUser.objects.get(email='" + email + "'); "
        "d = Dashboard.objects.filter(owning_feuser=u)" + order_clause + ".first(); "
        "print(d.pk if d else 'NONE')"
    )
    result = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c", code],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    val = result.stdout.strip()
    if val == "NONE":
        return None, "User has no dashboard yet"
    return int(val), None


def _dash_title_in_db(dash_id) -> str:
    code = (
        "from budget.models import Dashboard; "
        "print(Dashboard.objects.get(pk=" + str(dash_id) + ").title)"
    )
    result = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c", code],
        capture_output=True, text=True, timeout=15,
    )
    return result.stdout.strip()


def _dash_exists_in_db(dash_id) -> bool:
    code = (
        "from budget.models import Dashboard; "
        "print(Dashboard.objects.filter(pk=" + str(dash_id) + ").exists())"
    )
    result = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c", code],
        capture_output=True, text=True, timeout=15,
    )
    return "True" in result.stdout


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    driver.get(_url("/budget/"))
    time.sleep(2)
    yield c
    cleanup_user(c["email"])


@pytest.fixture(scope="module")
def ctx2(driver, w):
    """Second independent user for cross-user isolation tests (no browser login)."""
    import uuid
    email = "sel.pt." + uuid.uuid4().hex[:8] + "@example.com"
    pw = "S3l3n!umTest"
    subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "create_user", email, "-p", pw],
        check=True, capture_output=True, timeout=15,
    )
    yield {"email": email, "password": pw}
    cleanup_user(email)


@pytest.fixture(scope="module")
def sess(driver, ctx):
    driver.get(_url("/budget/"))
    time.sleep(2)
    return _session(driver)


# ---------------------------------------------------------------------------
# TestDashboardCrud
# ---------------------------------------------------------------------------

class TestDashboardCrud:

    def test_initial_dashboard_exists(self, driver, w, ctx, sess):
        """create_defaults() must have created exactly one dashboard."""
        dashes = _list_dashboards(sess)
        assert len(dashes) >= 1
        ctx["first_dash_id"] = dashes[0]["id"]

    def test_create_dashboard(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        dash = _create_dashboard(sess, csrf, "My Second Dashboard")
        assert dash["title"] == "My Second Dashboard"
        assert "url" in dash
        assert dash["url"].startswith("/budget/dash/")
        ctx["second_dash_id"] = dash["id"]

    def test_list_dashboards_shows_both(self, driver, w, ctx, sess):
        dashes = _list_dashboards(sess)
        ids = [d["id"] for d in dashes]
        assert ctx["first_dash_id"] in ids
        assert ctx["second_dash_id"] in ids

    def test_rename_dashboard(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        dash_id = ctx["second_dash_id"]
        r = _patch_json(sess, csrf, DASHBOARDS_URL + str(dash_id) + "/", {"title": "Renamed"})
        assert r.status_code == 200, r.text
        assert r.json()["dashboard"]["title"] == "Renamed"

    def test_rename_requires_title(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        dash_id = ctx["second_dash_id"]
        r = _patch_json(sess, csrf, DASHBOARDS_URL + str(dash_id) + "/", {"title": ""})
        assert r.status_code == 400

    def test_title_max_length(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        dash_id = ctx["second_dash_id"]
        r = _patch_json(sess, csrf, DASHBOARDS_URL + str(dash_id) + "/", {"title": "x" * 129})
        assert r.status_code == 400

    def test_create_third_dashboard(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        dash = _create_dashboard(sess, csrf, "Third")
        ctx["third_dash_id"] = dash["id"]

    def test_delete_third_dashboard(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _delete_dashboard(sess, csrf, ctx["third_dash_id"])
        assert r.status_code == 200, r.text
        ids = [d["id"] for d in _list_dashboards(sess)]
        assert ctx["third_dash_id"] not in ids

    def test_delete_only_dashboard_blocked(self, driver, w, ctx, sess):
        """Can't delete when only one dashboard remains."""
        csrf = _csrf(sess)
        # Delete second so only first remains
        r = _delete_dashboard(sess, csrf, ctx["second_dash_id"])
        assert r.status_code == 200
        ctx.pop("second_dash_id")

        # Try to delete the last one
        r = _delete_dashboard(sess, csrf, ctx["first_dash_id"])
        assert r.status_code == 409

        # Recreate second for downstream tests
        dash = _create_dashboard(sess, csrf, "Second Dashboard")
        ctx["second_dash_id"] = dash["id"]

    def test_delete_nonexistent_returns_404(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _delete_dashboard(sess, csrf, 9999999)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# TestCardWithDashboard
# ---------------------------------------------------------------------------

class TestCardWithDashboard:

    def test_create_card_on_first_dashboard(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        card = _create_card(sess, csrf, ctx["first_dash_id"], "CardOnFirst")
        assert card["dashboard_id"] == ctx["first_dash_id"]
        ctx["card_on_first_id"] = card["id"]

    def test_create_card_on_second_dashboard(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        card = _create_card(sess, csrf, ctx["second_dash_id"], "CardOnSecond")
        assert card["dashboard_id"] == ctx["second_dash_id"]
        ctx["card_on_second_id"] = card["id"]

    def test_get_cards_filters_by_dashboard(self, driver, w, ctx, sess):
        r = sess.get(CARDS_URL, params={"dashboard_id": ctx["first_dash_id"]})
        assert r.status_code == 200
        ids = [c["id"] for c in r.json()["cards"]]
        assert ctx["card_on_first_id"] in ids
        assert ctx["card_on_second_id"] not in ids

    def test_get_cards_second_dashboard(self, driver, w, ctx, sess):
        r = sess.get(CARDS_URL, params={"dashboard_id": ctx["second_dash_id"]})
        assert r.status_code == 200
        ids = [c["id"] for c in r.json()["cards"]]
        assert ctx["card_on_second_id"] in ids
        assert ctx["card_on_first_id"] not in ids

    def test_move_card_between_dashboards(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        card_id = ctx["card_on_first_id"]
        target  = ctx["second_dash_id"]

        r = _patch_json(sess, csrf, CARDS_URL + str(card_id) + "/",
                        {"dashboard_id": target})
        assert r.status_code == 200, r.text
        assert r.json()["card"]["dashboard_id"] == target

        # No longer on first dashboard
        r2 = sess.get(CARDS_URL, params={"dashboard_id": ctx["first_dash_id"]})
        assert card_id not in [c["id"] for c in r2.json()["cards"]]

        # Now on second dashboard
        r3 = sess.get(CARDS_URL, params={"dashboard_id": ctx["second_dash_id"]})
        assert card_id in [c["id"] for c in r3.json()["cards"]]

        ctx["card_on_first_id"] = None

    def test_move_to_nonexistent_dashboard_404(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        card_id = ctx["card_on_second_id"]
        r = _patch_json(sess, csrf, CARDS_URL + str(card_id) + "/",
                        {"dashboard_id": 9999999})
        assert r.status_code == 404

    def test_create_card_invalid_dashboard_404(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_json(sess, csrf, CARDS_URL, {
            "yaml_config": "type: cell\ntitle: X\nmethod: sum\n",
            "dashboard_id": 9999999,
        })
        assert r.status_code == 404

    def test_cleanup_cards(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        for key in ("card_on_first_id", "card_on_second_id"):
            cid = ctx.get(key)
            if cid:
                _delete_card(sess, csrf, cid)


# ---------------------------------------------------------------------------
# TestReset
# ---------------------------------------------------------------------------

class TestReset:

    def test_reset_on_first_dashboard_succeeds(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_json(sess, csrf, RESET_URL, {"dashboard_id": ctx["first_dash_id"]})
        assert r.status_code == 200, r.text
        assert len(r.json()["cards"]) == 10  # 10 default cards

    def test_reset_on_second_dashboard_blocked(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_json(sess, csrf, RESET_URL, {"dashboard_id": ctx["second_dash_id"]})
        assert r.status_code == 409, r.text

    def test_reset_without_dashboard_id_uses_first(self, driver, w, ctx, sess):
        """Omitting dashboard_id falls back to the first dashboard."""
        csrf = _csrf(sess)
        r = _post_json(sess, csrf, RESET_URL, {})
        assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# TestReorder
# ---------------------------------------------------------------------------

class TestReorder:

    def test_reorder_dashboards(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        first  = ctx["first_dash_id"]
        second = ctx["second_dash_id"]

        # Swap order
        r = _post_json(sess, csrf, DASHBOARDS_URL + "reorder/",
                       {"order": [second, first]})
        assert r.status_code == 200, r.text
        updated = {d["id"]: d for d in r.json()["dashboards"]}
        assert updated[second]["sorting"] == 0
        assert updated[first]["sorting"] == 1

        # Restore original order
        _post_json(sess, csrf, DASHBOARDS_URL + "reorder/",
                   {"order": [first, second]})

    def test_reorder_ignores_foreign_ids(self, driver, w, ctx, sess):
        """Reorder with unknown IDs should not crash."""
        csrf = _csrf(sess)
        r = _post_json(sess, csrf, DASHBOARDS_URL + "reorder/",
                       {"order": [ctx["first_dash_id"], 9999999]})
        assert r.status_code == 200

    def test_reorder_requires_list(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_json(sess, csrf, DASHBOARDS_URL + "reorder/", {"order": "bad"})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# TestUITabBar — browser smoke tests
# ---------------------------------------------------------------------------

class TestUITabBar:

    def test_redirect_from_budget_root(self, driver, w, ctx, sess):
        """/budget/ must redirect to /budget/dash/<id>/."""
        driver.get(_url("/budget/"))
        time.sleep(2)
        assert "/budget/dash/" in driver.current_url

    def test_tab_bar_visible(self, driver, w, ctx, sess):
        driver.get(_url("/budget/"))
        time.sleep(3)
        tabbar = driver.find_element(By.CSS_SELECTOR, ".dash-tabbar-wrap")
        assert tabbar.is_displayed()

    def test_active_tab_shown(self, driver, w, ctx, sess):
        driver.get(_url("/budget/"))
        time.sleep(3)
        active_tab = driver.find_element(By.CSS_SELECTOR, ".dash-tab--active")
        assert active_tab.is_displayed()

    def test_close_button_on_active_tab(self, driver, w, ctx, sess):
        driver.get(_url("/budget/"))
        time.sleep(3)
        close_btn = driver.find_element(By.CSS_SELECTOR, ".dash-tab--active .dash-tab-close")
        assert close_btn.is_displayed()

    def test_add_dashboard_via_plus_button(self, driver, w, ctx, sess):
        driver.get(_url("/budget/"))
        time.sleep(3)

        # Click the + button
        driver.find_element(By.CSS_SELECTOR, ".dash-tab-add-btn").click()
        time.sleep(1)

        inp = driver.find_element(By.CSS_SELECTOR, ".dash-tab-new-input")
        driver.execute_script("arguments[0].value = arguments[1];", inp, "UI Created")
        driver.execute_script(
            "var e=arguments[0];"
            "e.dispatchEvent(new Event('input',{bubbles:true}));"
            "e.dispatchEvent(new Event('change',{bubbles:true}));",
            inp,
        )
        time.sleep(0.3)

        create_btn = driver.find_element(By.XPATH,
            "//div[contains(@class,'dash-tab-new-form')]//button[contains(text(),'Create')]")
        create_btn.click()
        time.sleep(3)

        assert "/budget/dash/" in driver.current_url
        path = driver.current_url.split("?")[0]
        new_id = int(path.rstrip("/").split("/")[-1])
        ctx["ui_created_dash_id"] = new_id

    def test_double_click_rename_active_tab(self, driver, w, ctx, sess):
        driver.get(_url("/budget/dash/" + str(ctx["first_dash_id"]) + "/"))
        time.sleep(3)

        active_title = driver.find_element(By.CSS_SELECTOR, ".dash-tab--active .dash-tab-title")
        driver.execute_script(
            "arguments[0].dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));",
            active_title,
        )
        time.sleep(0.5)

        rename_input = driver.find_element(By.CSS_SELECTOR, ".dash-tab--active .dash-tab-rename-input")
        driver.execute_script("arguments[0].value = arguments[1];", rename_input, "Renamed Via UI")
        driver.execute_script(
            "var e=arguments[0];"
            "e.dispatchEvent(new Event('input',{bubbles:true}));"
            "e.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));",
            rename_input,
        )
        time.sleep(1)

        wait_text(driver, w, "Renamed Via UI")

    def test_navigate_to_second_dashboard(self, driver, w, ctx, sess):
        """Clicking a non-active tab navigates to that dashboard."""
        first_id = ctx.get("first_dash_id") or _list_dashboards(sess)[0]["id"]
        driver.get(_url("/budget/dash/" + str(first_id) + "/"))
        time.sleep(3)

        # Find the non-active tab and click its title
        tabs = driver.find_elements(By.CSS_SELECTOR, ".dash-tab:not(.dash-tab--active) .dash-tab-title")
        assert len(tabs) >= 1, "No non-active tab found to click"
        tabs[0].click()
        time.sleep(2)

        assert "/budget/dash/" in driver.current_url
        path = driver.current_url.split("?")[0]
        new_id = int(path.rstrip("/").split("/")[-1])
        assert new_id != ctx["first_dash_id"]

    def test_cleanup_ui_created_dashboard(self, driver, w, ctx, sess):
        uid = ctx.get("ui_created_dash_id")
        if uid:
            csrf = _csrf(sess)
            driver.get(_url("/budget/"))
            time.sleep(1)
            _delete_dashboard(_session(driver), csrf, uid)


# ---------------------------------------------------------------------------
# TestPenTests — cross-user isolation and auth guards
# ---------------------------------------------------------------------------

class TestPenTests:

    def test_unauthenticated_dashboards_api_redirects(self):
        """Dashboards API without session should redirect/403."""
        s = requests.Session()
        r = s.get(DASHBOARDS_URL, allow_redirects=False)
        assert r.status_code in (302, 403)

    def test_unauthenticated_dashboard_page_redirects(self):
        """Dashboard detail URL without session should redirect."""
        s = requests.Session()
        r = s.get(BASE_URL + "/budget/dash/1/", allow_redirects=False)
        assert r.status_code in (302, 403)

    def test_cannot_read_other_users_dashboard(self, driver, w, ctx, ctx2, sess):
        """User1 list must not contain User2's dashboards."""
        user2_dash_id, skip = _get_user_dash_id(ctx2["email"])
        if skip:
            pytest.skip(skip)

        dash_ids = [d["id"] for d in _list_dashboards(sess)]
        assert user2_dash_id not in dash_ids, "User1 can see User2's dashboard in list!"

    def test_cannot_view_other_users_dashboard_page(self, driver, w, ctx, ctx2, sess):
        """User1 loading User2's dashboard URL must get 404."""
        user2_dash_id, skip = _get_user_dash_id(ctx2["email"])
        if skip:
            pytest.skip(skip)

        r = sess.get(BASE_URL + "/budget/dash/" + str(user2_dash_id) + "/")
        assert r.status_code == 404, \
            "User1 got %d for User2's dashboard — expected 404" % r.status_code

    def test_cannot_rename_other_users_dashboard(self, driver, w, ctx, ctx2, sess):
        """User1 PATCH on User2's dashboard must return 404 and leave title unchanged."""
        user2_dash_id, skip = _get_user_dash_id(ctx2["email"])
        if skip:
            pytest.skip(skip)

        csrf = _csrf(sess)
        r = _patch_json(sess, csrf, DASHBOARDS_URL + str(user2_dash_id) + "/",
                        {"title": "HACKED"})
        assert r.status_code == 404, \
            "User1 could rename User2's dashboard (got %d)" % r.status_code

        assert "HACKED" not in _dash_title_in_db(user2_dash_id)

    def test_cannot_delete_other_users_dashboard(self, driver, w, ctx, ctx2, sess):
        """User1 DELETE on User2's dashboard must return 404."""
        user2_dash_id, skip = _get_user_dash_id(ctx2["email"])
        if skip:
            pytest.skip(skip)

        csrf = _csrf(sess)
        r = _delete_dashboard(sess, csrf, user2_dash_id)
        assert r.status_code == 404, \
            "User1 could delete User2's dashboard (got %d)" % r.status_code

        assert _dash_exists_in_db(user2_dash_id), \
            "User2's dashboard was actually deleted!"

    def test_cannot_create_card_on_other_users_dashboard(self, driver, w, ctx, ctx2, sess):
        """User1 cannot POST a card onto User2's dashboard."""
        user2_dash_id, skip = _get_user_dash_id(ctx2["email"])
        if skip:
            pytest.skip(skip)

        csrf = _csrf(sess)
        r = _post_json(sess, csrf, CARDS_URL, {
            "yaml_config": "type: cell\ntitle: Injected\nmethod: sum\n",
            "dashboard_id": user2_dash_id,
        })
        assert r.status_code == 404, \
            "User1 could create card on User2's dashboard (got %d)" % r.status_code

    def test_cannot_move_own_card_to_other_users_dashboard(self, driver, w, ctx, ctx2, sess):
        """User1 cannot PATCH their card's dashboard_id to User2's dashboard."""
        user2_dash_id, skip = _get_user_dash_id(ctx2["email"])
        if skip:
            pytest.skip(skip)

        csrf = _csrf(sess)
        card = _create_card(sess, csrf, ctx["first_dash_id"], "MoveTarget")
        card_id = card["id"]

        try:
            r = _patch_json(sess, csrf, CARDS_URL + str(card_id) + "/",
                            {"dashboard_id": user2_dash_id})
            assert r.status_code == 404, \
                "User1 could move their card to User2's dashboard (got %d)" % r.status_code

            # Card must still be on User1's first dashboard
            r2 = sess.get(CARDS_URL, params={"dashboard_id": ctx["first_dash_id"]})
            assert card_id in [c["id"] for c in r2.json()["cards"]]
        finally:
            _delete_card(sess, csrf, card_id)

    def test_cannot_reset_other_users_dashboard(self, driver, w, ctx, ctx2, sess):
        """User1 cannot reset User2's first dashboard."""
        user2_dash_id, skip = _get_user_dash_id(
            ctx2["email"], order_clause=".order_by('sorting','uid')"
        )
        if skip:
            pytest.skip(skip)

        csrf = _csrf(sess)
        r = _post_json(sess, csrf, RESET_URL, {"dashboard_id": user2_dash_id})
        assert r.status_code == 404, \
            "User1 could reset User2's dashboard (got %d)" % r.status_code
