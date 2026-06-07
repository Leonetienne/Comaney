"""
AI-powered express expense creation: agent abstraction, image handling,
item validation, and trial-key management.

The view layer lives in budget/views/express.py and imports from here.

AI call hierarchy:
  _call_agent(AgentConfig, system_prompt, messages) -> (raw_text, usage)
    └── _call_claude_impl  (provider="claude")
        └── future providers via AgentConfig.provider

Express-creation callers use the legacy _call_claude() wrapper which builds
the content array and parses the smart-create JSON format on top of _call_agent.
"""
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from .models import Category, Tag

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class AIRefusalError(Exception):
    """AI returned {"result": "fail", "msg": "..."}"""
    def __init__(self, msg: str, raw: str = ""):
        super().__init__(msg)
        self.raw = raw


class AIInvalidResponseError(Exception):
    """AI returned unparseable or structurally unexpected output."""
    def __init__(self, raw: str, cause: Exception | None = None):
        super().__init__("Invalid response")
        self.raw = raw
        self.cause = cause


class AIBudgetExceededError(Exception):
    """Trial or user budget is exhausted."""


# ---------------------------------------------------------------------------
# Agent abstraction
# ---------------------------------------------------------------------------

@dataclass
class AgentConfig:
    provider: str = "claude"
    api_key: str = ""
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 8192
    extra: dict = field(default_factory=dict)


def _call_agent(
    config: AgentConfig,
    system_prompt: str | list[dict],
    messages: list[dict],
) -> tuple[str, dict]:
    """
    Dispatch to the configured AI provider.
    system_prompt may be a plain string (wrapped in a single cached block) or
    a pre-built list of Anthropic system content blocks -- the latter lets a
    caller split a large static portion (its own cache_control breakpoint,
    shareable across requests/users) from a smaller per-request dynamic tail.
    Returns (raw_text_response, usage_dict).
    usage_dict keys: input_tokens, output_tokens, cache_write_tokens,
                     cache_read_tokens, total_tokens, cost_usd, cost_cents.
    """
    if config.provider == "claude":
        return _call_claude_impl(config, system_prompt, messages)
    raise ValueError(f"Unsupported AI provider: {config.provider!r}")


def _call_claude_impl(
    config: AgentConfig,
    system_prompt: str | list[dict],
    messages: list[dict],
) -> tuple[str, dict]:
    """Raw Anthropic API call. Returns (response_text, usage_dict)."""
    import anthropic

    if isinstance(system_prompt, str):
        system = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    else:
        system = system_prompt

    client = anthropic.Anthropic(api_key=config.api_key)
    response = client.messages.create(
        model=config.model or "claude-sonnet-4-6",
        max_tokens=config.max_tokens,
        system=system,
        messages=messages,
    )

    raw = ""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            raw = block.text.strip()
            break

    if not raw:
        _log.error("_call_claude_impl: empty response. blocks: %r", response.content)
        raise ValueError(
            f"Claude returned an empty response. Content blocks: "
            f"{[getattr(b, 'type', '?') for b in response.content]}"
        )

    u = response.usage
    input_tok       = getattr(u, "input_tokens", 0)
    output_tok      = getattr(u, "output_tokens", 0)
    cache_write_tok = getattr(u, "cache_creation_input_tokens", 0)
    cache_read_tok  = getattr(u, "cache_read_input_tokens", 0)

    cost = (
        (input_tok       / 1_000_000) * _PRICE_INPUT +
        (output_tok      / 1_000_000) * _PRICE_OUTPUT +
        (cache_write_tok / 1_000_000) * _PRICE_CACHE_WRITE +
        (cache_read_tok  / 1_000_000) * _PRICE_CACHE_READ
    )
    usage = {
        "input_tokens":       input_tok,
        "output_tokens":      output_tok,
        "cache_write_tokens": cache_write_tok,
        "cache_read_tokens":  cache_read_tok,
        "total_tokens":       input_tok + output_tok + cache_write_tok + cache_read_tok,
        "cost_usd":           round(cost, 6),
        "cost_cents":         round(cost * 100, 1),
    }
    return raw, usage


