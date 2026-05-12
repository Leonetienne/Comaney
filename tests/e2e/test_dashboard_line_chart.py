"""
Dashboard line chart card: API validation, data computation, and browser smoke test.
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


def _line_yaml(
    method="cum",
    series=None,
    extra_fields="",
    position=50,
    width=6,
    height=3,
) -> str:
    if series is None:
        series = [{"label": "Expenses", "query": "type=expense"}]

    lines = [
        "type: line-chart",
        "title: TestLineChart",
        f"method: {method}",
        "series:",
    ]
    for s in series:
        lines.append(f'  - label: "{s["label"]}"')
        if s.get("query"):
            lines.append(f'    query: "{s["query"]}"')
        if s.get("method"):
            lines.append(f'    method: {s["method"]}')
        if s.get("color"):
            lines.append(f'    color: "{s["color"]}"')
    if extra_fields:
        lines.append(extra_fields)
    lines += [
        "positioning:",
        f"  position: {position}",
        f"  width: {width}",
        f"  height: {height}",
    ]
    return "\n".join(lines) + "\n"


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


class TestLineChartValidation:

    def test_create_line_chart_card(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _line_yaml())
        assert r.status_code == 201, r.text
        card = r.json()["card"]
        assert card["config"]["type"] == "line-chart"
        assert card["config"]["method"] == "cum"
        assert len(card["config"]["series"]) == 1
        _delete_card(sess, csrf, card["id"])

    def test_base_method_accepted(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _line_yaml(method="base"))
        assert r.status_code == 201, r.text
        assert r.json()["card"]["config"]["method"] == "base"
        _delete_card(sess, csrf, r.json()["card"]["id"])

    def test_invalid_card_method_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _line_yaml(method="sum"))
        assert r.status_code == 400

    def test_another_invalid_card_method_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _line_yaml(method="custom"))
        assert r.status_code == 400

    def test_missing_series_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = "type: line-chart\ntitle: NoSeries\nmethod: cum\npositioning:\n  position: 0\n  width: 4\n  height: 2\n"
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 400

    def test_series_without_label_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = (
            "type: line-chart\ntitle: BadSeries\nmethod: cum\n"
            "series:\n  - query: type=expense\n"
            "positioning:\n  position: 0\n  width: 4\n  height: 2\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 400

    def test_invalid_series_method_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _line_yaml(
            series=[{"label": "Bad", "query": "", "method": "count"}],
        ))
        assert r.status_code == 400

    def test_valid_series_methods_accepted(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        for m in ("sum", "total"):
            r = _post_card(sess, csrf, _line_yaml(
                series=[{"label": "S", "query": "type=expense", "method": m}],
            ))
            assert r.status_code == 201, f"series method={m} rejected: {r.text}"
            _delete_card(sess, csrf, r.json()["card"]["id"])

    def test_multiple_series_accepted(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _line_yaml(series=[
            {"label": "Expenses", "query": "type=expense"},
            {"label": "Income",   "query": "type=income"},
        ]))
        assert r.status_code == 201, r.text
        cfg = r.json()["card"]["config"]
        assert len(cfg["series"]) == 2
        assert cfg["series"][0]["label"] == "Expenses"
        assert cfg["series"][1]["label"] == "Income"
        _delete_card(sess, csrf, r.json()["card"]["id"])

    def test_series_color_round_trips(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _line_yaml(
            series=[{"label": "Red", "query": "", "color": "#ff0000"}],
        ))
        assert r.status_code == 201, r.text
        s = r.json()["card"]["config"]["series"][0]
        assert s["color"] == "#ff0000"
        _delete_card(sess, csrf, r.json()["card"]["id"])


class TestLineChartData:

    def test_labels_and_values_have_same_length(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _line_yaml())
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next((c for c in cards if c["id"] == card_id), None)
        assert card is not None
        data = card["data"]
        assert len(data["labels"]) == len(data["series"][0]["values"])

        _delete_card(sess, csrf, card_id)

    def test_labels_are_iso_date_strings(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _line_yaml())
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next((c for c in cards if c["id"] == card_id), None)
        labels = card["data"]["labels"]
        assert len(labels) > 0
        # Each label must be parseable as YYYY-MM-DD
        for lbl in labels:
            parts = lbl.split("-")
            assert len(parts) == 3 and len(parts[0]) == 4

        _delete_card(sess, csrf, card_id)

    def test_cum_values_are_non_decreasing(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        e1 = api_post("/api/v1/expenses/", ctx, json={
            "title": "CumNonDec A", "type": "expense", "value": "10.00",
            "date_due": today, "settled": True,
        })
        e2 = api_post("/api/v1/expenses/", ctx, json={
            "title": "CumNonDec B", "type": "expense", "value": "20.00",
            "date_due": today, "settled": True,
        })
        assert e1.status_code == 201
        assert e2.status_code == 201

        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _line_yaml(method="cum", series=[
            {"label": "CumTest", "query": "CumNonDec"},
        ]))
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next((c for c in cards if c["id"] == card_id), None)
        values = card["data"]["series"][0]["values"]
        # Cumulative: each value >= previous
        for i in range(1, len(values)):
            assert values[i] >= values[i - 1], f"cum dipped at index {i}: {values}"

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{e1.json()['id']}/", ctx)
        api_delete(f"/api/v1/expenses/{e2.json()['id']}/", ctx)

    def test_cum_final_value_equals_total_sum(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        e1 = api_post("/api/v1/expenses/", ctx, json={
            "title": "CumSum1", "type": "expense", "value": "15.00",
            "date_due": today, "settled": True,
        })
        e2 = api_post("/api/v1/expenses/", ctx, json={
            "title": "CumSum2", "type": "expense", "value": "25.00",
            "date_due": today, "settled": True,
        })
        assert e1.status_code == 201
        assert e2.status_code == 201

        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _line_yaml(method="cum", series=[
            {"label": "CumSumTest", "query": "CumSum"},
        ]))
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next((c for c in cards if c["id"] == card_id), None)
        values = card["data"]["series"][0]["values"]
        assert len(values) > 0
        assert pytest.approx(values[-1], abs=0.01) == 40.0

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{e1.json()['id']}/", ctx)
        api_delete(f"/api/v1/expenses/{e2.json()['id']}/", ctx)

    def test_base_values_sum_to_total(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        e1 = api_post("/api/v1/expenses/", ctx, json={
            "title": "BaseVal1", "type": "expense", "value": "7.00",
            "date_due": today, "settled": True,
        })
        e2 = api_post("/api/v1/expenses/", ctx, json={
            "title": "BaseVal2", "type": "expense", "value": "13.00",
            "date_due": today, "settled": True,
        })
        assert e1.status_code == 201
        assert e2.status_code == 201

        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _line_yaml(method="base", series=[
            {"label": "BaseTest", "query": "BaseVal"},
        ]))
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next((c for c in cards if c["id"] == card_id), None)
        values = card["data"]["series"][0]["values"]
        # In base mode, all bucket values sum to the total
        assert pytest.approx(sum(values), abs=0.01) == 20.0

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{e1.json()['id']}/", ctx)
        api_delete(f"/api/v1/expenses/{e2.json()['id']}/", ctx)

    def test_series_method_total_negates_income(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        exp = api_post("/api/v1/expenses/", ctx, json={
            "title": "NetTotal expense", "type": "expense", "value": "100.00",
            "date_due": today, "settled": True,
        })
        inc = api_post("/api/v1/expenses/", ctx, json={
            "title": "NetTotal income", "type": "income", "value": "60.00",
            "date_due": today, "settled": True,
        })
        assert exp.status_code == 201
        assert inc.status_code == 201

        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _line_yaml(
            method="cum",
            series=[{"label": "Net", "query": "NetTotal", "method": "total"}],
        ))
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next((c for c in cards if c["id"] == card_id), None)
        values = card["data"]["series"][0]["values"]
        # expense 100 + income as -60 = 40
        assert pytest.approx(values[-1], abs=0.01) == 40.0

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{exp.json()['id']}/", ctx)
        api_delete(f"/api/v1/expenses/{inc.json()['id']}/", ctx)

    def test_card_level_query_applied_to_all_series(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        # This expense has the title "CardQFilter" but NOT "type=income"
        e_exp = api_post("/api/v1/expenses/", ctx, json={
            "title": "CardQFilter", "type": "expense", "value": "50.00",
            "date_due": today, "settled": True,
        })
        # This expense also has "CardQFilter" in title but is filtered out by card query
        e_inc = api_post("/api/v1/expenses/", ctx, json={
            "title": "CardQFilterInc", "type": "income", "value": "999.00",
            "date_due": today, "settled": True,
        })
        assert e_exp.status_code == 201
        assert e_inc.status_code == 201

        csrf = _csrf(sess)
        yaml_str = (
            "type: line-chart\ntitle: CardQTest\nmethod: cum\n"
            "query: \"type=expense CardQFilter\"\n"
            "series:\n  - label: Exp\npositioning:\n  position: 50\n  width: 6\n  height: 3\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next((c for c in cards if c["id"] == card_id), None)
        values = card["data"]["series"][0]["values"]
        # Only the expense matches; income excluded by card-level query
        assert pytest.approx(values[-1], abs=0.01) == 50.0

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{e_exp.json()['id']}/", ctx)
        api_delete(f"/api/v1/expenses/{e_inc.json()['id']}/", ctx)

    def test_flip_signs_per_series_negates_that_series(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        e = api_post("/api/v1/expenses/", ctx, json={
            "title": "FlipLine", "type": "expense", "value": "45.00",
            "date_due": today, "settled": True,
        })
        assert e.status_code == 201

        csrf = _csrf(sess)
        yaml_str = (
            "type: line-chart\ntitle: FlipTest\nmethod: cum\n"
            "series:\n"
            "  - label: Flipped\n    query: FlipLine\n    flip_signs: true\n"
            "  - label: Normal\n    query: FlipLine\n"
            "positioning:\n  position: 50\n  width: 6\n  height: 3\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next((c for c in cards if c["id"] == card_id), None)
        flipped = card["data"]["series"][0]["values"]
        normal  = card["data"]["series"][1]["values"]
        assert pytest.approx(flipped[-1], abs=0.01) == -45.0
        assert pytest.approx(normal[-1],  abs=0.01) ==  45.0

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{e.json()['id']}/", ctx)

    def test_empty_period_returns_empty_labels(self, driver, w, ctx, sess):
        # Use a far-future year where no expenses exist
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _line_yaml())
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": "2099", "month": "1"}).json()["cards"]
        card = next((c for c in cards if c["id"] == card_id), None)
        assert card is not None
        # No data in 2099, so labels list should be empty (cutoff = min(p_end, today) < p_start)
        assert card["data"]["labels"] == []
        assert card["data"]["series"] == []

        _delete_card(sess, csrf, card_id)


class TestLineChartBrowser:

    def test_line_chart_canvas_renders(self, driver, w, ctx, sess):
        today = server_today()
        e = api_post("/api/v1/expenses/", ctx, json={
            "title": "LineChartBrowser", "type": "expense", "value": "33.00",
            "date_due": today, "settled": True,
        })
        assert e.status_code == 201

        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _line_yaml(series=[
            {"label": "Browser", "query": "LineChartBrowser"},
        ]))
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        driver.get(_url("/budget/"))
        time.sleep(3)

        canvases = driver.execute_script(
            "return Array.from(document.querySelectorAll('canvas[id]'))"
            ".map(el => el.id);"
        )
        assert f"chart-{card_id}" in canvases, f"canvas#chart-{card_id} not found; canvases={canvases}"

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{e.json()['id']}/", ctx)

    def test_cleanup_all_cards(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        cards = sess.get(CARDS_URL).json()["cards"]
        for card in cards:
            _delete_card(sess, csrf, card["id"])
        assert sess.get(CARDS_URL).json()["cards"] == []
