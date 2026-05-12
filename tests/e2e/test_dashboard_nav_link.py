"""
Dashboard nav-link: verify card links append ?view=year when in year mode
and navigate cleanly in month mode.
"""
import time

import requests
import pytest

from helpers import (
    _url, server_today, session_cookies, BASE_URL, setup_user, cleanup_user,
)

CARDS_URL = BASE_URL + "/budget/dashboard/cards/"


def _cards_session(driver) -> requests.Session:
    s = requests.Session()
    s.cookies.update(session_cookies(driver))
    return s


def _csrf(sess) -> str:
    return next((c.value for c in sess.cookies if c.name == "csrftoken"), "")


def _post_card(sess, csrf, yaml_str) -> requests.Response:
    return sess.post(CARDS_URL, json={"yaml_config": yaml_str},
                     headers={"X-CSRFToken": csrf, "Content-Type": "application/json"})


def _delete_card(sess, csrf, card_id):
    sess.delete(f"{CARDS_URL}{card_id}/", headers={"X-CSRFToken": csrf})


def _cell_yaml(link="/budget/expenses/"):
    return (
        "type: cell\ntitle: NavLinkCell\nmethod: sum\n"
        f"link: {link}\n"
        "positioning:\n  position: 50\n  width: 3\n  height: 1\n"
    )


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


@pytest.fixture(scope="module")
def sess(driver, ctx):
    driver.get(_url("/budget/"))
    s = _cards_session(driver)
    # Remove default cards so only test cards are on the board.
    csrf = _csrf(s)
    for card in s.get(CARDS_URL).json()["cards"]:
        _delete_card(s, csrf, card["id"])
    return s


class TestNavLinkYearView:

    def test_cell_link_appends_view_year(self, driver, w, ctx, sess):
        today = server_today()
        year = today[:4]
        csrf = _csrf(sess)

        r = _post_card(sess, csrf, _cell_yaml())
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        driver.get(_url(f"/budget/?view=year&year={year}"))
        time.sleep(3)

        driver.execute_script(
            "document.querySelector('.dash-card-body--linked').click();"
        )
        time.sleep(2)

        assert "view=year" in driver.current_url

        _delete_card(sess, csrf, card_id)

    def test_cell_link_no_view_year_in_month_mode(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        csrf = _csrf(sess)

        r = _post_card(sess, csrf, _cell_yaml())
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        driver.get(_url(f"/budget/?year={year}&month={month}"))
        time.sleep(3)

        driver.execute_script(
            "document.querySelector('.dash-card-body--linked').click();"
        )
        time.sleep(2)

        assert "view=year" not in driver.current_url
        assert "/budget/expenses/" in driver.current_url

        _delete_card(sess, csrf, card_id)

    def test_cell_link_existing_query_gets_ampersand_not_question_mark(self, driver, w, ctx, sess):
        """Link that already has ?search=... should get &view=year appended, not ?view=year."""
        today = server_today()
        year = today[:4]
        csrf = _csrf(sess)

        r = _post_card(sess, csrf, _cell_yaml(link="/budget/expenses/?search=type%3Dexpense"))
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        driver.get(_url(f"/budget/?view=year&year={year}"))
        time.sleep(3)

        driver.execute_script(
            "document.querySelector('.dash-card-body--linked').click();"
        )
        time.sleep(2)

        url = driver.current_url
        assert "view=year" in url
        assert "search=" in url
        # Must be &view=year, not ?view=year (query string already present)
        assert "&view=year" in url

        _delete_card(sess, csrf, card_id)

    def test_cleanup(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        for card in sess.get(CARDS_URL).json()["cards"]:
            _delete_card(sess, csrf, card["id"])
        assert sess.get(CARDS_URL).json()["cards"] == []
