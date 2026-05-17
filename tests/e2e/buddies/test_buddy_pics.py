"""
Profile pictures in buddy contexts.

Covers:
- Personal offline buddy: upload via modal, display in balance list, remove.
- Group offline member: upload via modal, display in member card, remove.
- FeUser ppic in group member cards ("You" card and other-member card).
"""
import os
import subprocess
import time
import uuid

import pytest
import requests
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user, BASE_URL, DOCKER_WEB
from bhelpers import _shell, _create_group, _add_group_member, _get_pk

PPIC_ASSET = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "ppic.jpg")


# ── shared helpers ─────────────────────────────────────────────────────────────

def _open_dummy_pic_modal(driver, dummy_id):
    """Click the Upload picture button for a given dummy id."""
    driver.execute_script(
        f'document.querySelector(\'[data-dummy-id="{dummy_id}"]\').click();'
    )
    time.sleep(0.5)


def _upload_via_cropper(driver):
    """Expose the hidden file input in the dummy-pic-modal, send the test image,
    confirm in the cropper and wait for the fetch to finish."""
    driver.execute_script(
        "document.getElementById('dummy-pic-input').style.display = 'block';"
    )
    driver.find_element(By.ID, "dummy-pic-input").send_keys(PPIC_ASSET)
    time.sleep(1)   # wait for cropper to open
    driver.find_element(By.ID, "img-cropper-done").click()
    time.sleep(3)   # wait for fetch + DOM update


def _avatar_tag(driver, dummy_id):
    """Return 'img' or 'span' for the data-dummy-avatar element, or None."""
    return driver.execute_script(
        f'var el = document.querySelector(\'[data-dummy-avatar="{dummy_id}"]\');'
        "return el ? el.tagName.toLowerCase() : null;"
    )


def _ppic_url_in_page(driver, pk, subdir="ppics"):
    """Return True if /media/<subdir>/<pk>.jpg appears anywhere in the page source."""
    return f"/media/{subdir}/{pk}.jpg" in driver.page_source


# ── personal offline buddy picture ────────────────────────────────────────────

class TestPersonalDummyPicture:
    """Upload, display, and remove a profile picture for a personal offline buddy."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Petra", last_name="PicTest")
        email = c["email"]
        dummy_id = _shell(
            f"from buddies.models import DummyUser; from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='Pic Dummy'); "
            f"print(d.pk)"
        )
        # Shared expense so the balance row appears in the list.
        _shell(
            f"from budget.expense_factory import create_expense; "
            f"from feusers.models import FeUser; from budget.models import TransactionType; "
            f"from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"create_expense(owning_feuser=u, title='Pic Test Expense', "
            f"  type=TransactionType.EXPENSE, value=Decimal('10.00'), "
            f"  date_due=None, settled=False, "
            f"  buddy_spendings=[{{'type': 'dummy', 'id': {dummy_id}, 'share_percent': 50}}])"
        )
        c["dummy_id"] = int(dummy_id)
        yield c
        cleanup_user(c["email"])

    def test_initials_shown_before_upload(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert _avatar_tag(driver, ctx["dummy_id"]) == "span", \
            "Before upload the dummy avatar should be an initials span"

    def test_dummy_initials_content(self, driver, w, ctx):
        # "Pic Dummy" -> first letter of each word -> "PD"
        assert "PD" in driver.page_source

    def test_upload_dummy_picture_via_modal(self, driver, w, ctx):
        _open_dummy_pic_modal(driver, ctx["dummy_id"])
        _upload_via_cropper(driver)
        assert _avatar_tag(driver, ctx["dummy_id"]) == "img", \
            "After upload the balance-list avatar should switch to <img>"

    def test_dummy_pic_url_returns_image(self, driver, w, ctx):
        cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
        url = f"{BASE_URL}/media/offline-buddy-ppic/{ctx['dummy_id']}.jpg"
        resp = requests.get(url, cookies=cookies, timeout=10)
        assert resp.status_code == 200
        assert resp.headers.get("Content-Type", "").startswith("image/")

    def test_avatar_persists_after_page_reload(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert _avatar_tag(driver, ctx["dummy_id"]) == "img", \
            "After reload the dummy avatar should still be <img>"

    def test_remove_dummy_picture(self, driver, w, ctx):
        _open_dummy_pic_modal(driver, ctx["dummy_id"])
        time.sleep(0.5)
        driver.find_element(By.ID, "dummy-pic-delete").click()
        time.sleep(2)
        assert _avatar_tag(driver, ctx["dummy_id"]) == "span", \
            "After removal the dummy avatar should revert to initials span"

    def test_initials_restored_after_reload(self, driver, w, ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        assert _avatar_tag(driver, ctx["dummy_id"]) == "span", \
            "After reload post-removal the dummy avatar should be initials span"
        assert "PD" in driver.page_source


# ── group offline member picture ───────────────────────────────────────────────

class TestGroupDummyPicture:
    """Upload, display, and remove a profile picture for a group offline member."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Greta", last_name="GroupPic")
        group_id = _create_group(a["email"], "Pic Group")
        dummy_id = _shell(
            f"from buddies.models import DummyUser, BuddyGroup, BuddyGroupMember; "
            f"g = BuddyGroup.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='Group Pic Member'); "
            f"BuddyGroupMember.objects.create(group=g, dummy=d); "
            f"print(d.pk)"
        )
        a["group_id"] = int(group_id)
        a["dummy_id"] = int(dummy_id)
        yield {"a": a}
        cleanup_user(a["email"])

    def test_initials_shown_for_group_dummy(self, driver, w, ctx):
        driver.get(_url(f"/buddies/groups/{ctx['a']['group_id']}/"))
        time.sleep(1)
        assert _avatar_tag(driver, ctx["a"]["dummy_id"]) == "span", \
            "Before upload the group dummy avatar should be an initials span"

    def test_group_dummy_initials_content(self, driver, w, ctx):
        # "Group Pic Member" -> "G" + "M" = "GM"
        assert "GM" in driver.page_source

    def test_upload_group_dummy_picture(self, driver, w, ctx):
        _open_dummy_pic_modal(driver, ctx["a"]["dummy_id"])
        _upload_via_cropper(driver)
        assert _avatar_tag(driver, ctx["a"]["dummy_id"]) == "img", \
            "After upload the group member card avatar should switch to <img>"

    def test_group_dummy_pic_url_returns_image(self, driver, w, ctx):
        cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
        url = f"{BASE_URL}/media/offline-buddy-ppic/{ctx['a']['dummy_id']}.jpg"
        resp = requests.get(url, cookies=cookies, timeout=10)
        assert resp.status_code == 200
        assert resp.headers.get("Content-Type", "").startswith("image/")

    def test_group_dummy_pic_persists_after_reload(self, driver, w, ctx):
        driver.get(_url(f"/buddies/groups/{ctx['a']['group_id']}/"))
        time.sleep(1)
        assert _avatar_tag(driver, ctx["a"]["dummy_id"]) == "img", \
            "After reload the group dummy avatar should still be <img>"

    def test_remove_group_dummy_picture(self, driver, w, ctx):
        _open_dummy_pic_modal(driver, ctx["a"]["dummy_id"])
        time.sleep(0.5)
        driver.find_element(By.ID, "dummy-pic-delete").click()
        time.sleep(2)
        assert _avatar_tag(driver, ctx["a"]["dummy_id"]) == "span", \
            "After removal the group dummy avatar should revert to initials span"

    def test_group_dummy_initials_restored_after_reload(self, driver, w, ctx):
        driver.get(_url(f"/buddies/groups/{ctx['a']['group_id']}/"))
        time.sleep(1)
        assert _avatar_tag(driver, ctx["a"]["dummy_id"]) == "span", \
            "After reload post-removal the group dummy avatar should be initials span"
        assert "GM" in driver.page_source