def _default_agent_config(feuser) -> AgentConfig:
    """Resolve the right API key for a feuser (own key > trial key)."""
    api_key, *_ = _trial_state(feuser)
    return AgentConfig(provider="claude", api_key=api_key)


# ---------------------------------------------------------------------------
# Express-creation constants and helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# System prompt, assembled from independent feature blocks.
#
# Each block is self-contained and describes exactly one capability plus the
# item keys it introduces. _build_smart_create_system() joins the enabled
# blocks and appends the catalog. Keeping features in separate blocks (rather
# than one monolithic string) lets us later switch individual capabilities off
# without disturbing the rest: drop a block and the AI stops emitting its keys.
# The base block is always required; it defines the response envelope and the
# keys every item must have.
# ---------------------------------------------------------------------------

_SMART_CREATE_BASE = """You are a financial data-entry assistant for a budgeting app.
The user may provide an image (receipt, invoice, order confirmation, etc.), a text description, or both.
Your job is to extract expense and income items and return a single JSON object.

CRITICAL GROUPING RULE — read this carefully:
All line items that share the same category AND the same tags MUST be merged into a single record.
Sum their values. Use a short collective title (e.g. "Cola and chips", "Toothpaste and shampoo", "Drinks at the bar").
This applies without exception — bottle deposits (Pfand), surcharges, or minor add-ons that belong
to the same category/tag group must be absorbed into that group's record, not given their own entry.
The goal is one record per (category, tags) combination, never one record per line item.
If a user says that they withdrew savings to buy something, they mean that they either paid completely out of savings OR that they want to SPLIT the expense into "expense" and "savings wit", depending on whether the withdrawn amount covers the item.
All generated items IN SUM must match the value stated by the user!

If an image is provided:
- Read every line item, assign each a category and tags, then apply the grouping rule above.
- A supermarket receipt will typically produce very few records (e.g. Groceries, Hygiene, Drinks, Household), not one per product.
- The payee is the store or vendor name from the receipt header.
- Use the user's text (if any) as additional context or filtering instructions.

Response format — your entire response must be one of these two JSON objects, no prose, no markdown, no code fences, never produce any output that's not json! Never produce a leading text or summary!:
Only produce one of the following two json formats as your ENTIRE message:

Success:
{"result": "good", "items": [ ... ]}

Failure (Use ONLY when the input contains no financial information you can extract. Never ask questions. Make the msg sound cute-ish and friendly, maybe a bit insecure. Add cute emoticons such as >.< >_< <_< >_> ^_^ ^.^ ^^ :3 :>. But NEVER use emojis! Cut the response short, it is shown as a small error message.):
{"result": "fail", "msg": "ahh - how am i supposed to know what your drill cost >.<"}

Each item in the "items" array must have exactly these base keys (feature sections below may add more optional keys):
    "title"        — collective name for the group, as short as possible (1-3 words)
    "type"         — "expense", "income", "savings_dep", or "savings_wit"
    "value"        — positive decimal, sum of all merged line items in this group
    "payee"        — merchant or person name, or "" if unknown
    "date_due"     — ISO date string YYYY-MM-DD if the purchase/transaction date is known or can be inferred (e.g. "yesterday", "last Tuesday", a printed date on a receipt or invoice), otherwise null
    "category_uid" — integer uid from the Categories list below, or null if none fits
    "tag_uids"     — array of integer uids from the Tags list below (can be [])
    "note"         — any extra context worth keeping, or ""
Only use category_uid and tag_uids values that appear in the lists below.
If the user describes a lump sum for categorically different things, split by category/tag group.
Default type to "expense" unless the description clearly indicates income or savings movement."""

_SMART_CREATE_PROJECTS = """Assigning an expense to a shared project:
    "project_uid"  — integer uid from the Projects list below if this expense clearly belongs to one of the listed projects, or null if it is a personal expense
Only use project_uid values that appear in the Projects list below.
If an item is assigned to a project (project_uid is set), its type MUST be "expense": project costs are
shared expenses, never income or savings movements for the group. Never combine a non-"expense" type with a project_uid."""

