"""
Sidebar/hamburger visibility on public pages based on login state.

The /impressum/ URL may or may not exist in a given deployment;
tests skip gracefully when it returns 404.
"""
import pytest
import requests

from helpers import BASE_URL, session_cookies, setup_user, cleanup_user

PUBLIC_URL = BASE_URL + "/impressum/"


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestPublicPageNav:

    def test_sidebar_hidden_logged_out(self, driver, w, ctx):
        resp = requests.get(PUBLIC_URL, timeout=10, allow_redirects=True)
        if resp.status_code == 404:
            pytest.skip("/impressum/ does not exist in this environment")
        assert resp.status_code == 200
        assert 'class="sidebar"' not in resp.text
        assert 'id="hamburger"' not in resp.text

    def test_sidebar_visible_logged_in(self, driver, w, ctx):
        resp = requests.get(PUBLIC_URL, cookies=session_cookies(driver),
                            timeout=10, allow_redirects=True)
        if resp.status_code == 404:
            pytest.skip("/impressum/ does not exist in this environment")
        assert resp.status_code == 200
        assert 'class="sidebar"' in resp.text
        assert 'id="hamburger"' in resp.text
