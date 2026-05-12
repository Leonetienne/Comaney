"""API field-length and choice validation for all resources."""
import pytest

from helpers import api_get, api_post, api_patch, server_today, setup_user, cleanup_user

LONG_128  = "x" * 129
LONG_1024 = "x" * 1025


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestAccountValidation:

    def test_first_name_too_long(self, driver, w, ctx):
        assert api_patch("/api/v1/account/", ctx, json={"first_name": LONG_128}).status_code == 400

    def test_last_name_too_long(self, driver, w, ctx):
        assert api_patch("/api/v1/account/", ctx, json={"last_name": LONG_128}).status_code == 400

    def test_currency_too_long(self, driver, w, ctx):
        assert api_patch("/api/v1/account/", ctx, json={"currency": "TOOLONGVALUE"}).status_code == 400

    def test_month_start_day_too_high(self, driver, w, ctx):
        assert api_patch("/api/v1/account/", ctx, json={"month_start_day": 32}).status_code == 400

    def test_month_start_day_zero(self, driver, w, ctx):
        assert api_patch("/api/v1/account/", ctx, json={"month_start_day": 0}).status_code == 400

    def test_invalid_allowance_action(self, driver, w, ctx):
        assert api_patch("/api/v1/account/", ctx,
                         json={"unspent_allowance_action": "drop_it"}).status_code == 400


class TestCategoryValidation:

    def test_title_too_long(self, driver, w, ctx):
        assert api_post("/api/v1/categories/", ctx, json={"title": LONG_128}).status_code == 400

    def test_patch_title_too_long(self, driver, w, ctx):
        cat = api_post("/api/v1/categories/", ctx, json={"title": "ValCat"}).json()
        assert api_patch(f"/api/v1/categories/{cat['id']}/", ctx,
                         json={"title": LONG_128}).status_code == 400
        api_post("/api/v1/categories/", ctx, json={})  # clean up via user deletion


class TestTagValidation:

    def test_title_too_long(self, driver, w, ctx):
        assert api_post("/api/v1/tags/", ctx, json={"title": LONG_128}).status_code == 400


class TestExpenseValidation:

    def _base(self, **kwargs):
        return {"title": "Val", "type": "expense", "value": "1.00",
                "date_due": server_today(), "settled": True, **kwargs}

    def test_title_too_long(self, driver, w, ctx):
        assert api_post("/api/v1/expenses/", ctx, json=self._base(title=LONG_128)).status_code == 400

    def test_payee_too_long(self, driver, w, ctx):
        assert api_post("/api/v1/expenses/", ctx, json=self._base(payee=LONG_128)).status_code == 400

    def test_note_too_long(self, driver, w, ctx):
        assert api_post("/api/v1/expenses/", ctx, json=self._base(note=LONG_1024)).status_code == 400

    def test_invalid_type(self, driver, w, ctx):
        assert api_post("/api/v1/expenses/", ctx, json=self._base(type="invalid")).status_code == 400

    def test_negative_value(self, driver, w, ctx):
        assert api_post("/api/v1/expenses/", ctx, json=self._base(value="-1.00")).status_code == 400

    def test_missing_required_fields(self, driver, w, ctx):
        assert api_post("/api/v1/expenses/", ctx, json={}).status_code == 400


class TestScheduledValidation:

    def _base(self, **kwargs):
        return {"title": "Val", "type": "expense", "value": "1.00",
                "repeat_every_factor": 1, "repeat_every_unit": "months",
                "repeat_base_date": server_today(), **kwargs}

    def test_title_too_long(self, driver, w, ctx):
        assert api_post("/api/v1/scheduled/", ctx, json=self._base(title=LONG_128)).status_code == 400

    def test_invalid_type(self, driver, w, ctx):
        assert api_post("/api/v1/scheduled/", ctx, json=self._base(type="invalid")).status_code == 400

    def test_invalid_repeat_unit(self, driver, w, ctx):
        assert api_post("/api/v1/scheduled/", ctx,
                        json=self._base(repeat_every_unit="decades")).status_code == 400