_SMART_CREATE_PROJECT_PARTICIPANTS = """Adjusting who shares a project expense:
    "project_participants" — OPTIONAL, only meaningful when project_uid is set; omit it (or use []) unless the user says otherwise. By default every project member shares the cost equally, so you only need this to record exceptions the user mentions. It is a list of override entries, each: {"idx": <member idx from that project's "members" list>, "included": true|false, "share_percent": <number 0-100, or null>}. Set "included": false to drop a member from sharing entirely (e.g. "Robbie does not participate"). To pin a member to a specific share, use "included": true with "share_percent" set (e.g. "Robbie is on us, set him to 0%" -> {"idx": 2, "included": true, "share_percent": 0} if Robbie is idx 2). Members you do not list keep an equal share of whatever percentage is left over. Only use idx values that appear in that project's "members" list; never invent one."""

_SMART_CREATE_PROJECT_PAYER = """Recording who paid a project expense upfront:
    "project_payer" — OPTIONAL, only meaningful when project_uid is set. The idx (from that project's "members" list) of whoever paid the bill upfront. Omit it or use null when the current user paid, which is the default. Set it when the user says someone else covered the cost (e.g. "Volker paid for the campsite" -> {"project_payer": 1} if Volker is idx 1). The upfront payer is not one of the shared participants; the remaining members split the cost. Only use an idx that appears in that project's "members" list; never invent one."""

_SMART_CREATE_DIRECT_BUDDY = """Sharing an expense one-on-one with a direct buddy (NOT a project):
    "buddy_idx" — OPTIONAL. The idx (from the Direct buddies list below) of the one person this expense is shared with one-on-one, or null for a personal expense. Use this only for a two-person split with a single buddy; use project_uid instead when the cost belongs to a shared project. An item is EITHER a project expense (project_uid) OR a direct buddy expense (buddy_idx), NEVER both.
    "buddy_paid" — OPTIONAL, only meaningful when buddy_idx is set. true if the buddy paid the bill upfront, false or omitted when the current user paid (the default) (e.g. "Volker paid, I owe him half" -> "buddy_paid": true).
    "buddy_share_percent" — OPTIONAL, only meaningful when buddy_idx is set. The buddy's share of the total cost as a number 0-100 (regardless of who paid). Omit it for an equal 50/50 split. Example: "dinner was 40, but 30 of it was mine" -> the buddy's share is 25.
If buddy_idx is set, the item's type MUST be "expense". Only use an idx that appears in the Direct buddies list below; never invent one."""

# Ordered feature blocks. The base is mandatory; the rest can be dropped later
# to switch a capability off. _build_smart_create_system() joins them in order.
_SMART_CREATE_BLOCKS = [
    _SMART_CREATE_BASE,
    _SMART_CREATE_PROJECTS,
    _SMART_CREATE_PROJECT_PARTICIPANTS,
    _SMART_CREATE_PROJECT_PAYER,
    _SMART_CREATE_DIRECT_BUDDY,
]


def _build_smart_create_system(catalog: str, blocks: list[str] | None = None) -> str:
    """Assemble the smart-create system prompt from feature blocks + catalog.

    Pass a subset of _SMART_CREATE_BLOCKS as ``blocks`` to disable capabilities
    (the base block should always be included).
    """
    if blocks is None:
        blocks = _SMART_CREATE_BLOCKS
    return "\n\n".join(blocks) + "\n\n" + catalog

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_IMAGE_MAX_PX = 1600
_IMAGE_QUALITY = 82

_PRICE_INPUT       = 3.00
_PRICE_OUTPUT      = 15.00
_PRICE_CACHE_WRITE = 3.75
_PRICE_CACHE_READ  = 0.30


def _prepare_image(image_file) -> tuple[str, str]:
    """Downscale and JPEG-compress an uploaded image, return (base64, mime_type)."""
    import base64 as _base64
    import io
    from PIL import Image

    img = Image.open(image_file)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > _IMAGE_MAX_PX:
        scale = _IMAGE_MAX_PX / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=_IMAGE_QUALITY, optimize=True)
    return _base64.b64encode(buf.getvalue()).decode("utf-8"), "image/jpeg"