# ── feuser profile picture in buddy list and group member cards ────────────────

class TestFeuserPicInBuddyLists:
    """FeUser profile pictures render correctly in group member cards."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        # admin: the browser user
        admin = setup_user(driver, w, first_name="Frank", last_name="Admin")
        group_id = _create_group(admin["email"], "FeUser Pic Group")
        admin["group_id"] = int(group_id)

        # member: created via shell so no second browser session is needed
        member_email = f"member-pic-{uuid.uuid4().hex[:8]}@test.invalid"
        member_pk = _shell(
            f"from feusers.models import FeUser; "
            f"u = FeUser(email='{member_email}', first_name='Mary', last_name='Member', "
            f"  is_confirmed=True, is_active=True); "
            f"u.set_password('TestPass456!'); u.save(); "
            f"print(u.pk)"
        )
        _add_group_member(int(group_id), member_email)

        # Give the member a profile picture via docker cp + model flag.
        subprocess.run(
            ["docker", "cp", PPIC_ASSET,
             f"{DOCKER_WEB}:/app/data/media/ppics/{member_pk}.jpg"],
            check=True, capture_output=True,
        )
        _shell(
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(pk={member_pk}); "
            f"u.profile_picture = True; u.save(update_fields=['profile_picture'])"
        )

        admin["member_pk"] = int(member_pk)
        admin["member_email"] = member_email
        yield {"admin": admin}
        cleanup_user(admin["email"])
        cleanup_user(member_email)

    def test_you_card_shows_initials_before_upload(self, driver, w, ctx):
        # The admin has no ppic yet; their "You" card should show initials.
        driver.get(_url(f"/buddies/groups/{ctx['admin']['group_id']}/"))
        time.sleep(1)
        assert "user-avatar--initials" in driver.page_source
        # "Frank Admin" -> "FA"
        assert "FA" in driver.page_source

    def test_member_ppic_shown_in_group_member_card(self, driver, w, ctx):
        # Mary Member has a ppic; her card should contain an <img> with her ppic URL.
        driver.get(_url(f"/buddies/groups/{ctx['admin']['group_id']}/"))
        time.sleep(1)
        assert _ppic_url_in_page(
            driver, ctx["admin"]["member_pk"], subdir="ppics"
        ), "Group member card should contain an <img> with the member's ppic URL"

    def test_upload_admin_ppic_and_you_card_updates(self, driver, w, ctx):
        # Upload admin's own ppic via the profile page.
        driver.get(_url("/profile/"))
        time.sleep(1)
        driver.execute_script(
            "document.getElementById('id_profile_picture').style.display = 'block';"
        )
        driver.find_element(By.ID, "id_profile_picture").send_keys(PPIC_ASSET)
        time.sleep(1)
        driver.find_element(By.ID, "img-cropper-done").click()
        time.sleep(3)
        assert "Profile picture updated." in driver.page_source

    def test_you_card_shows_img_after_upload(self, driver, w, ctx):
        admin_pk = _get_pk(ctx["admin"]["email"])
        driver.get(_url(f"/buddies/groups/{ctx['admin']['group_id']}/"))
        time.sleep(1)
        assert _ppic_url_in_page(driver, admin_pk, subdir="ppics"), \
            "After upload the admin's You card should contain their ppic URL"
