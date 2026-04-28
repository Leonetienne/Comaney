"""Tests: sidebar/hamburger visibility on public pages based on login state."""
import pytest
import requests

from conftest import BASE_URL, session_cookies

PUBLIC_URL = f"{BASE_URL}/impressum/"


def _get_public_page(cookies=None):
    resp = requests.get(PUBLIC_URL, cookies=cookies or {}, timeout=10, allow_redirects=True)
    return resp


class TestPublicPageNav:

    def test_sidebar_hidden_when_logged_out(self, driver, w, ctx):
        resp = _get_public_page()
        if resp.status_code == 404:
            pytest.skip("/impressum/ does not exist in this environment")
        assert resp.status_code == 200
        assert 'class="sidebar"' not in resp.text, "sidebar should not appear for logged-out users on public pages"
        assert 'id="hamburger"' not in resp.text, "hamburger should not appear for logged-out users on public pages"

    def test_sidebar_visible_when_logged_in(self, driver, w, ctx):
        resp = _get_public_page(cookies=session_cookies(driver))
        if resp.status_code == 404:
            pytest.skip("/impressum/ does not exist in this environment")
        assert resp.status_code == 200
        assert 'class="sidebar"' in resp.text, "sidebar should appear for logged-in users on public pages"
        assert 'id="hamburger"' in resp.text, "hamburger should appear for logged-in users on public pages"