def _build_catalog(feuser, projects_data: list, single_buddies: list) -> str:
    """
    projects_data / single_buddies must be the exact same lists passed to the
    express-creation template (budget/views/expenses.py::_buddy_context), so the
    "idx" the AI is given always lines up with the widget's own member/buddy
    arrays -- re-querying independently here could return a different row
    order and silently point the AI's idx at the wrong person.
    """
    from buddies.models import Project
    categories = list(Category.objects.filter(owning_feuser=feuser).values("uid", "title"))
    tags = list(Tag.objects.filter(owning_feuser=feuser).values("uid", "title"))
    projects_qs = (
        Project.objects
        .filter(members__feuser=feuser, archived=False)
        .distinct()
        .values("uid", "name", "description")
    )
    # Per-project members, indexed 0..N-1 for this request only. The AI refers to
    # a member by "idx" (never a name), so it can only ever point at a position
    # in this exact list -- it has no way to spell an id that isn't a member.
    members_by_project = {
        p["id"]: [{"idx": i, "name": m["name"]} for i, m in enumerate(p["members"])]
        for p in projects_data
    }
    projects = [
        {
            "uid": p["uid"],
            "name": p["name"],
            "description": p["description"] or "",
            "members": members_by_project.get(p["uid"], []),
        }
        for p in projects_qs
    ]
    # Direct (one-on-one) buddies, indexed the same way as project members, in
    # the same order the express-creation UI lists them.
    direct_buddies = [{"idx": i, "name": b["name"]} for i, b in enumerate(single_buddies)]
    parts = [
        f"Categories:\n{json.dumps(categories, ensure_ascii=False)}",
        f"Tags:\n{json.dumps(tags, ensure_ascii=False)}",
    ]
    if projects:
        parts.append(
            f"Projects (assign each expense to one of these if it clearly belongs to a shared project, otherwise null).\n"
            f"\"members\" lists everyone who shares that project's costs; use each member's \"idx\" (never their name) in project_participants/project_payer:\n"
            f"{json.dumps(projects, ensure_ascii=False)}"
        )
    if direct_buddies:
        parts.append(
            f"Direct buddies (people you split one-on-one expenses with, NOT projects). "
            f"Use a buddy's \"idx\" (never their name) as buddy_idx to share an expense with one of these:\n"
            f"{json.dumps(direct_buddies, ensure_ascii=False)}"
        )
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Legacy express-creation wrapper (keeps express.py unchanged)
# ---------------------------------------------------------------------------

def _call_claude(
    api_key: str,
    system_prompt: str,
    description: str,
    image_b64: str = "",
    image_type: str = "image/jpeg",
) -> tuple[list[dict], dict]:
    """
    Express-creation specific AI call.
    Builds the content array, calls _call_agent, parses the smart-create JSON format.
    Returns (parsed_items, usage_dict).
    """
    content: list[dict] = []
    if image_b64:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": image_type,
                "data": image_b64,
            },
        })
    content.append({
        "type": "text",
        "text": description or "Please analyse this image and extract all expense items.",
    })

    config = AgentConfig(provider="claude", api_key=api_key, max_tokens=8192)
    raw, usage = _call_agent(config, system_prompt, [{"role": "user", "content": content}])

    _log.debug("smart_create raw response: %r", raw)

    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0].strip()

    if not raw.startswith('{"result":'):
        idx = raw.find('{"result":')
        if idx == -1:
            idx = raw.find('{ "result":')
        if idx != -1:
            raw = raw[idx:]

    if not raw:
        raise ValueError("Claude returned only a code fence with no content inside.")

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        _log.error("smart_create JSON parse failure. raw=%r exc=%s", raw, exc)
        raise AIInvalidResponseError(raw, exc) from exc

    if isinstance(parsed, dict):
        if parsed.get("result") == "fail":
            raise AIRefusalError(parsed.get("msg", ""), raw)
        if parsed.get("result") == "good":
            items = parsed.get("items", [])
        else:
            raise AIInvalidResponseError(raw)
    elif isinstance(parsed, list):
        items = parsed
    else:
        raise AIInvalidResponseError(raw)

    return items, usage


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _handle_invalid_ai_reference(kind: str, context, value) -> None:
    """
    Drop an idx the AI made up that doesn't resolve to a real catalog entry
    (out of range, wrong type, etc). Silently dropping it is correct for now;
    this is the single choke point to swap in more graceful handling later
    (e.g. reporting the bad idx back to the AI on a correction turn) without
    touching any of the call sites below.
    """
    _log.warning("AI express: dropped invalid %s %r (context=%r)", kind, value, context)


