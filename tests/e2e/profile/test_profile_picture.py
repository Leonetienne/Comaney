"""Profile picture: upload, display in header, and removal."""
import os
import re
import time

import pytest
import requests
from selenium.webdriver.common.by import By

from helpers import (
    BASE_URL, _url, setup_user, cleanup_user,
)

PPIC_ASSET = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "ppic.jpg")


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w, first_name="Ada", last_name="Lovelace")
    yield c
    cleanup_user(c["email"])


class TestProfilePicture:

    def test_initials_shown_in_header_before_upload(self, driver, w, ctx):
        driver.get(_url("/budget/"))
        time.sleep(1)
        src = driver.page_source
        # Header should show the initials fallback span, not an <img> for the pic
        assert "user-avatar--initials" in src
        assert "AL" in src

    def test_upload_profile_picture(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)

        # Reveal the hidden file input so send_keys can target it.
        # File inputs cannot be set via JS (browser security); send_keys is required here.
        driver.execute_script(
            "document.getElementById('id_profile_picture').style.display = 'block';"
        )
        driver.find_element(By.ID, "id_profile_picture").send_keys(PPIC_ASSET)
        time.sleep(1)  # wait for cropper modal to open

        # Click Done to confirm the crop and trigger the fetch upload
        driver.find_element(By.ID, "img-cropper-done").click()
        time.sleep(3)  # allow fetch + DOM update to complete

        assert "Profile picture updated." in driver.page_source

    def test_header_shows_img_after_upload(self, driver, w, ctx):
        driver.get(_url("/budget/"))
        time.sleep(1)
        src = driver.page_source
        # The uploaded picture img tag should be present; initials span should not
        assert "user-avatar--initials" not in src
        assert 'class="user-avatar"' in src

    def test_ppic_url_returns_image(self, driver, w, ctx):
        # Extract the ppic URL from the page source (it's in the <img src="..."> tag)
        driver.get(_url("/profile/"))
        time.sleep(1)
        match = re.search(r'src="(/media/ppics/\d+\.jpg)"', driver.page_source)
        assert match, "Could not find ppic <img> src in page source"
        ppic_path = match.group(1)
        cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
        resp = requests.get(f"{BASE_URL}{ppic_path}", cookies=cookies, timeout=10)
        assert resp.status_code == 200
        assert resp.headers.get("Content-Type", "").startswith("image/")

    def test_remove_profile_picture(self, driver, w, ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        driver.execute_script(
            "document.querySelector(\"input[name='action'][value='picture_delete']\")"
            ".closest('form').submit();"
        )
        time.sleep(2)
        assert "Profile picture removed." in driver.page_source

    def test_initials_restored_after_removal(self, driver, w, ctx):
        driver.get(_url("/budget/"))
        time.sleep(1)
        src = driver.page_source
        assert "user-avatar--initials" in src
        assert "AL" in src
