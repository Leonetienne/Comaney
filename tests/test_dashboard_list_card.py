"""
Dashboard list card: API CRUD, validation, data computation, ordering, sum row,
type colours, and a browser smoke test.
"""
import time

import requests
import pytest
from selenium.webdriver.common.by import By

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


def _list_yaml(**overrides) -> str:
    fields = {
        "type": "list",
        "title": "TestList",
        "query": "type=expense",
        "order_by": "date",
        "order_dir": "desc",
        "positioning_position": 50,
        "positioning_width": 4,
        "positioning_height": 3,
    }
    fields.update(overrides)
    lines = [
        f"type: {fields['type']}",
        f"title: {fields['title']}",
    ]
    if fields.get("query"):
        lines.append(f"query: \"{fields['query']}\"")
    if fields.get("order_by"):
        lines.append(f"order_by: {fields['order_by']}")
    if fields.get("order_dir"):
        lines.append(f"order_dir: {fields['order_dir']}")
    for extra in ("show_sum", "method", "flip_signs", "type_colors", "sum_template"):
        if extra in fields:
            lines.append(f"{extra}: {fields[extra]}")
    lines += [
        "positioning:",
        f"  position: {fields['positioning_position']}",
        f"  width: {fields['positioning_width']}",
        f"  height: {fields['positioning_height']}",
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


class TestListCardValidation:

    def test_create_list_card(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _list_yaml())
        assert r.status_code == 201, r.text
        card = r.json()["card"]
        assert card["config"]["type"] == "list"
        assert card["config"]["order_by"] == "date"
        assert card["config"]["order_dir"] == "desc"
        _delete_card(sess, csrf, card["id"])

    def test_invalid_order_by_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = _list_yaml(order_by="payee")
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 400

    def test_invalid_order_dir_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = _list_yaml(order_dir="random")
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 400

    def test_invalid_method_rejected(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = _list_yaml(show_sum=True, method="custom")
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 400

    def test_valid_methods_accepted(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        for method in ("sum", "total", "count"):
            yaml_str = _list_yaml(show_sum=True, method=method)
            r = _post_card(sess, csrf, yaml_str)
            assert r.status_code == 201, f"method={method} should be accepted: {r.text}"
            _delete_card(sess, csrf, r.json()["card"]["id"])

    def test_all_order_by_values_accepted(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        for ob in ("value", "date", "title"):
            r = _post_card(sess, csrf, _list_yaml(order_by=ob))
            assert r.status_code == 201, f"order_by={ob} rejected: {r.text}"
            _delete_card(sess, csrf, r.json()["card"]["id"])

    def test_config_fields_round_trip(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = _list_yaml(
            order_by="value",
            order_dir="asc",
            show_sum=True,
            method="count",
            type_colors=False,
            sum_template="$VALUE orders",
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 201, r.text
        cfg = r.json()["card"]["config"]
        assert cfg["order_by"] == "value"
        assert cfg["order_dir"] == "asc"
        assert cfg["show_sum"] is True
        assert cfg["method"] == "count"
        assert cfg["type_colors"] is False
        assert cfg["sum_template"] == "$VALUE orders"
        _delete_card(sess, csrf, r.json()["card"]["id"])


class TestListCardData:

    def test_items_returned(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        e1 = api_post("/api/v1/expenses/", ctx, json={
            "title": "List Item A", "type": "expense", "value": "10.00",
            "date_due": today, "settled": True,
        })
        e2 = api_post("/api/v1/expenses/", ctx, json={
            "title": "List Item B", "type": "expense", "value": "20.00",
            "date_due": today, "settled": True,
        })
        assert e1.status_code == 201
        assert e2.status_code == 201

        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _list_yaml(query="type=expense"))
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next((c for c in cards if c["id"] == card_id), None)
        assert card is not None
        items = card["data"].get("items", [])
        titles = [i["title"] for i in items]
        assert "List Item A" in titles
        assert "List Item B" in titles

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{e1.json()['id']}/", ctx)
        api_delete(f"/api/v1/expenses/{e2.json()['id']}/", ctx)

    def test_items_have_type_title_value(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        e = api_post("/api/v1/expenses/", ctx, json={
            "title": "TypeCheck Expense", "type": "expense", "value": "77.00",
            "date_due": today, "settled": True,
        })
        assert e.status_code == 201

        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _list_yaml(query="TypeCheck"))
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next((c for c in cards if c["id"] == card_id), None)
        items = card["data"].get("items", [])
        item = next((i for i in items if i["title"] == "TypeCheck Expense"), None)
        assert item is not None
        assert item["type"] == "expense"
        assert float(item["value"]) == pytest.approx(77.0)

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{e.json()['id']}/", ctx)

    def test_order_by_value_desc(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        e1 = api_post("/api/v1/expenses/", ctx, json={
            "title": "Ord Small", "type": "expense", "value": "5.00",
            "date_due": today, "settled": True,
        })
        e2 = api_post("/api/v1/expenses/", ctx, json={
            "title": "Ord Large", "type": "expense", "value": "100.00",
            "date_due": today, "settled": True,
        })
        assert e1.status_code == 201
        assert e2.status_code == 201

        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _list_yaml(
            query="Ord",
            order_by="value",
            order_dir="desc",
        ))
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next((c for c in cards if c["id"] == card_id), None)
        items = card["data"].get("items", [])
        relevant = [i for i in items if i["title"] in ("Ord Small", "Ord Large")]
        assert len(relevant) == 2
        assert relevant[0]["title"] == "Ord Large"
        assert relevant[1]["title"] == "Ord Small"

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{e1.json()['id']}/", ctx)
        api_delete(f"/api/v1/expenses/{e2.json()['id']}/", ctx)

    def test_order_by_value_asc(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        e1 = api_post("/api/v1/expenses/", ctx, json={
            "title": "AscSmall", "type": "expense", "value": "3.00",
            "date_due": today, "settled": True,
        })
        e2 = api_post("/api/v1/expenses/", ctx, json={
            "title": "AscLarge", "type": "expense", "value": "99.00",
            "date_due": today, "settled": True,
        })
        assert e1.status_code == 201
        assert e2.status_code == 201

        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _list_yaml(
            query="Asc",
            order_by="value",
            order_dir="asc",
        ))
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next((c for c in cards if c["id"] == card_id), None)
        items = card["data"].get("items", [])
        relevant = [i for i in items if i["title"] in ("AscSmall", "AscLarge")]
        assert len(relevant) == 2
        assert relevant[0]["title"] == "AscSmall"
        assert relevant[1]["title"] == "AscLarge"

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{e1.json()['id']}/", ctx)
        api_delete(f"/api/v1/expenses/{e2.json()['id']}/", ctx)

    def test_show_sum_not_present_by_default(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        e = api_post("/api/v1/expenses/", ctx, json={
            "title": "NoSum Expense", "type": "expense", "value": "40.00",
            "date_due": today, "settled": True,
        })
        assert e.status_code == 201

        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _list_yaml(query="NoSum"))
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next((c for c in cards if c["id"] == card_id), None)
        assert "sum_value" not in (card["data"] or {})

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{e.json()['id']}/", ctx)

    def test_show_sum_method_sum(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        e1 = api_post("/api/v1/expenses/", ctx, json={
            "title": "SumRow A", "type": "expense", "value": "30.00",
            "date_due": today, "settled": True,
        })
        e2 = api_post("/api/v1/expenses/", ctx, json={
            "title": "SumRow B", "type": "expense", "value": "20.00",
            "date_due": today, "settled": True,
        })
        assert e1.status_code == 201
        assert e2.status_code == 201

        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _list_yaml(query="SumRow", show_sum=True, method="sum"))
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next((c for c in cards if c["id"] == card_id), None)
        assert card is not None
        assert float(card["data"]["sum_value"]) == pytest.approx(50.0)

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{e1.json()['id']}/", ctx)
        api_delete(f"/api/v1/expenses/{e2.json()['id']}/", ctx)

    def test_show_sum_method_count(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        e1 = api_post("/api/v1/expenses/", ctx, json={
            "title": "CntRow X", "type": "expense", "value": "11.00",
            "date_due": today, "settled": True,
        })
        e2 = api_post("/api/v1/expenses/", ctx, json={
            "title": "CntRow Y", "type": "expense", "value": "22.00",
            "date_due": today, "settled": True,
        })
        assert e1.status_code == 201
        assert e2.status_code == 201

        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _list_yaml(query="CntRow", show_sum=True, method="count"))
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next((c for c in cards if c["id"] == card_id), None)
        assert float(card["data"]["sum_value"]) == pytest.approx(2.0)

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{e1.json()['id']}/", ctx)
        api_delete(f"/api/v1/expenses/{e2.json()['id']}/", ctx)

    def test_show_sum_method_total(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        exp = api_post("/api/v1/expenses/", ctx, json={
            "title": "TotalRow Exp", "type": "expense", "value": "80.00",
            "date_due": today, "settled": True,
        })
        inc = api_post("/api/v1/expenses/", ctx, json={
            "title": "TotalRow Inc", "type": "income", "value": "50.00",
            "date_due": today, "settled": True,
        })
        assert exp.status_code == 201
        assert inc.status_code == 201

        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _list_yaml(query="TotalRow", show_sum=True, method="total"))
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next((c for c in cards if c["id"] == card_id), None)
        # expense (80) + income as negative (-50) = 30
        assert float(card["data"]["sum_value"]) == pytest.approx(30.0)

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{exp.json()['id']}/", ctx)
        api_delete(f"/api/v1/expenses/{inc.json()['id']}/", ctx)

    def test_flip_signs_inverts_sum(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        e = api_post("/api/v1/expenses/", ctx, json={
            "title": "FlipList Exp", "type": "expense", "value": "60.00",
            "date_due": today, "settled": True,
        })
        assert e.status_code == 201

        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _list_yaml(
            query="FlipList",
            show_sum=True,
            method="sum",
            flip_signs=True,
        ))
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next((c for c in cards if c["id"] == card_id), None)
        assert float(card["data"]["sum_value"]) == pytest.approx(-60.0)

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{e.json()['id']}/", ctx)

    def test_empty_list_returns_empty_items(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]
        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _list_yaml(query="xyzNonExistentTitle99"))
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        cards = sess.get(CARDS_URL, params={"year": year, "month": month}).json()["cards"]
        card = next((c for c in cards if c["id"] == card_id), None)
        assert card["data"]["items"] == []
        _delete_card(sess, csrf, card_id)


class TestListCardBrowser:

    def test_list_card_renders_in_browser(self, driver, w, ctx, sess):
        """Create a list card with a known expense, verify rows appear in the UI."""
        today = server_today()
        e = api_post("/api/v1/expenses/", ctx, json={
            "title": "BrowserListItem", "type": "expense", "value": "42.00",
            "date_due": today, "settled": True,
        })
        assert e.status_code == 201

        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _list_yaml(query="BrowserListItem"))
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        driver.get(_url("/budget/"))
        time.sleep(3)

        src = driver.page_source
        assert "BrowserListItem" in src

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{e.json()['id']}/", ctx)

    def test_list_card_type_abbr_visible(self, driver, w, ctx, sess):
        """Type abbreviation EX should appear in the list row."""
        today = server_today()
        e = api_post("/api/v1/expenses/", ctx, json={
            "title": "AbbrCheckItem", "type": "expense", "value": "15.00",
            "date_due": today, "settled": True,
        })
        assert e.status_code == 201

        csrf = _csrf(sess)
        r = _post_card(sess, csrf, _list_yaml(query="AbbrCheckItem"))
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        driver.get(_url("/budget/"))
        time.sleep(3)

        abbrs = driver.execute_script(
            "return Array.from(document.querySelectorAll('.dash-list-type'))"
            ".map(el => el.textContent.trim());"
        )
        assert "EX" in abbrs

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{e.json()['id']}/", ctx)

    def test_cleanup_all_cards(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        cards = sess.get(CARDS_URL).json()["cards"]
        for card in cards:
            _delete_card(sess, csrf, card["id"])
        assert sess.get(CARDS_URL).json()["cards"] == []
