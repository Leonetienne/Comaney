"""
api/registry.py argument validation and api/permissions.py, both Django-free.
Run with: venv/bin/pytest tests/unit/test_api_registry.py -v
"""
import pytest

from api.registry import CONCERNS, READ, WRITE, Operation, OpError, validate_args
from api import permissions


def _op(params, required=()):
    return Operation(
        name="t", concern="expenses", access=READ, method="GET", path="t/",
        description="", handler=lambda ctx, args: args, params=params, required=tuple(required),
    )


class TestValidateArgs:

    def test_query_strings_become_integers_and_booleans(self):
        op = _op({"id": {"type": "integer"}, "flag": {"type": "boolean"}})
        assert validate_args(op, {"id": "12", "flag": "true"}, from_query=True) == {"id": 12, "flag": True}

    def test_body_strings_stay_strings(self):
        op = _op({"id": {"type": "integer"}})
        with pytest.raises(OpError, match="'id' must be integer"):
            validate_args(op, {"id": "12"})

    def test_bool_is_not_an_integer(self):
        with pytest.raises(OpError):
            validate_args(_op({"id": {"type": "integer"}}), {"id": True})

    def test_enum(self):
        op = _op({"kind": {"type": "string", "enum": ["a", "b"]}})
        with pytest.raises(OpError, match="one of: a, b"):
            validate_args(op, {"kind": "c"})

    def test_nullable(self):
        op = _op({"cat": {"type": ["integer", "null"]}})
        assert validate_args(op, {"cat": None}) == {"cat": None}
        with pytest.raises(OpError, match="must not be null"):
            validate_args(_op({"cat": {"type": "integer"}}), {"cat": None})

    def test_required(self):
        with pytest.raises(OpError, match="Missing required argument 'id'"):
            validate_args(_op({"id": {"type": "integer"}}, required=["id"]), {})

    def test_unknown_rejected_when_strict_ignored_otherwise(self):
        op = _op({"id": {"type": "integer"}})
        with pytest.raises(OpError, match="Unknown argument 'x'"):
            validate_args(op, {"x": 1})
        assert validate_args(op, {"x": 1}, strict=False) == {}

    def test_input_schema(self):
        schema = _op({"id": {"type": "integer"}}, required=["id"]).input_schema()
        assert schema == {
            "type": "object", "properties": {"id": {"type": "integer"}},
            "additionalProperties": False, "required": ["id"],
        }


class TestPermissions:

    def test_full_permissions_cover_every_concern(self):
        perms = permissions.full_permissions(CONCERNS)
        assert all(permissions.allows(perms, c, WRITE) for c in CONCERNS)

    def test_write_implies_read(self):
        perms = permissions.normalize({"expenses": {"write": True}}, CONCERNS)
        assert perms["expenses"] == {"read": True, "write": True}
        assert permissions.allows(perms, "expenses", READ)

    def test_missing_concern_is_off(self):
        perms = permissions.normalize({"expenses": {"read": True}}, CONCERNS)
        assert not permissions.allows(perms, "projects", READ)
        assert not permissions.allows(perms, "expenses", WRITE)

    def test_unknown_concerns_are_dropped(self):
        assert "admin" not in permissions.normalize({"admin": {"read": True}}, CONCERNS)

    def test_from_form(self):
        perms = permissions.from_form({"write_contacts": "on", "read_expenses": "on"}, CONCERNS)
        assert perms["contacts"] == {"read": True, "write": True}
        assert perms["expenses"] == {"read": True, "write": False}
        assert perms["projects"] == {"read": False, "write": False}