def _handle_share_sum_mismatch(project_uid, total: float) -> None:
    """
    The AI pinned a share_percent for every included participant (no member
    left to auto-absorb the remainder) and they don't sum to 100. Scaling
    them proportionally is the correct behavior for now; this is the single
    choke point to swap in more graceful handling later (e.g. a correction
    turn) without touching the caller.
    """
    _log.warning(
        "AI express: scaling project_participants shares for project %r (sum=%.2f)",
        project_uid, total,
    )


def _normalize_participant_shares(cleaned: list[dict], project_uid, member_count: int) -> list[dict]:
    """
    Enforce that pinned shares (included=True entries with an explicit
    share_percent) add up to 100 whenever there is no unpinned member left to
    absorb the difference. If exactly one participant is included overall,
    their share is trivially the whole expense. Otherwise, when the pinned
    entries don't cover every included participant, a leftover member still
    absorbs the gap so a sum under 100 is valid as-is; a sum over 100 is
    never valid (it overcommits shares that don't exist) and is scaled down.
    """
    mentioned = {e["idx"] for e in cleaned}
    included_idxs = {e["idx"] for e in cleaned if e["included"]} | (set(range(member_count)) - mentioned)
    pinned = [e for e in cleaned if e["included"] and "share_percent" in e]

    if len(included_idxs) == 1:
        only_idx = next(iter(included_idxs))
        for e in pinned:
            if e["idx"] == only_idx:
                e["share_percent"] = 100.0
        return cleaned

    if not pinned:
        return cleaned

    total = sum(e["share_percent"] for e in pinned)
    if total <= 0:
        return cleaned

    full_coverage = {e["idx"] for e in pinned} == included_idxs
    if total > 100 or (full_coverage and total < 100):
        _handle_share_sum_mismatch(project_uid, total)
        scale = 100.0 / total
        for e in pinned:
            e["share_percent"] = e["share_percent"] * scale
    return cleaned


def _sanitize_project_participants(raw_participants, project_uid, member_count: int) -> list[dict]:
    """
    Sanitize the AI's per-member participation overrides for a project expense.
    Returns [] unless a project is assigned and the input is a well-formed list.
    Each kept entry has: idx (int, referring to that project's "members" list
    for this request), included (bool), and optionally share_percent (float
    clamped to 0..100, then normalized to sum to 100 -- see
    _normalize_participant_shares). The express-creation UI consumes these to
    pre-select participants / preset shares before the user confirms.
    """
    if project_uid is None or not isinstance(raw_participants, list):
        return []
    cleaned = []
    for rp in raw_participants:
        if not isinstance(rp, dict):
            continue
        idx = rp.get("idx")
        if not isinstance(idx, int) or isinstance(idx, bool) or not (0 <= idx < member_count):
            _handle_invalid_ai_reference("project_participants idx", project_uid, idx)
            continue
        included = rp.get("included", True)
        if not isinstance(included, bool):
            included = True
        entry = {"idx": idx, "included": included}
        share = rp.get("share_percent")
        if share is not None:
            try:
                share = float(share)
            except (TypeError, ValueError):
                share = None
            if share is not None:
                entry["share_percent"] = max(0.0, min(100.0, share))
        cleaned.append(entry)
    return _normalize_participant_shares(cleaned, project_uid, member_count)


