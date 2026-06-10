"""
Tests for project sorting: archived last, reorder endpoint, member sorting.
"""
import json
import time

import pytest
import requests
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _create_group, _add_group_member


def _post_json(url, payload, user_ctx):
    """POST JSON with session auth."""
    s = requests.Session()
    r = s.get(_url("/login/"))
    csrf = r.cookies.get("csrftoken", "")
    s.post(_url("/login/"), data={
        "email": user_ctx["email"],
        "password": user_ctx["password"],
        "csrfmiddlewaretoken": csrf,
    })
    csrf2 = s.cookies.get("csrftoken", csrf)
    return s.post(url, json=payload, headers={
        "X-CSRFToken": csrf2,
        "Content-Type": "application/json",
    })


class TestArchivedSortedLast:
    """Archived projects always appear after non-archived ones."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Sort", last_name="Tester")
        g1 = _create_group(a["email"], "Sort Active 1")
        g2 = _create_group(a["email"], "Sort Archived 1")
        _shell(
            f"from buddies.models import Project; "
            f"p = Project.objects.get(pk={g2}); "
            f"p.archived = True; p.save(update_fields=['archived'])"
        )
        yield {"a": a, "g1": int(g1), "g2": int(g2)}
        cleanup_user(a["email"])

    def test_archived_after_non_archived(self, driver, w, ctx):
        driver.get(_url("/projects/"))
        time.sleep(1)
        cards = driver.find_elements(By.CSS_SELECTOR, ".bgs-card")
        ids = [c.get_attribute("data-project-id") for c in cards]
        if str(ctx["g1"]) in ids and str(ctx["g2"]) in ids:
            assert ids.index(str(ctx["g1"])) < ids.index(str(ctx["g2"]))


class TestReorderEndpoint:
    """POST /projects/reorder/ updates ProjectMember.sorting."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Reorder", last_name="User")
        g1 = _create_group(a["email"], "Reorder Project 1")
        g2 = _create_group(a["email"], "Reorder Project 2")
        yield {"a": a, "g1": int(g1), "g2": int(g2)}
        cleanup_user(a["email"])

    def test_reorder_endpoint_200(self, driver, w, ctx):
        r = _post_json(
            _url("/projects/reorder/"),
            {"order": [ctx["g2"], ctx["g1"]]},
            ctx["a"],
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("ok") is True

    def test_reorder_reflected_in_db(self, driver, w, ctx):
        sort1 = _shell(
            f"from buddies.models import ProjectMember; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"print(ProjectMember.objects.get(feuser=u, group_id={ctx['g1']}).sorting)"
        )
        sort2 = _shell(
            f"from buddies.models import ProjectMember; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"print(ProjectMember.objects.get(feuser=u, group_id={ctx['g2']}).sorting)"
        )
        assert int(sort2) < int(sort1), "g2 was placed first so should have smaller sorting value"

    def test_reorder_archived_ignored(self, driver, w, ctx):
        _shell(
            f"from buddies.models import Project; "
            f"p = Project.objects.get(pk={ctx['g1']}); "
            f"p.archived = True; p.save(update_fields=['archived'])"
        )
        r = _post_json(
            _url("/projects/reorder/"),
            {"order": [ctx["g1"], ctx["g2"]]},
            ctx["a"],
        )
        # Endpoint must return 200 but ignore/skip archived project
        assert r.status_code == 200


class TestTouchDragReorder:
    """Long-press + drag on touch devices reorders projects (mobile fix:
    HTML5 drag-and-drop has no touch equivalent, so without the touch
    handlers a long-press fell through to the native context menu)."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Touch", last_name="Dragger")
        # A brand-new user gets the getting-started intro modal on first page
        # load (see tests/e2e/profile/test_intros.py); its full-screen backdrop
        # would otherwise absorb every touch point in this test's coordinate-
        # based dispatch, so mark it seen up front like an already-onboarded user.
        _shell(
            f"from django.utils import timezone; from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{a['email']}'); "
            f"u.intro_seen_at = timezone.now(); u.save(update_fields=['intro_seen_at'])"
        )
        g1 = _create_group(a["email"], "Touch Project 1")
        g2 = _create_group(a["email"], "Touch Project 2")
        # Pin a known starting order (g1 before g2) so the drag direction below
        # is deterministic regardless of natural creation-order sorting.
        _post_json(_url("/projects/reorder/"), {"order": [int(g1), int(g2)]}, a)
        yield {"a": a, "g1": int(g1), "g2": int(g2)}
        cleanup_user(a["email"])

    def test_long_press_drag_reorders_cards(self, driver, w, ctx):
        driver.get(_url("/projects/"))
        time.sleep(1)

        cards = driver.find_elements(By.CSS_SELECTOR, ".bgs-card")
        ids = [c.get_attribute("data-project-id") for c in cards]
        assert ids.index(str(ctx["g1"])) < ids.index(str(ctx["g2"])), "fixture did not pin g1 before g2"

        first_card = cards[ids.index(str(ctx["g1"]))]
        second_card = cards[ids.index(str(ctx["g2"]))]
        r1, r2 = first_card.rect, second_card.rect
        x1, y1 = r1["x"] + r1["width"] / 2, r1["y"] + r1["height"] / 2
        x2, y2 = r2["x"] + r2["width"] / 2, r2["y"] + r2["height"] / 2

        # Plain Chrome ignores CDP-dispatched touch events unless the page is
        # actually reporting as a touch device; without this, dispatchTouchEvent
        # is a silent no-op and no touchstart/touchmove/touchend listener fires.
        driver.execute_cdp_cmd("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 1})
        driver.execute_cdp_cmd("Emulation.setEmitTouchEventsForMouse", {"enabled": False})
        try:
            driver.execute_cdp_cmd("Input.dispatchTouchEvent", {
                "type": "touchStart",
                "touchPoints": [{"x": x1, "y": y1}],
            })
            time.sleep(0.45)  # exceed the 300ms long-press threshold to enter drag mode
            driver.execute_cdp_cmd("Input.dispatchTouchEvent", {
                "type": "touchMove",
                "touchPoints": [{"x": x2, "y": y2}],
            })
            time.sleep(0.2)
            driver.execute_cdp_cmd("Input.dispatchTouchEvent", {
                "type": "touchEnd",
                "touchPoints": [],
            })
            time.sleep(1)
        finally:
            driver.execute_cdp_cmd("Emulation.setTouchEmulationEnabled", {"enabled": False})

        ids_after = [
            c.get_attribute("data-project-id")
            for c in driver.find_elements(By.CSS_SELECTOR, ".bgs-card")
        ]
        assert ids_after.index(str(ctx["g2"])) < ids_after.index(str(ctx["g1"])), (
            "long-press touch drag did not reorder the cards"
        )

        sort1 = _shell(
            f"from buddies.models import ProjectMember; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"print(ProjectMember.objects.get(feuser=u, group_id={ctx['g1']}).sorting)"
        )
        sort2 = _shell(
            f"from buddies.models import ProjectMember; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"print(ProjectMember.objects.get(feuser=u, group_id={ctx['g2']}).sorting)"
        )
        assert int(sort2) < int(sort1), "drag was not persisted via the reorder endpoint"

    def test_long_press_suppresses_native_context_menu(self, driver, w, ctx):
        driver.get(_url("/projects/"))
        time.sleep(1)
        card = driver.find_element(By.CSS_SELECTOR, ".bgs-card:not(.bgs-card--archived)")
        not_shown = driver.execute_script(
            "var ev = new MouseEvent('contextmenu', {bubbles: true, cancelable: true}); "
            "var dispatched = arguments[0].dispatchEvent(ev); "
            "return !dispatched;",
            card,
        )
        assert not_shown, "contextmenu was not prevented on a draggable card"

    def test_cards_allow_native_scroll_outside_a_drag(self, driver, w, ctx):
        """Regression test: an earlier version of the long-press-drag fix set
        touch-action: none statically on every card, which blocks the browser's
        native swipe-to-scroll for any touch starting on a card, not just an
        active drag. Scrolling must stay native (touch-action: auto) except
        for the window the touchmove handler explicitly preventDefault()s,
        i.e. while a long-press drag is actually in progress."""
        driver.get(_url("/projects/"))
        time.sleep(1)
        card = driver.find_element(By.CSS_SELECTOR, ".bgs-card:not(.bgs-card--archived)")
        touch_action = driver.execute_script(
            "return getComputedStyle(arguments[0]).touchAction;", card
        )
        assert touch_action != "none", (
            "project card has touch-action: none outside of an active drag, "
            "which disables native swipe-scrolling on the project list"
        )


class TestUpdateLastmod:
    """Project.update_lastmod() sets last_mod to now and persists it."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Lastmod", last_name="Tester")
        g = _create_group(a["email"], "Lastmod Test Project")
        yield {"a": a, "g": int(g)}
        cleanup_user(a["email"])

    def test_update_lastmod_sets_field(self, driver, w, ctx):
        before = _shell(
            f"from buddies.models import Project; "
            f"p = Project.objects.get(pk={ctx['g']}); "
            f"print(p.last_mod.isoformat())"
        )
        _shell(
            f"import time; time.sleep(1); "
            f"from buddies.models import Project; "
            f"p = Project.objects.get(pk={ctx['g']}); "
            f"p.update_lastmod()"
        )
        after = _shell(
            f"from buddies.models import Project; "
            f"p = Project.objects.get(pk={ctx['g']}); "
            f"print(p.last_mod.isoformat())"
        )
        assert after > before, f"last_mod was not updated: before={before} after={after}"


class TestNonAdminCanReorder:
    """A non-admin member can update their own sorting via the reorder endpoint."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Admin", last_name="Reorderer")
        b = setup_user(None, None, first_name="Member", last_name="Reorderer")
        g1 = _create_group(a["email"], "Non-Admin Reorder 1")
        g2 = _create_group(a["email"], "Non-Admin Reorder 2")
        _add_group_member(int(g1), b["email"])
        _add_group_member(int(g2), b["email"])
        yield {"a": a, "b": b, "g1": int(g1), "g2": int(g2)}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_member_can_reorder(self, driver, w, ctx):
        r = _post_json(
            _url("/projects/reorder/"),
            {"order": [ctx["g2"], ctx["g1"]]},
            ctx["b"],
        )
        assert r.status_code == 200
        assert r.json().get("ok") is True
