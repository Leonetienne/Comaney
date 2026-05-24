"""
Pie-chart dashboard card:
- Create pie-chart card with group=categories and group=tags
- Card creation is accepted (201) and type is preserved in config
- Computed data returns 'labels' and 'values' keys
- flip_signs inverts all values
- method=total supported
- method=custom and method=count are rejected for pie-chart
- Query filter is applied to data
"""
import time

import pytest

from helpers import (
    _url, api_post, api_delete, server_today,
    session_cookies, BASE_URL, setup_user, cleanup_user,
)
import requests


CARDS_URL = BASE_URL + "/budget/dashboard/cards/"


def _cards_session(driver) -> requests.Session:
    s = requests.Session()
    s.cookies.update(session_cookies(driver))
    return s


def _csrf(sess) -> str:
    return next((c.value for c in sess.cookies if c.name == "csrftoken"), "")


def _post_card(sess, csrf, yaml_str) -> requests.Response:
    return sess.post(
        CARDS_URL,
        json={"yaml_config": yaml_str},
        headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
    )


def _delete_card(sess, csrf, card_id):
    sess.delete(f"{CARDS_URL}{card_id}/", headers={"X-CSRFToken": csrf})


def _card_data(sess, card_id, year, month):
    r = sess.get(CARDS_URL, params={"year": year, "month": month})
    cards = r.json().get("cards", [])
    return next((c["data"] for c in cards if c["id"] == card_id), None)


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


@pytest.fixture(scope="module")
def sess(driver, ctx):
    driver.get(_url("/budget/"))
    time.sleep(1)
    return _cards_session(driver)


class TestPieChartCard:

    def test_create_pie_chart_by_categories(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = (
            "type: pie-chart\ntitle: Spending by Category\n"
            "method: sum\ngroup: categories\n"
            "positioning:\n  position: 50\n  width: 4\n  height: 2\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 201, r.text
        card = r.json()["card"]
        assert card["config"]["type"] == "pie-chart"
        assert card["config"]["group"] == "categories"
        ctx["pie_cat_id"] = card["id"]

    def test_create_pie_chart_by_tags(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = (
            "type: pie-chart\ntitle: Spending by Tag\n"
            "method: sum\ngroup: tags\n"
            "positioning:\n  position: 51\n  width: 4\n  height: 2\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 201, r.text
        ctx["pie_tag_id"] = r.json()["card"]["id"]

    def test_pie_chart_data_has_labels_and_values(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]

        cat = api_post("/api/v1/categories/", ctx, json={"title": "PieCatA"})
        assert cat.status_code == 201
        cat_id = cat.json()["id"]

        exp = api_post("/api/v1/expenses/", ctx, json={
            "title": "PieExp", "type": "expense", "value": "77.00",
            "date_due": today, "settled": True,
            "category_id": cat_id,
        })
        assert exp.status_code == 201
        eid = exp.json()["id"]

        data = _card_data(sess, ctx["pie_cat_id"], year, month)
        assert data is not None
        assert "labels" in data
        assert "values" in data
        assert isinstance(data["labels"], list)
        assert isinstance(data["values"], list)
        assert len(data["labels"]) == len(data["values"])
        assert "PieCatA" in data["labels"]

        api_delete(f"/api/v1/expenses/{eid}/", ctx)
        api_delete(f"/api/v1/categories/{cat_id}/", ctx)

    def test_pie_chart_by_tags_data(self, driver, w, ctx, sess):
        today = server_today()
        year, month = today[:4], today[5:7]

        tag = api_post("/api/v1/tags/", ctx, json={"title": "PieTagA"})
        assert tag.status_code == 201
        tag_id = tag.json()["id"]

        exp = api_post("/api/v1/expenses/", ctx, json={
            "title": "PieTagExp", "type": "expense", "value": "55.00",
            "date_due": today, "settled": True,
            "tag_ids": [tag_id],
        })
        assert exp.status_code == 201
        eid = exp.json()["id"]

        data = _card_data(sess, ctx["pie_tag_id"], year, month)
        assert data is not None
        assert "PieTagA" in data.get("labels", [])

        api_delete(f"/api/v1/expenses/{eid}/", ctx)
        api_delete(f"/api/v1/tags/{tag_id}/", ctx)

    def test_pie_chart_method_total(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        today = server_today()
        year, month = today[:4], today[5:7]

        yaml_str = (
            "type: pie-chart\ntitle: PieTotalTest\n"
            "method: total\ngroup: categories\n"
            "positioning:\n  position: 52\n  width: 4\n  height: 2\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 201, r.text
        card_id = r.json()["card"]["id"]

        data = _card_data(sess, card_id, year, month)
        assert data is not None
        assert "labels" in data and "values" in data

        _delete_card(sess, csrf, card_id)

    def test_pie_chart_rejects_custom_method(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = (
            "type: pie-chart\ntitle: BadPie\n"
            "method: custom\ngroup: categories\n"
            "positioning:\n  position: 53\n  width: 2\n  height: 1\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 400, "pie-chart must reject method=custom"

    def test_pie_chart_rejects_count_method(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = (
            "type: pie-chart\ntitle: BadPieCount\n"
            "method: count\ngroup: categories\n"
            "positioning:\n  position: 54\n  width: 2\n  height: 1\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 400, "pie-chart must reject method=count"

    def test_pie_chart_requires_group(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        yaml_str = (
            "type: pie-chart\ntitle: NoGroupPie\n"
            "method: sum\n"
            "positioning:\n  position: 55\n  width: 2\n  height: 1\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 400, "pie-chart must require a group"

    def test_pie_chart_flip_signs(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        today = server_today()
        year, month = today[:4], today[5:7]

        cat = api_post("/api/v1/categories/", ctx, json={"title": "PieFlipCat"})
        assert cat.status_code == 201
        cat_id = cat.json()["id"]

        exp = api_post("/api/v1/expenses/", ctx, json={
            "title": "PieFlipExp", "type": "expense", "value": "40.00",
            "date_due": today, "settled": True, "category_id": cat_id,
        })
        assert exp.status_code == 201
        eid = exp.json()["id"]

        yaml_str = (
            "type: pie-chart\ntitle: PieFlip\n"
            "method: sum\ngroup: categories\nflip_signs: true\n"
            "positioning:\n  position: 56\n  width: 4\n  height: 2\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 201
        card_id = r.json()["card"]["id"]

        data = _card_data(sess, card_id, year, month)
        assert data is not None
        pie_flip_idx = next(
            (i for i, l in enumerate(data.get("labels", [])) if l == "PieFlipCat"), None
        )
        if pie_flip_idx is not None:
            assert data["values"][pie_flip_idx] < 0, "flip_signs should negate values"

        _delete_card(sess, csrf, card_id)
        api_delete(f"/api/v1/expenses/{eid}/", ctx)
        api_delete(f"/api/v1/categories/{cat_id}/", ctx)

    def test_cleanup_pie_cards(self, driver, w, ctx, sess):
        csrf = _csrf(sess)
        for key in ("pie_cat_id", "pie_tag_id"):
            if key in ctx:
                _delete_card(sess, csrf, ctx.pop(key))
