"""
Group background picture: upload, display, serve, remove.

Covers:
- Admin can upload a group picture via the group detail settings form.
- The picture URL appears as background-image on the group detail header.
- The picture URL appears as background-image on the group card on /buddies/summary/.
- The picture is served (HTTP 200) at /media/bgpics/<id>.webp.
- Admin can remove the picture; it disappears from both pages.
- A non-admin does not see the upload form.
"""
import os
import time

import pytest
import requests
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user, BASE_URL
from bhelpers import _shell, _create_group, _add_group_member, _login_as

ASSET = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "projectpic.jpg")


class TestGroupPicture:

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Greta", last_name="GroupBg")
        group_id = int(_create_group(admin["email"], "BG Pic Group"))
        admin["group_id"] = group_id
        yield {"admin": admin}
        cleanup_user(admin["email"])

    # ── upload ──────────────────────────────────────────────────────────────

    def test_upload_form_visible_for_admin(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['admin']['group_id']}/"))
        time.sleep(1)
        assert "group_picture" in driver.page_source, \
            "Admin should see the group picture upload form"

    def test_upload_group_picture(self, driver, w, ctx):
        driver.execute_script(
            "document.getElementById('project-pic-input').style.display = 'block';"
        )
        driver.find_element(By.ID, "project-pic-input").send_keys(ASSET)
        driver.execute_script(
            "document.getElementById('btn-upload-project-pic').closest('form').submit();"
        )
        time.sleep(2)

    # ── group detail page ────────────────────────────────────────────────────

    def test_group_detail_header_has_bg_image(self, driver, w, ctx):
        gid = ctx["admin"]["group_id"]
        driver.get(_url(f"/projects/{gid}/"))
        time.sleep(1)
        assert f"/media/bgpics/{gid}.webp" in driver.page_source, \
            "Group detail header should contain the bgpics URL after upload"

    def test_group_detail_has_remove_button(self, driver, w, ctx):
        assert "Remove picture" in driver.page_source, \
            "Remove picture button should appear after upload"

    # ── summary page ─────────────────────────────────────────────────────────

    def test_summary_card_has_bg_image(self, driver, w, ctx):
        gid = ctx["admin"]["group_id"]
        driver.get(_url("/projects/"))
        time.sleep(1)
        assert f"/media/bgpics/{gid}.webp" in driver.page_source, \
            "Group card on projects page should contain the bgpics URL"

    # ── media URL serves the file ─────────────────────────────────────────────

    def test_image_url_returns_200(self, driver, w, ctx):
        gid = ctx["admin"]["group_id"]
        cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
        resp = requests.get(
            f"{BASE_URL}/media/bgpics/{gid}.webp", cookies=cookies, timeout=10
        )
        assert resp.status_code == 200, \
            f"Expected 200 from bgpics URL, got {resp.status_code}"
        assert resp.headers.get("Content-Type", "").startswith("image/"), \
            "Response should have an image Content-Type"

    # ── remove ───────────────────────────────────────────────────────────────

    def test_remove_group_picture(self, driver, w, ctx):
        gid = ctx["admin"]["group_id"]
        driver.get(_url(f"/projects/{gid}/"))
        time.sleep(1)
        driver.execute_script(
            "document.getElementById('btn-delete-project-pic').closest('form').submit();"
        )
        time.sleep(2)

    def test_group_detail_bg_image_gone_after_remove(self, driver, w, ctx):
        gid = ctx["admin"]["group_id"]
        driver.get(_url(f"/projects/{gid}/"))
        time.sleep(1)
        assert f"/media/bgpics/{gid}.webp" not in driver.page_source, \
            "bgpics URL should be gone from group detail after removal"
        assert "Remove picture" not in driver.page_source, \
            "Remove button should be gone after removal"

    def test_summary_card_bg_image_gone_after_remove(self, driver, w, ctx):
        gid = ctx["admin"]["group_id"]
        driver.get(_url("/projects/"))
        time.sleep(1)
        assert f"/media/bgpics/{gid}.webp" not in driver.page_source, \
            "bgpics URL should be gone from projects page after removal"

    # ── non-admin picture endpoint rejects ───────────────────────────────────

    def test_non_admin_picture_endpoint_rejects(self, driver, w, ctx):
        """POSTing to the picture endpoint as a non-admin must be rejected (404)."""
        import uuid
        member_email = f"nonamin-ep-{uuid.uuid4().hex[:8]}@test.invalid"
        _shell(
            f"from feusers.models import FeUser; "
            f"u = FeUser(email='{member_email}', first_name='Nona', last_name='Ep', "
            f"  is_confirmed=True, is_active=True); "
            f"u.set_password('TestPass456!'); u.save()"
        )
        _add_group_member(ctx["admin"]["group_id"], member_email)

        member_ctx = {"email": member_email, "password": "TestPass456!"}
        _login_as(driver, member_ctx)

        # Grab a live session cookie and POST directly to the picture endpoint.
        gid = ctx["admin"]["group_id"]
        cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
        csrf = cookies.get("csrftoken", "")
        resp = requests.post(
            f"{BASE_URL}/projects/{gid}/picture/",
            data={"csrfmiddlewaretoken": csrf},
            cookies=cookies,
            allow_redirects=False,
            timeout=10,
        )
        assert resp.status_code == 404, \
            f"Non-admin POST to picture endpoint should return 404, got {resp.status_code}"

        _shell(f"from feusers.models import FeUser; FeUser.objects.get(email='{member_email}').delete()")
        _login_as(driver, ctx["admin"])

    # ── non-admin cannot see upload form ─────────────────────────────────────

    def test_non_admin_has_no_upload_form(self, driver, w, ctx):
        # Create a second user and add them as a regular member via shell.
        import uuid
        member_email = f"nonamin-bgpic-{uuid.uuid4().hex[:8]}@test.invalid"
        _shell(
            f"from feusers.models import FeUser; "
            f"u = FeUser(email='{member_email}', first_name='Nona', last_name='Admin', "
            f"  is_confirmed=True, is_active=True); "
            f"u.set_password('TestPass456!'); u.save()"
        )
        _add_group_member(ctx["admin"]["group_id"], member_email)

        member_ctx = {"email": member_email, "password": "TestPass456!"}
        _login_as(driver, member_ctx)
        driver.get(_url(f"/projects/{ctx['admin']['group_id']}/"))
        time.sleep(1)
        assert "project-pic-input" not in driver.page_source, \
            "Non-admin should not see the group picture upload form"

        _shell(f"from feusers.models import FeUser; FeUser.objects.get(email='{member_email}').delete()")
        # Re-login as admin for any subsequent tests.
        _login_as(driver, ctx["admin"])
