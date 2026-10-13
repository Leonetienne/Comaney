"""
Every API action is defined once as an Operation (handlers in api/operations/). The REST API (/api/v2/)
and the MCP server (/mcp) are both generated from this registry, so they always
share validation, permissions and side effects.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable

READ = "read"
WRITE = "write"

# permission groups an agent key can restrict, in display order
CONCERNS = {
    "expenses":    "Expenses",
    "scheduled":   "Recurring expenses",
    "catalog":     "Categories and tags",
    "dashboard":   "Dashboard",
    "projects":    "Projects",
    "contacts":    "Contacts",
    "approvals":   "Approvals and settlements",
    "partnership": "Catalog partnership",
    "settings":    "Account settings",
}


class OpError(Exception):
    """A rejected call; `status` is the REST status code, the message is shown to the caller."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class NotFound(OpError):
    def __init__(self, what: str = "Not found."):
        super().__init__(what, 404)


class Forbidden(OpError):
    def __init__(self, message: str):
        super().__init__(message, 403)


@dataclass
class Context:
    """Who is calling: the feuser, plus the agent key on MCP calls (None on REST)."""
    feuser: Any
    agent_key: Any = None


@dataclass(frozen=True)
class Operation:
    name: str
    concern: str
    access: str
    method: str
    path: str
    description: str
    handler: Callable[[Context, dict], Any]
    params: dict = field(default_factory=dict)
    required: tuple = ()
    destructive: bool = False
    status: int = 200

    def input_schema(self) -> dict:
        schema = {"type": "object", "properties": self.params, "additionalProperties": False}
        if self.required:
            schema["required"] = list(self.required)
        return schema


REGISTRY: dict[str, Operation] = {}


def operation(name, *, concern, access, method, path, description, params=None, required=(),
              destructive=False, status=200):
    """Register the decorated handler(ctx, args) as an API operation."""
    assert concern in CONCERNS and access in (READ, WRITE)

    def decorator(fn):
        assert name not in REGISTRY, name
        REGISTRY[name] = Operation(
            name=name, concern=concern, access=access, method=method, path=path,
            description=description, handler=fn, params=params or {}, required=tuple(required),
            destructive=destructive, status=status,
        )
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------

def _coerce(name, schema, value, from_query):
    types = schema.get("type")
    types = types if isinstance(types, list) else [types]
    if value is None:
        if "null" in types:
            return None
        raise OpError(f"'{name}' must not be null.")
    if from_query and isinstance(value, str):
        if "integer" in types and value.lstrip("-").isdigit():
            return int(value)
        if "boolean" in types and value.lower() in ("true", "false", "1", "0"):
            return value.lower() in ("true", "1")
    ok = (
        ("string" in types and isinstance(value, str))
        or ("integer" in types and isinstance(value, int) and not isinstance(value, bool))
        or ("number" in types and isinstance(value, (int, float, Decimal)) and not isinstance(value, bool))
        or ("boolean" in types and isinstance(value, bool))
        or ("array" in types and isinstance(value, list))
        or ("object" in types and isinstance(value, dict))
    )
    if not ok:
        readable = " or ".join(t for t in types if t != "null")
        raise OpError(f"'{name}' must be {readable}.")
    if "enum" in schema and value not in schema["enum"]:
        raise OpError(f"'{name}' must be one of: {', '.join(map(str, schema['enum']))}.")
    return value


def validate_args(op: Operation, raw: dict, *, from_query=False, strict=True) -> dict:
    """
    Check top-level argument types, enums and required keys against op.params.
    Query string values are coerced to integer/boolean. With strict, unknown keys are rejected.
    """
    args = {}
    for key, value in raw.items():
        schema = op.params.get(key)
        if schema is None:
            if strict:
                raise OpError(f"Unknown argument '{key}'.")
            continue
        args[key] = _coerce(key, schema, value, from_query)
    missing = [k for k in op.required if k not in args]
    if missing:
        raise OpError(f"Missing required argument '{missing[0]}'.")
    return args


def call(op: Operation, ctx: Context, args: dict):
    return op.handler(ctx, args)
