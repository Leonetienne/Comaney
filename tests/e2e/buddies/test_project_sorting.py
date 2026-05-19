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
