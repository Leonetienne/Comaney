"""
Dashboard gauge card: API validation, data computation, and browser smoke test.
"""
import time

import requests
import pytest

from helpers import (
    _url, api_post, api_delete, server_today,
    session_cookies, BASE_URL, setup_user, cleanup_user,
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


def _gauge_yaml(
    query="type=expense",
    method="sum",
    max_value=None,
    max_value_query=None,
    max_value_method=None,
    extra_fields="",
    position=60,
    width=3,
    height=2,
) -> str:
    lines = [
        "type: gauge",
        "title: TestGauge",
        f"query: \"{query}\"" if query is not None else None,
        f"method: {method}" if method is not None else None,
    ]
    if max_value is not None:
        lines.append(f"max_value: {max_value}")
    if max_value_query is not None:
        lines.append(f'max_value_query: "{max_value_query}"')
    if max_value_method is not None:
        lines.append(f"max_value_method: {max_value_method}")
    if extra_fields:
        lines.append(extra_fields)
    lines += [
        "positioning:",
        f"  position: {position}",
        f"  width: {width}",
        f"  height: {height}",
    ]
    return "\n".join(l for l in lines if l is not None) + "\n"


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


@pytest.fixture(scope="module")
def sess(driver, ctx):
    driver.get(_url("/budget/"))
    s = _cards_session(driver)
    return s


class TestGaugeValidation:

    def test_create_gauge_with_fixed_max(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _gauge_yaml(max_value=200))
        assert r.status_code == 201, r.text
        card = r.json()["card"]
        assert card["config"]["type"] == "gauge"
        assert card["config"]["max_value"] == 200.0
        _delete_card(sess, csrf, card["id"])

    def test_create_gauge_with_dynamic_max(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _gauge_yaml(
            max_value_query="type=income", max_value_method="sum",
        ))
        assert r.status_code == 201, r.text
        cfg = r.json()["card"]["config"]
        assert cfg["max_value_query"] == "type=income"
        assert cfg["max_value_method"] == "sum"
        _delete_card(sess, csrf, r.json()["card"]["id"])

    def test_missing_query_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _gauge_yaml(query=None, max_value=200))
        assert r.status_code == 400

    def test_missing_method_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _gauge_yaml(method=None, max_value=200))
        assert r.status_code == 400

    def test_invalid_method_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _gauge_yaml(method="average", max_value=200))
        assert r.status_code == 400

    def test_both_max_fields_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _gauge_yaml(
            max_value=200, max_value_query="type=income", max_value_method="sum",
        ))
        assert r.status_code == 400

    def test_neither_max_field_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _gauge_yaml())
        assert r.status_code == 400

    def test_max_value_query_without_method_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _gauge_yaml(max_value_query="type=income"))
        assert r.status_code == 400

    def test_invalid_max_value_method_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _gauge_yaml(
            max_value_query="type=income", max_value_method="average",
        ))
        assert r.status_code == 400

    def test_max_value_zero_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _gauge_yaml(max_value=0))
        assert r.status_code == 400

    def test_max_value_negative_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _gauge_yaml(max_value=-50))
        assert r.status_code == 400

    def test_max_value_non_numeric_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _gauge_yaml(max_value="not_a_number"))
        assert r.status_code == 400

    def test_unknown_field_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _gauge_yaml(
            max_value=200, extra_fields='template: "$VALUE"',
        ))
        assert r.status_code == 400

    def test_color_breakpoints_round_trip(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        extra = (
            "color_breakpoints:\n"
            "  - less_than: 100\n"
            "    color: '#ffff00'\n"
            "  - less_than: 0\n"
            "    color: '#ff0000'"
        )
        r = _post_card(sess, csrf, _gauge_yaml(max_value=200, extra_fields=extra))
        assert r.status_code == 201, r.text
        bps = r.json()["card"]["config"]["color_breakpoints"]
        assert len(bps) == 2
        assert bps[0]["less_than"] == 100.0
        assert bps[0]["color"] == "#ffff00"
        _delete_card(sess, csrf, r.json()["card"]["id"])

    def test_gauge_color_round_trip(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        extra = "gauge_color: '#4caf50'\ngauge_color_darkmode: '#81c784'"
        r = _post_card(sess, csrf, _gauge_yaml(max_value=200, extra_fields=extra))
        assert r.status_code == 201, r.text
        cfg = r.json()["card"]["config"]
        assert cfg["gauge_color"] == "#4caf50"
        assert cfg["gauge_color_darkmode"] == "#81c784"
        _delete_card(sess, csrf, r.json()["card"]["id"])

    def test_link_round_trip(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        extra = "link: /budget/expenses/?search=type%3Dexpense"
        r = _post_card(sess, csrf, _gauge_yaml(max_value=200, extra_fields=extra))
        assert r.status_code == 201, r.text
        assert r.json()["card"]["config"]["link"] == "/budget/expenses/?search=type%3Dexpense"
        _delete_card(sess, csrf, r.json()["card"]["id"])

    @pytest.mark.parametrize("show_raw,show_pct", [
        (True, True), (True, False), (False, True), (False, False),
    ])
    def test_show_flags_independent(self, driver, w, ctx, sess, show_raw, show_pct):
        csrf = _csrf(sess)
        extra = f"show_raw_values: {str(show_raw).lower()}\nshow_percent: {str(show_pct).lower()}"
        r = _post_card(sess, csrf, _gauge_yaml(max_value=200, extra_fields=extra))
        assert r.status_code == 201, r.text
        cfg = r.json()["card"]["config"]
        assert cfg["show_raw_values"] is show_raw
        assert cfg["show_percent"] is show_pct
        _delete_card(sess, csrf, r.json()["card"]["id"])

    def test_show_flags_default_to_true_when_omitted(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _gauge_yaml(max_value=200))
        assert r.status_code == 201, r.text
        cfg = r.json()["card"]["config"]
        assert cfg["show_raw_values"] is True
        assert cfg["show_percent"] is True
        _delete_card(sess, csrf, r.json()["card"]["id"])


class TestGaugeData:

    def test_fixed_max_percent_computation(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        e1 = api_post("/api/v1/expenses/", ctx, json={
            "title": "GaugeFixed1", "type": "expense", "value": "50.00",
            "date_due": today, "settled": True,
        })
        e2 = api_post("/api/v1/expenses/", ctx, json={
            "title": "GaugeFixed2", "type": "expense", "value": "70.00",
            "date_due": today, "settled": True,
        })
        assert e1.status_code == 201
        assert e2.status_code == 201

        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _gauge_yaml(query="GaugeFixed", max_value=200))
        assert r.status_code == 201, r.text
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next(c for c in cards if c["id"] == card_id)
        assert card["data"]["value"] == 120.0
        assert card["data"]["max_value"] == 200.0
        assert pytest.approx(card["data"]["percent"], abs=0.01) == 60.0

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{e1.json()['id']}/", ctx)
        api_delete(f"/api/v1/expenses/{e2.json()['id']}/", ctx)

    def test_dynamic_max_value_query_computation(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        exp = api_post("/api/v1/expenses/", ctx, json={
            "title": "GaugeDynExp", "type": "expense", "value": "120.00",
            "date_due": today, "settled": True,
        })
        inc = api_post("/api/v1/expenses/", ctx, json={
            "title": "GaugeDynInc", "type": "income", "value": "300.00",
            "date_due": today, "settled": True,
        })
        assert exp.status_code == 201
        assert inc.status_code == 201

        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _gauge_yaml(
            query="GaugeDynExp", max_value_query="GaugeDynInc", max_value_method="sum",
        ))
        assert r.status_code == 201, r.text
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next(c for c in cards if c["id"] == card_id)
        assert card["data"]["value"] == 120.0
        assert card["data"]["max_value"] == 300.0
        assert pytest.approx(card["data"]["percent"], abs=0.01) == 40.0

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{exp.json()['id']}/", ctx)
        api_delete(f"/api/v1/expenses/{inc.json()['id']}/", ctx)

    def test_method_count(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        e1 = api_post("/api/v1/expenses/", ctx, json={
            "title": "GaugeCount1", "type": "expense", "value": "1.00",
            "date_due": today, "settled": True,
        })
        e2 = api_post("/api/v1/expenses/", ctx, json={
            "title": "GaugeCount2", "type": "expense", "value": "1.00",
            "date_due": today, "settled": True,
        })
        assert e1.status_code == 201
        assert e2.status_code == 201

        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _gauge_yaml(query="GaugeCount", method="count", max_value=10))
        assert r.status_code == 201, r.text
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next(c for c in cards if c["id"] == card_id)
        assert card["data"]["value"] == 2.0

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{e1.json()['id']}/", ctx)
        api_delete(f"/api/v1/expenses/{e2.json()['id']}/", ctx)

    def test_dynamic_max_zero_is_safe(self, driver, w, ctx, sess):
        """When max_value_query matches nothing, percent must be 0, never a divide-by-zero error."""
        today = server_today()
        year, month = today[:4], today[5:7]
        e = api_post("/api/v1/expenses/", ctx, json={
            "title": "GaugeZeroMax", "type": "expense", "value": "10.00",
            "date_due": today, "settled": True,
        })
        assert e.status_code == 201

        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _gauge_yaml(
            query="GaugeZeroMax",
            max_value_query="NoSuchExpenseTitleEverMatchesThis",
            max_value_method="sum",
        ))
        assert r.status_code == 201, r.text
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next(c for c in cards if c["id"] == card_id)
        assert card["data"]["max_value"] == 0.0
        assert card["data"]["percent"] == 0.0
        assert card["error"] is None

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{e.json()['id']}/", ctx)


class TestGaugeBrowser:

    def test_gauge_svg_renders(self, driver, w, ctx, sess):
        today = server_today()
        e = api_post("/api/v1/expenses/", ctx, json={
            "title": "GaugeBrowserTest", "type": "expense", "value": "33.00",
            "date_due": today, "settled": True,
        })
        assert e.status_code == 201

        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _gauge_yaml(
            query="GaugeBrowserTest", max_value=100,
            extra_fields="show_raw_values: true\nshow_percent: true",
        ))
        assert r.status_code == 201, r.text
        card_id = r.json()["card"]["id"]

        driver.get(_url("/budget/"))
        time.sleep(3)

        has_gauge = driver.execute_script(
            "return document.querySelectorAll('.dash-gauge-svg').length > 0;"
        )
        assert has_gauge, "no .dash-gauge-svg rendered on the dashboard"

        offset = driver.execute_script(
            "const el = document.querySelector('.dash-gauge-value');"
            "return el ? el.getAttribute('stroke-dashoffset') : null;"
        )
        assert offset is not None
        # 33/100 = 33% filled -> dashoffset should be 100 - 33 = 67
        assert pytest.approx(float(offset), abs=0.5) == 67.0

        body_text = driver.execute_script(
            "const el = document.querySelector('.dash-gauge-text');"
            "return el ? el.textContent : '';"
        )
        assert "33" in body_text
        assert "100" in body_text
        assert "33%" in body_text

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{e.json()['id']}/", ctx)

    def test_color_breakpoints_compare_against_percent_not_raw_value(self, driver, w, ctx, sess):
        """
        Regression test: gauge color_breakpoints must compare against percent-of-max,
        not the raw value. max_value=10, spent=6.3 -> percent=63%.
        Against percent: less_than:100 matches (63<100) -> amber; less_than:10 does NOT
        (63 is not <10) -> stays amber.
        Against raw value (the bug): less_than:100 AND less_than:10 both match
        (6.3<100 and 6.3<10) -> last one wins -> green. These are distinguishable colors,
        so this pins down which comparison basis is actually in effect.
        """
        today = server_today()
        e = api_post("/api/v1/expenses/", ctx, json={
            "title": "GaugePercentBreakpoint", "type": "expense", "value": "6.30",
            "date_due": today, "settled": True,
        })
        assert e.status_code == 201

        csrf = _csrf(sess)
        extra = (
            "gauge_color: '#da2525'\n"
            "color_breakpoints:\n"
            "  - less_than: 100\n"
            "    color: '#ffc800'\n"
            "  - less_than: 10\n"
            "    color: '#57a87e'"
        )
        r = _post_card(sess, csrf, _gauge_yaml(
            query="GaugePercentBreakpoint", max_value=10, extra_fields=extra,
        ))
        assert r.status_code == 201, r.text
        card_id = r.json()["card"]["id"]

        driver.get(_url("/budget/"))
        time.sleep(3)

        stroke = driver.execute_script(
            "const el = document.querySelector('.dash-gauge-value');"
            "return el ? el.style.stroke : null;"
        )
        # rgb(255, 200, 0) == #ffc800 (amber); a value-based comparison would give
        # rgb(87, 168, 126) == #57a87e (green) instead.
        assert stroke == "rgb(255, 200, 0)", f"expected amber (percent-based), got {stroke!r}"

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{e.json()['id']}/", ctx)

    def test_cleanup_all_cards(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        cards = sess.get(CARDS_URL).json()["cards"]
        for card in cards:
            _delete_card(sess, csrf, card["id"])
        assert sess.get(CARDS_URL).json()["cards"] == []
