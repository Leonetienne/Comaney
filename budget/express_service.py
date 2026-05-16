"""
AI-powered express expense creation: Claude API integration, image handling,
item validation, and trial-key management.

The view layer lives in budget/views/express.py and imports from here.
"""
import json
import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from .models import Category, Tag

_log = logging.getLogger(__name__)


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


_SMART_CREATE_SYSTEM = """You are a financial data-entry assistant for a budgeting app.
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
{{"result": "good", "items": [ ... ]}}

Failure (Use ONLY when the input contains no financial information you can extract. Never ask questions. Make the msg sound cute-ish and friendly, maybe a bit insecure. Add cute emoticons such as >.< >_< <_< >_> ^_^ ^.^ ^^ :3 :>. But NEVER use emojis! Cut the response short, it is shown as a small error message.):
{{"result": "fail", "msg": "ahh - how am i supposed to know what your drill cost >.<"}}

Each item in the "items" array must have exactly these keys:
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
Default type to "expense" unless the description clearly indicates income or savings movement.

{{catalog}}"""

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


def _build_catalog(feuser) -> str:
    categories = list(Category.objects.filter(owning_feuser=feuser).values("uid", "title"))
    tags = list(Tag.objects.filter(owning_feuser=feuser).values("uid", "title"))
    return (
        f"Categories:\n{json.dumps(categories, ensure_ascii=False)}\n\n"
        f"Tags:\n{json.dumps(tags, ensure_ascii=False)}"
    )


def _call_claude(
    api_key: str,
    system_prompt: str,
    description: str,
    image_b64: str = "",
    image_type: str = "image/jpeg",
) -> tuple[list[dict], dict]:
    """Return (parsed_items, usage_info_dict)."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

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

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": content}],
    )

    raw = ""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            raw = block.text.strip()
            break

    _log.debug("smart_create raw response: %r", raw)

    if not raw:
        _log.error("smart_create: empty response. Full content: %r", response.content)
        raise ValueError(f"Claude returned an empty response. Content blocks: {[getattr(b, 'type', '?') for b in response.content]}")

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

    u = response.usage
    input_tok        = getattr(u, "input_tokens", 0)
    output_tok       = getattr(u, "output_tokens", 0)
    cache_write_tok  = getattr(u, "cache_creation_input_tokens", 0)
    cache_read_tok   = getattr(u, "cache_read_input_tokens", 0)

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
    return items, usage


def _validate_items(raw_items: list, feuser) -> tuple[list[dict], list[str]]:
    """Validate and sanitise parsed items against the user's actual categories/tags."""
    valid_category_uids = set(
        Category.objects.filter(owning_feuser=feuser).values_list("uid", flat=True)
    )
    valid_tag_uids = set(
        Tag.objects.filter(owning_feuser=feuser).values_list("uid", flat=True)
    )
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
        })

    return items, errors


def _parse_buddy_item(item: dict, feuser) -> dict | None:
    """Parse buddy payment fields from a preview item dict. Returns None if not a buddy payment."""
    if not item.get("buddy_payment") or not item.get("buddy_spendings"):
        return None

    from buddies.models import BuddyGroup, DummyUser
    from feusers.models import FeUser as FU

    upfront_type = item.get("buddy_upfront_type", "me")
    upfront_id   = item.get("buddy_upfront_id")
    mode         = item.get("buddy_mode", "single")
    group_id     = item.get("buddy_group_id")
    spendings    = item.get("buddy_spendings", [])

    group = None
    if mode == "group" and group_id:
        try:
            group = BuddyGroup.objects.get(uid=group_id, members__feuser=feuser)
        except BuddyGroup.DoesNotExist:
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
    trial_key   = settings.AI_TRIAL_API_KEY
    trial_limit = settings.AI_TRIAL_USAGE_LIMIT
    if not trial_key or not trial_limit:
        return "", False, 0, 0, False
    spent   = float(feuser.ai_trial_budget_spent or 0)
    blocked = spent >= trial_limit
    return trial_key, True, trial_limit, spent, blocked
