import json
import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from django.shortcuts import redirect, render
from django.utils import timezone

from ..decorators import feuser_required
from ..expense_factory import create_expense
from ..models import Category, Tag, TransactionType

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
    "title"        — collective name for the group, as short as possible (1–3 words)
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

{catalog}"""

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


@feuser_required
def express_creation(request):
    from ..ai_trial import disable_trial, notify_admin_billing, notify_admin_invalid_trial_key, trial_is_disabled

    feuser = request.feuser
    api_key, is_trial, trial_limit, trial_spent, trial_blocked = _trial_state(feuser)

    if not api_key:
        return redirect("profile")

    trial_disabled = is_trial and trial_is_disabled()

    categories = list(Category.objects.filter(owning_feuser=feuser).values("uid", "title"))
    tags = list(Tag.objects.filter(owning_feuser=feuser).values("uid", "title"))
    context = {
        "active_nav":         "express_creation",
        "description":        "",
        "preview_items":      None,
        "preview_json":       "",
        "usage":              None,
        "ai_error":           None,
        "created_count":      None,
        "categories":         categories,
        "tags":               tags,
        "is_trial":           is_trial,
        "trial_limit":        trial_limit,
        "trial_spent":        round(trial_spent, 1),
        "trial_blocked":      trial_blocked,
        "trial_disabled":     trial_disabled,
        "trial_just_exhausted": False,
    }

    if trial_disabled or trial_blocked:
        return render(request, "budget/express_creation.html", context)

    if request.method == "POST":
        action = request.POST.get("action", "parse")

        if action == "parse":
            description = request.POST.get("description", "").strip()
            image_b64 = ""
            image_type = "image/jpeg"
            image_file = request.FILES.get("image_file")
            if image_file:
                image_b64, image_type = _prepare_image(image_file)
            context["description"] = description
            if not description and not image_b64:
                context["ai_error"] = "Please enter a description or attach an image."
                context["ai_error_is_validation"] = True
            else:
                catalog = _build_catalog(feuser)
                custom = feuser.ai_custom_instructions.strip()
                extra = f"\n\nUser's custom instructions (follow these when assigning categories/tags):\n{custom}" if custom else ""
                system_prompt = _SMART_CREATE_SYSTEM.format(catalog=catalog) + extra
                today_str = timezone.localdate().isoformat()
                description_with_date = f"[Today's date: {today_str}]\n\n{description}" if description else f"[Today's date: {today_str}]"
                try:
                    raw_items, usage = _call_claude(
                        api_key, system_prompt, description_with_date,
                        image_b64=image_b64, image_type=image_type,
                    )
                    items, errors = _validate_items(raw_items, feuser)
                    if errors:
                        context["ai_error"] = " | ".join(errors)
                    if items:
                        context["preview_items"] = items
                        context["preview_json"] = json.dumps(items)
                    context["usage"] = usage
                    if is_trial and usage:
                        from decimal import Decimal as _Dec
                        feuser.ai_trial_budget_spent = (feuser.ai_trial_budget_spent or _Dec(0)) + _Dec(str(usage["cost_cents"]))
                        feuser.save(update_fields=["ai_trial_budget_spent"])
                        context["trial_spent"] = round(float(feuser.ai_trial_budget_spent), 1)
                        if float(feuser.ai_trial_budget_spent) >= trial_limit:
                            context["trial_just_exhausted"] = True
                except AIRefusalError as exc:
                    context["ai_error"] = str(exc)
                    context["ai_raw_output"] = exc.raw
                except AIInvalidResponseError as exc:
                    _log.error("smart_create invalid response: cause=%s raw=%r", exc.cause, exc.raw)
                    context["ai_error"] = ""
                    context["ai_raw_output"] = exc.raw
                except Exception as exc:
                    import anthropic as _anthropic

                    def _handle_billing():
                        if is_trial:
                            disable_trial(str(exc))
                            notify_admin_billing(str(exc))
                            context["trial_disabled"] = True
                        else:
                            context["ai_error"] = "Insufficient Anthropic credits. Please top up your account at console.anthropic.com."

                    if isinstance(exc, _anthropic.AuthenticationError):
                        if is_trial:
                            notify_admin_invalid_trial_key()
                            context["ai_error"] = "The server is misconfigured: the trial API key is invalid. Please contact the server administrator."
                        else:
                            context["ai_error"] = "Invalid API key. Please update it in your profile."
                    elif isinstance(exc, _anthropic.PermissionDeniedError):
                        context["ai_error"] = "API key does not have permission to use this model. Please check your Anthropic account."
                    elif isinstance(exc, _anthropic.RateLimitError):
                        msg = str(exc).lower()
                        if "credit" in msg or "billing" in msg or "balance" in msg:
                            _handle_billing()
                        else:
                            context["ai_error"] = "Anthropic rate limit reached. Please wait a moment and try again."
                    elif isinstance(exc, _anthropic.APIConnectionError):
                        context["ai_error"] = "Could not reach the Anthropic API. Please check your internet connection."
                    elif isinstance(exc, _anthropic.APIStatusError):
                        msg = str(exc).lower()
                        if "credit" in msg or "billing" in msg or "balance" in msg:
                            _handle_billing()
                        else:
                            context["ai_error"] = f"Anthropic API error {exc.status_code}: {exc.message}"
                    else:
                        context["ai_error"] = f"Unexpected error: {exc}"

        elif action == "confirm":
            preview_json = request.POST.get("preview_json", "")
            selected_indices = set(
                int(i) for i in request.POST.getlist("selected")
                if i.isdigit()
            )
            today = timezone.localdate()
            try:
                all_items = json.loads(preview_json)
                if not selected_indices:
                    selected_indices = set(range(len(all_items)))
                category_cache: dict[int, Category] = {}
                tag_cache: dict[int, Tag] = {}
                count = 0
                for idx, item in enumerate(all_items):
                    if idx not in selected_indices:
                        continue

                    cat_uid = item.get("category_uid")
                    category = None
                    if cat_uid:
                        if cat_uid not in category_cache:
                            try:
                                category_cache[cat_uid] = Category.objects.get(uid=cat_uid, owning_feuser=feuser)
                            except Category.DoesNotExist:
                                pass
                        category = category_cache.get(cat_uid)

                    tags = []
                    for tuid in (item.get("tag_uids") or []):
                        if tuid not in tag_cache:
                            try:
                                tag_cache[tuid] = Tag.objects.get(uid=tuid, owning_feuser=feuser)
                            except Tag.DoesNotExist:
                                pass
                        if tuid in tag_cache:
                            tags.append(tag_cache[tuid])

                    item_date = today
                    date_due_str = item.get("date_due", "")
                    if date_due_str:
                        try:
                            item_date = date.fromisoformat(date_due_str)
                        except (ValueError, TypeError):
                            pass

                    create_expense(
                        owning_feuser=feuser,
                        title=item["title"],
                        type=TransactionType(item["type"]),
                        value=Decimal(item["value"]),
                        payee=item.get("payee", ""),
                        note=item.get("note", ""),
                        category=category,
                        tags=tags or None,
                        date_due=item_date,
                        settled=True,
                    )
                    count += 1
                if not context.get("ai_error"):
                    return redirect(f"{request.path}?created={count}")
                context["created_count"] = count
            except Exception as exc:
                context["ai_error"] = f"Could not save expenses: {exc}"

    if not context["created_count"] and request.GET.get("created", "").isdigit():
        context["created_count"] = int(request.GET["created"])

    return render(request, "budget/express_creation.html", context)