def _sanitize_project_payer(raw_payer, project_uid, member_count: int) -> int | None:
    """
    Sanitize the AI's upfront-payer idx for a project expense. Returns None
    unless a project is assigned and a valid member idx was provided (the
    default None means the current user paid). The express-creation UI looks
    this idx up in the project's members list to preset the payer dropdown.
    """
    if project_uid is None:
        return None
    if not isinstance(raw_payer, int) or isinstance(raw_payer, bool):
        return None
    if not (0 <= raw_payer < member_count):
        _handle_invalid_ai_reference("project_payer idx", project_uid, raw_payer)
        return None
    return raw_payer


def _sanitize_direct_buddy(raw_idx, raw_paid, raw_share, project_uid, buddy_count: int) -> tuple[int | None, bool, float | None]:
    """
    Sanitize the AI's one-on-one direct-buddy assignment. Returns
    (buddy_idx, buddy_paid, buddy_share_percent). Direct buddy and project
    assignment are mutually exclusive, so everything is dropped when a project
    is set. buddy_idx is None for a personal expense (or an out-of-range idx);
    buddy_paid is True only when the AI explicitly says the buddy paid (default
    False, current user paid); buddy_share_percent is the buddy's share
    (0..100) or None for an equal split. The express-creation UI looks buddy_idx
    up in the user's direct-buddy list to preset the Direct Buddy section.
    """
    if project_uid is not None or not isinstance(raw_idx, int) or isinstance(raw_idx, bool):
        return None, False, None
    if not (0 <= raw_idx < buddy_count):
        _handle_invalid_ai_reference("buddy_idx", "direct_buddy", raw_idx)
        return None, False, None
    paid = raw_paid is True
    share = None
    if raw_share is not None:
        try:
            share = max(0.0, min(100.0, float(raw_share)))
        except (TypeError, ValueError):
            share = None
    return raw_idx, paid, share


def _validate_items(raw_items: list, feuser, projects_data: list, single_buddies: list) -> tuple[list[dict], list[str]]:
    """
    Validate and sanitise parsed items against the user's actual categories/tags/projects.

    projects_data / single_buddies must be the exact same lists passed to
    _build_catalog() for this request, so idx range-checks agree with the idx
    the AI was actually given (see _build_catalog's docstring).
    """
    from buddies.models import Project
    valid_category_uids = set(
        Category.objects.filter(owning_feuser=feuser).values_list("uid", flat=True)
    )
    valid_tag_uids = set(
        Tag.objects.filter(owning_feuser=feuser).values_list("uid", flat=True)
    )
    valid_project_uids = set(
        Project.objects.filter(members__feuser=feuser, archived=False)
        .distinct()
        .values_list("uid", flat=True)
    )
    member_counts_by_project = {p["id"]: len(p["members"]) for p in projects_data}
    buddy_count = len(single_buddies)
    category_map = {
        c["uid"]: c["title"]
        for c in Category.objects.filter(owning_feuser=feuser).values("uid", "title")
    }
    tag_map = {
        t["uid"]: t["title"]
        for t in Tag.objects.filter(owning_feuser=feuser).values("uid", "title")
    }

    items = []
    errors = []
    for i, raw in enumerate(raw_items):
        try:
            value = Decimal(str(raw.get("value", 0))).quantize(Decimal("0.01"))
            if value <= 0:
                raise ValueError("value must be positive")
        except (InvalidOperation, ValueError) as exc:
            errors.append(f"Item {i+1}: invalid value — {exc}")
            continue

        tx_type = raw.get("type", "expense")
        if tx_type not in ("expense", "income", "savings_dep", "savings_wit"):
            tx_type = "expense"

        cat_uid = raw.get("category_uid")
        if cat_uid not in valid_category_uids:
            cat_uid = None

        tag_uids = [u for u in (raw.get("tag_uids") or []) if u in valid_tag_uids]

        project_uid = raw.get("project_uid")
        if project_uid not in valid_project_uids:
            project_uid = None
        member_count = member_counts_by_project.get(project_uid, 0) if project_uid is not None else 0

        buddy_idx, buddy_paid, buddy_share = _sanitize_direct_buddy(
            raw.get("buddy_idx"), raw.get("buddy_paid"),
            raw.get("buddy_share_percent"), project_uid, buddy_count,
        )

        # Project and direct-buddy expenses only make sense as type=expense (see
        # budget/expense_factory.py); the AI is told this, but force it rather than trust it.
        if (project_uid is not None or buddy_idx is not None) and tx_type != "expense":
            tx_type = "expense"

        date_due = None
        date_due_raw = raw.get("date_due")
        if date_due_raw:
            try:
                date_due = date.fromisoformat(str(date_due_raw))
            except (ValueError, TypeError):
                pass

        items.append({
            "title":          str(raw.get("title", "Untitled"))[:255],
            "type":           tx_type,
            "value":          str(value),
            "payee":          str(raw.get("payee", "") or "")[:255],
            "note":           str(raw.get("note", "") or ""),
            "date_due":       date_due.isoformat() if date_due else "",
            "category_uid":   cat_uid,
            "category_title": category_map.get(cat_uid, "—") if cat_uid else "—",
            "tag_uids":       tag_uids,
            "tag_titles":     [tag_map[u] for u in tag_uids],
            "project_uid":    project_uid,
            "project_participants": _sanitize_project_participants(
                raw.get("project_participants"), project_uid, member_count
            ),
            "project_payer": _sanitize_project_payer(
                raw.get("project_payer"), project_uid, member_count
            ),
            "buddy_idx":           buddy_idx,
            "buddy_paid":          buddy_paid,
            "buddy_share_percent": buddy_share,
        })

    return items, errors


