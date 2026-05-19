"""Custom backdrop: upload, render, delete (file removed), user delete (file removed)."""
import os
import re
import subprocess
import time

import requests
from selenium.webdriver.common.by import By

from helpers import BASE_URL, DOCKER_WEB, _url, cleanup_user, setup_user

BACKDROP_ASSET = os.path.join(os.path.dirname(__file__), "assets", "backdrop.png")


def _file_exists_on_server(pk) -> bool:
    result = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c",
         f"from django.conf import settings;"
         f" print((settings.MEDIA_ROOT / 'backdrops' / '{pk}.png').exists())"],
        capture_output=True, text=True, timeout=15,
    )
    return result.stdout.strip() == "True"


def _upload_backdrop(driver):
    driver.get(_url("/profile/"))
    time.sleep(1)
    driver.execute_script(
        "document.getElementById('id_custom_backdrop').style.display = 'block';"
    )
    driver.find_element(By.ID, "id_custom_backdrop").send_keys(BACKDROP_ASSET)
    time.sleep(3)


class TestCustomBackdrop:

    def test_upload_backdrop(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            _upload_backdrop(driver)
            assert "Backdrop updated." in driver.page_source
        finally:
            cleanup_user(ctx["email"])

    def test_backdrop_rendered_in_page(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            _upload_backdrop(driver)
            driver.get(_url("/budget/"))
            time.sleep(1)
            assert 'class="custom-backdrop"' in driver.page_source
            match = re.search(r'src="(/media/backdrops/\d+\.png)"', driver.page_source)
            assert match, "custom-backdrop img src not found in page source"
            cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
            resp = requests.get(f"{BASE_URL}{match.group(1)}", cookies=cookies, timeout=10)
            assert resp.status_code == 200
            assert resp.headers.get("Content-Type", "").startswith("image/")
        finally:
            cleanup_user(ctx["email"])

    def test_delete_backdrop_removes_file(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            _upload_backdrop(driver)
            match = re.search(r'/media/backdrops/(\d+)\.png', driver.page_source)
            assert match, "Could not find backdrop URL in page source"
            pk = match.group(1)
            assert _file_exists_on_server(pk), "File should exist after upload"
            driver.execute_script(
                "document.querySelector(\"input[name='action'][value='backdrop_delete']\")"
                ".closest('form').submit();"
            )
            time.sleep(2)
            assert "Backdrop removed." in driver.page_source
            assert not _file_exists_on_server(pk), "File should be gone after delete"
        finally:
            cleanup_user(ctx["email"])

    def test_opacity_setting_applied(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            _upload_backdrop(driver)
            driver.execute_script(
                "document.getElementById('id_backdrop_opacity').value = '42';"
            )
            driver.execute_script(
                "document.querySelector(\"input[name='action'][value='backdrop_settings']\")"
                ".closest('form').submit();"
            )
            time.sleep(2)
            driver.get(_url("/budget/"))
            time.sleep(1)
            assert "opacity:0.42" in driver.page_source
        finally:
            cleanup_user(ctx["email"])

    def test_fit_mode_setting_applied(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            _upload_backdrop(driver)
            driver.execute_script(
                "document.getElementById('id_backdrop_mode').value = 'contain';"
            )
            driver.execute_script(
                "document.querySelector(\"input[name='action'][value='backdrop_settings']\")"
                ".closest('form').submit();"
            )
            time.sleep(2)
            driver.get(_url("/budget/"))
            time.sleep(1)
            assert "object-fit:contain" in driver.page_source
        finally:
            cleanup_user(ctx["email"])

    def test_user_delete_removes_backdrop_file(self, driver, w):
        ctx = setup_user(driver, w)
        _upload_backdrop(driver)
        match = re.search(r'/media/backdrops/(\d+)\.png', driver.page_source)
        assert match, "Could not find backdrop URL in page source"
        pk = match.group(1)
        assert _file_exists_on_server(pk), "File should exist before user deletion"
        cleanup_user(ctx["email"])
        assert not _file_exists_on_server(pk), "File should be removed when user is deleted"
