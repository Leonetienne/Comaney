"""POST /mcp: the MCP server, built per request from the registry and the caller's agent key."""
import json
import logging
from datetime import timedelta
from urllib.parse import urlparse

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from api import permissions
from api.operations import CONCERNS, READ, REGISTRY, Context, OpError, validate_args

from . import docs
from .models import AgentKey, hash_key
from .protocol import Resource, Server, Tool, ToolError

_log = logging.getLogger(__name__)

SERVER_NAME = "comaney"
CARDS_REFERENCE_URI = "comaney://reference/dashboard-cards"
_LAST_USED_RESOLUTION = timedelta(minutes=1)

INSTRUCTIONS = """\
You are connected to Comaney, a personal budgeting app, acting as one of its users ("the feuser").

How Comaney works:
- Every expense has one owner. Expenses can be shared with a contact or inside a project; the other people are participants. \
A foreign expense is one the feuser participates in but does not own; they classify it with their own category, tags and note (an overlay).
- Types: expense, income, savings_dep, savings_wit. Amounts are in the feuser's currency (account_get).
- Periods follow the feuser's financial month, which may start on any day; most tools default to the current financial month. \
Use date_from/date_to for other ranges, view=year for a whole financial year.
- Use the query language in q (payee=, cat=, tag=, project=, value>, date>=, ||, !) to find expenses; expenses_totals sums them.
- Shared expenses, invitations and settlements notify other people by email. Settlements only record that money moved.
- Expenses and recurring expenses have a record id; use it to tell records apart in tool calls (q accepts uid=<id> or #<id>).

How to behave:
- Before explaining how a feature works, why it exists, or answering a support question, look it up in the user manual \
with docs_search and docs_read and link the page you used. Do not guess about features.
- Before writing a dashboard card, read the card reference (cards_reference).
- Bulk deletes and joining a Catalog Partnership are two-step: call once to get a preview and a confirm_token, show the \
user what will happen, and only repeat the call with the token after they agree.
- Ask the user before deleting anything and before actions that contact other people.
- Tools the key may not use are not listed. If the user wants something that needs one, tell them to widen this agent \
key's permissions in Settings, Advanced, Agent keys.
"""


RECORD_IDS_SHOWN = (
    "- The feuser has record IDs switched on, so you may show them as #<id> (e.g. #123) and they can search for them."
)
RECORD_IDS_HIDDEN = (
    "- The feuser has record IDs switched off: never show ids to the user, name records by title, date and amount. "
    "They can switch IDs on in Settings, Advanced; account_get's show_record_ids tells the current state."
)


def instructions_for(feuser) -> str:
    return INSTRUCTIONS + (RECORD_IDS_SHOWN if feuser.show_record_ids else RECORD_IDS_HIDDEN) + "\n"


def _error(status, message):
    return JsonResponse({"error": message}, status=status)


def _origin_allowed(request) -> bool:
    """A browser Origin must be this site itself (DNS rebinding protection); non-browser clients send none."""
    origin = request.headers.get("Origin")
    if not origin:
        return True
    host = urlparse(origin).hostname or ""
    own = {urlparse(getattr(settings, "SITE_URL", "")).hostname, request.get_host().rsplit(":", 1)[0]}
    return host in own


def authenticate(request) -> AgentKey | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    raw = header[7:].strip()
    if not raw:
        return None
    key = AgentKey.objects.select_related("feuser").filter(key_hash=hash_key(raw)).first()
    if key is None or not key.feuser.is_active or key.feuser.is_demo:
        return None
    now = timezone.now()
    if key.last_used_at is None or now - key.last_used_at > _LAST_USED_RESOLUTION:
        AgentKey.objects.filter(pk=key.pk).update(last_used_at=now)
    return key


def _tool_for(op) -> Tool:
    access = "read" if op.access == READ else "read and write"
    return Tool(
        name=op.name,
        description=f"{op.description} (Permission: {CONCERNS[op.concern]}, {access}.)",
        input_schema=op.input_schema(),
        read_only=op.access == READ,
        destructive=op.destructive,
        idempotent=op.method in ("GET", "PUT", "DELETE"),
    )


_DOCS_TOOLS = [
    Tool(
        name="docs_search",
        description="Search the Comaney user manual. Use it before explaining a feature or answering a support question.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Words to look for."}},
            "required": ["query"],
            "additionalProperties": False,
        },
        read_only=True, idempotent=True,
    ),
    Tool(
        name="docs_read",
        description="Read one user manual page by its path from docs_search, e.g. contacts/settling-up.md.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        read_only=True, idempotent=True,
    ),
]


def _docs_tool(name, args):
    site_url = getattr(settings, "SITE_URL", "")
    if name == "docs_search":
        hits = docs.search(str(args.get("query", "")))
        return {"results": [{"path": p.path, "title": p.title, "url": p.url(site_url), "snippet": s} for p, s in hits]}
    page = docs.find(str(args.get("path", "")))
    if page is None:
        raise ToolError("No manual page with that path; use docs_search to find one.")
    return {"path": page.path, "title": page.title, "url": page.url(site_url), "content": page.text}


def build_server(key: AgentKey) -> Server:
    ops = {name: op for name, op in REGISTRY.items() if key.access.allows(op.concern, op.access)}
    ctx = Context(feuser=key.feuser, agent_key=key)

    def call_tool(name, args):
        if name in ("docs_search", "docs_read"):
            return _docs_tool(name, args)
        op = ops[name]
        try:
            return op.handler(ctx, validate_args(op, args))
        except OpError as exc:
            raise ToolError(str(exc))
        except Exception:
            _log.exception("MCP tool %s failed", name)
            raise ToolError("The server failed to run this tool.")

    resources = [Resource(p.uri, p.title, f"User manual: {p.path}") for p in docs.pages()]
    if "cards_reference" in ops:
        resources.append(Resource(CARDS_REFERENCE_URI, "Dashboard card reference", "YAML schema of dashboard cards."))

    def read_resource(uri):
        if uri == CARDS_REFERENCE_URI and "cards_reference" in ops:
            return ops["cards_reference"].handler(ctx, {})["reference"]
        page = docs.find(uri) if uri.startswith(docs.URI_PREFIX) else None
        return page.text if page else None

    def refusal(name):
        op = REGISTRY.get(name)
        if op is None:
            return None
        return (
            f"This agent key may not use {name}: it lacks {permissions.missing(op.concern, op.access)}. "
            "The user can change that in Settings, Advanced, Agent keys."
        )

    return Server(
        name=SERVER_NAME,
        version=getattr(settings, "APP_VERSION", "") or "dev",
        instructions=instructions_for(key.feuser),
        tools=_DOCS_TOOLS + [_tool_for(op) for op in ops.values()],
        call_tool=call_tool,
        resources=resources,
        read_resource=read_resource,
        refusal=refusal,
    )


@csrf_exempt
def mcp_endpoint(request):
    """Streamable HTTP transport, JSON responses only; there is no event stream to GET."""
    if request.method != "POST":
        response = _error(405, "Use POST.")
        response["Allow"] = "POST"
        return response
    if not _origin_allowed(request):
        return _error(403, "Origin not allowed.")
    key = authenticate(request)
    if key is None:
        response = _error(401, "Unauthorized: provide a valid agent key as Bearer token.")
        response["WWW-Authenticate"] = 'Bearer realm="comaney"'
        return response
    answer = build_server(key).handle_body(request.body)
    if answer is None:
        return HttpResponse(status=202)
    return HttpResponse(json.dumps(answer, ensure_ascii=False, default=str), content_type="application/json")