def _parse_buddy_item(item: dict, feuser) -> dict | None:
    """Parse buddy payment fields from a preview item dict. Returns None if not a buddy payment."""
    if not item.get("buddy_payment") or not item.get("buddy_spendings"):
        return None

    from buddies.models import Project, DummyUser
    from feusers.models import FeUser as FU

    upfront_type = item.get("buddy_upfront_type", "me")
    upfront_id   = item.get("buddy_upfront_id")
    mode         = item.get("buddy_mode", "single")
    group_id     = item.get("project_id") or item.get("buddy_group_id")
    spendings    = item.get("buddy_spendings", [])

    group = None
    if mode == "group" and group_id:
        try:
            group = Project.objects.get(
                uid=group_id, members__feuser=feuser, archived=False
            )
        except Project.DoesNotExist:
            pass

    upfront_feuser = None
    upfront_dummy  = None
    if upfront_type == "feuser":
        try:
            upfront_feuser = FU.objects.get(pk=upfront_id, is_active=True)
        except (FU.DoesNotExist, TypeError, ValueError):
            return None
    elif upfront_type == "dummy":
        try:
            upfront_dummy = DummyUser.objects.get(pk=upfront_id)
        except (DummyUser.DoesNotExist, TypeError, ValueError):
            return None

    if not spendings:
        return None

    # Authorization: reject any upfront payer / participant not connected to the
    # acting user (same central validator as the web create/edit path).
    from buddies.services import BuddyExpenseService
    if not BuddyExpenseService.validate_buddy_identities(
        feuser,
        group=group,
        upfront_feuser=upfront_feuser,
        upfront_dummy=upfront_dummy,
        spendings=spendings,
    ):
        return None

    return {
        "upfront_type":   upfront_type,
        "upfront_feuser": upfront_feuser,
        "upfront_dummy":  upfront_dummy,
        "group":          group,
        "spendings":      spendings,
    }


def _trial_state(feuser):
    """Return (api_key, is_trial, trial_limit, trial_spent, trial_blocked)."""
    from django.conf import settings
    if feuser.anthropic_api_key:
        return feuser.anthropic_api_key, False, 0, 0, False
    trial_key = settings.AI_TRIAL_API_KEY
    if feuser.special_ai_trial_budget is not None:
        trial_limit = float(feuser.special_ai_trial_budget)
    else:
        trial_limit = settings.AI_TRIAL_USAGE_LIMIT
    if not trial_key or not trial_limit:
        return "", False, 0, 0, False
    spent   = float(feuser.ai_trial_budget_spent or 0)
    blocked = spent >= trial_limit
    return trial_key, True, trial_limit, spent, blocked
