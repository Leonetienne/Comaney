"""
AI express expense creation: system-prompt assembly, image handling, and
item validation.

The view layer lives in budget/views/express.py. The actual AI round trip
(talking to Claude, JSON-response recovery, trial-budget billing, error
classification) is not here -- it's budget.ai_service.AIService, the single
shared entry point used by every AI feature in the app. This module only
owns what's specific to express creation: building the system prompt text,
preparing an uploaded receipt image, and sanitising the items the AI hands
back before they're shown to the user.
"""
import json
import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from .models import Category, Tag

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System prompt, assembled from independent feature blocks.
#
# Each block is self-contained and describes exactly one capability plus the
# item keys it introduces. build_express_system_prompt() joins the enabled
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

Response format — your ENTIRE reply, from the very first character to the very last, must be exactly one of the two JSON objects below and nothing else:
- The first character of your reply MUST be "{" and the last character MUST be "}".
- No prose, no markdown, no code fences (no ``` anywhere), no leading text, no trailing note or summary after the closing brace.
- Do not use markdown formatting (backticks, asterisks, etc.) inside any field value either — plain text only.
- Inside every string value, escape special characters properly per JSON rules (e.g. use \\n for a line break) — never place a raw, unescaped line break inside a string.

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
# to switch a capability off. build_express_system_prompt() joins them in order.
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


def _select_smart_create_blocks(projects_data: list, single_buddies: list) -> list[str]:
    """Pick which feature blocks apply, based on what this feuser actually has.

    Must be called with the same projects_data/single_buddies lists used to build
    the catalog, so "has a project"/"has a buddy" matches what the AI can reference.
    """
    blocks = [_SMART_CREATE_BASE]
    if projects_data:
        blocks.append(_SMART_CREATE_PROJECTS)
        if any(len(p["members"]) > 1 for p in projects_data):
            blocks.append(_SMART_CREATE_PROJECT_PARTICIPANTS)
            blocks.append(_SMART_CREATE_PROJECT_PAYER)
    if single_buddies:
        blocks.append(_SMART_CREATE_DIRECT_BUDDY)
    return blocks


def build_express_system_prompt(catalog: str, blocks: list[str], custom_instructions: str = "") -> str:
    """Assemble the full express-creation system prompt: feature blocks +
    catalog + the feuser's own custom instructions, if any."""
    system_prompt = _build_smart_create_system(catalog, blocks)
    custom_instructions = (custom_instructions or "").strip()
    if custom_instructions:
        system_prompt += (
            "\n\nUser's custom instructions (follow these when assigning categories/tags):\n"
            f"{custom_instructions}"
        )
    return system_prompt


_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_IMAGE_MAX_PX = 1600
_IMAGE_QUALITY = 82


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
