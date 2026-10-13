"""
REST API v2 for the dashboard side: dashboards CRUD, cards CRUD with YAML
validation, the card reference endpoint, and foreign-resource rejection.
Run with: pytest -v tests/e2e/api/test_api_dashboards.py | tee logfile.log
"""
import pytest

from helpers import api_get, api_post, api_patch, api_delete, setup_user, cleanup_user

CELL_YAML = "type: cell\ntitle: API Cell\nmethod: sum\n"
RENAMED_CELL_YAML = "type: cell\ntitle: API Cell Renamed\nmethod: sum\n"


@pytest.fixture(scope="module")
def ctx():
    c = setup_user(None, None)
    yield c
    cleanup_user(c["email"])


class TestApiDashboards:

    def test_list_starts_with_default(self, ctx):
        data = api_get("/api/v2/dashboards/", ctx).json()
        assert len(data["dashboards"]) == 1
        assert data["dashboards"][0]["title"] == "Dashboard"
        ctx["default_id"] = data["dashboards"][0]["id"]

    def test_create(self, ctx):
        resp = api_post("/api/v2/dashboards/", ctx, {"title": "API Dash"})
        assert resp.status_code == 201
        data = resp.json()
        ctx["dash2"] = data["id"]
        assert data["title"] == "API Dash"
        assert data["sorting"] == 1

    def test_list_order(self, ctx):
        ids = [d["id"] for d in api_get("/api/v2/dashboards/", ctx).json()["dashboards"]]
        assert ids == [ctx["default_id"], ctx["dash2"]]

    def test_update(self, ctx):
        resp = api_patch(f"/api/v2/dashboards/{ctx['dash2']}/", ctx, {"title": "API Dash Renamed"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "API Dash Renamed"

    def test_update_requires_title(self, ctx):
        resp = api_patch(f"/api/v2/dashboards/{ctx['dash2']}/", ctx, {})
        assert resp.status_code == 400

    def test_delete(self, ctx):
        resp = api_delete(f"/api/v2/dashboards/{ctx['dash2']}/", ctx)
        assert resp.status_code == 204
        ids = [d["id"] for d in api_get("/api/v2/dashboards/", ctx).json()["dashboards"]]
        assert ids == [ctx["default_id"]]

    def test_last_dashboard_cannot_be_deleted(self, ctx):
        resp = api_delete(f"/api/v2/dashboards/{ctx['default_id']}/", ctx)
        assert resp.status_code == 409
        assert "only dashboard" in resp.json()["error"]

    def test_foreign_dashboard_not_found(self, ctx):
        other = setup_user(None, None)
        try:
            other_id = api_get("/api/v2/dashboards/", other).json()["dashboards"][0]["id"]
            resp = api_patch(f"/api/v2/dashboards/{other_id}/", ctx, {"title": "Stolen"})
            assert resp.status_code == 404
        finally:
            cleanup_user(other["email"])


class TestApiCards:

    def test_reference(self, ctx):
        data = api_get("/api/v2/cards/reference/", ctx).json()
        ref = data["reference"]
        assert isinstance(ref, str) and len(ref) > 100
        assert "type: cell" in ref and "bar-chart" in ref

    def test_list_defaults_to_first_dashboard(self, ctx):
        data = api_get("/api/v2/cards/", ctx).json()
        assert data["dashboard_id"] == ctx["default_id"]
        assert len(data["cards"]) >= 1
        assert all(c["error"] is None for c in data["cards"])

    def test_create(self, ctx):
        resp = api_post("/api/v2/cards/", ctx, {"yaml_config": CELL_YAML})
        assert resp.status_code == 201
        card = resp.json()
        ctx["card_id"] = card["id"]
        assert card["error"] is None
        assert card["config"]["type"] == "cell"
        assert card["config"]["title"] == "API Cell"

    def test_create_rejects_invalid_yaml(self, ctx):
        resp = api_post("/api/v2/cards/", ctx, {"yaml_config": "type: not_a_valid_type\ntitle: Bad\n"})
        assert resp.status_code == 400

    def test_create_requires_yaml(self, ctx):
        resp = api_post("/api/v2/cards/", ctx, {})
        assert resp.status_code == 400

    def test_list_contains_new_card(self, ctx):
        cards = api_get("/api/v2/cards/", ctx).json()["cards"]
        assert any(c["id"] == ctx["card_id"] for c in cards)

    def test_update_replaces_yaml(self, ctx):
        resp = api_patch(f"/api/v2/cards/{ctx['card_id']}/", ctx, {"yaml_config": RENAMED_CELL_YAML})
        assert resp.status_code == 200
        assert resp.json()["config"]["title"] == "API Cell Renamed"

    def test_update_requires_yaml_or_dashboard(self, ctx):
        resp = api_patch(f"/api/v2/cards/{ctx['card_id']}/", ctx, {})
        assert resp.status_code == 400

    def test_update_moves_card_to_other_dashboard(self, ctx):
        dash = api_post("/api/v2/dashboards/", ctx, {"title": "Card Target"}).json()
        resp = api_patch(f"/api/v2/cards/{ctx['card_id']}/", ctx, {"dashboard_id": dash["id"]})
        assert resp.status_code == 200
        assert resp.json()["dashboard_id"] == dash["id"]
        moved = api_get("/api/v2/cards/", ctx, params={"dashboard_id": dash["id"]}).json()["cards"]
        assert [c["id"] for c in moved] == [ctx["card_id"]]
        first = api_get("/api/v2/cards/", ctx).json()["cards"]
        assert ctx["card_id"] not in [c["id"] for c in first]

    def test_delete(self, ctx):
        resp = api_delete(f"/api/v2/cards/{ctx['card_id']}/", ctx)
        assert resp.status_code == 204

    def test_foreign_card_not_found(self, ctx):
        other = setup_user(None, None)
        try:
            other_card = api_post("/api/v2/cards/", other, {"yaml_config": CELL_YAML}).json()["id"]
            resp = api_patch(f"/api/v2/cards/{other_card}/", ctx, {"yaml_config": RENAMED_CELL_YAML})
            assert resp.status_code == 404
        finally:
            cleanup_user(other["email"])
