import calendar
import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .date_utils import current_financial_month, financial_month_range, financial_year_range
from .decorators import feuser_required
from .expense_factory import create_expense
from .forms import ExpenseForm, ScheduledExpenseForm
from .models import Category, Expense, ScheduledExpense, Tag, TransactionType


def _get_period_mode(request) -> str:
    return "year" if request.GET.get("view") == "year" else "month"


def _get_year(request, start_day: int = 1, prev_month: bool = False) -> int:
    try:
        year = int(request.GET["year"])
        if year < 1:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        return current_financial_month(start_day, prev_month)[0]
    return year


def _year_nav_context(year: int, start_day: int = 1, prev_month: bool = False) -> dict:
    cur_year, cur_month = current_financial_month(start_day, prev_month)
    is_current = (year == cur_year)
    start, end = financial_year_range(year, start_day, prev_month)
    is_default = (start_day == 1 and not prev_month)
    range_str = f"{start.strftime('%-d %b %Y')} – {end.strftime('%-d %b %Y')}" if not is_default else ""
    return {
        "nav_mode": "year",
        "nav_year": year,
        "nav_month": cur_month,
        "nav_label": str(year),
        "nav_range": range_str,
        "nav_prev_year": year - 1,
        "nav_next_year": year + 1,
        "nav_is_current": is_current,
    }


def _get_month(request, start_day: int = 1, prev_month: bool = False) -> tuple[int, int]:
    try:
        year = int(request.GET["year"])
        month = int(request.GET["month"])
        if not (1 <= month <= 12):
            raise ValueError
    except (KeyError, ValueError, TypeError):
        return current_financial_month(start_day, prev_month)
    return year, month


def _month_nav_context(year: int, month: int, start_day: int = 1, prev_month: bool = False) -> dict:
    nav_prev_month = month - 1 or 12
    nav_prev_year  = year - 1 if month == 1 else year
    nav_next_month = month % 12 + 1
    nav_next_year  = year + 1 if month == 12 else year
    cur_year, cur_month = current_financial_month(start_day, prev_month)
    is_current = (year == cur_year and month == cur_month)
    start, end = financial_month_range(year, month, start_day, prev_month)
    is_default = (start_day == 1 and not prev_month)
    range_str = f"{start.strftime('%-d %b')} – {end.strftime('%-d %b')}" if not is_default else ""
    return {
        "nav_mode": "month",
        "nav_year": year,
        "nav_month": month,
        "nav_label": date(year, month, 1).strftime("%B %Y"),
        "nav_range": range_str,
        "nav_prev_year": nav_prev_year,
        "nav_prev_month": nav_prev_month,
        "nav_next_year": nav_next_year,
        "nav_next_month": nav_next_month,
        "nav_is_current": is_current,
    }


@feuser_required
def dashboard(request):
    feuser = request.feuser
    mode = _get_period_mode(request)

    if mode == "year":
        year = _get_year(request, feuser.month_start_day, feuser.month_start_prev)
        start, end = financial_year_range(year, feuser.month_start_day, feuser.month_start_prev)
        nav_ctx = _year_nav_context(year, feuser.month_start_day, feuser.month_start_prev)
    else:
        year, month = _get_month(request, feuser.month_start_day, feuser.month_start_prev)
        start, end = financial_month_range(year, month, feuser.month_start_day, feuser.month_start_prev)
        nav_ctx = _month_nav_context(year, month, feuser.month_start_day, feuser.month_start_prev)

    period_qs = Expense.objects.filter(
        owning_feuser=feuser,
        date_due__gte=start,
        date_due__lte=end,
    )

    def _sum(qs):
        return qs.aggregate(t=Sum("value"))["t"] or Decimal("0")

    income      = _sum(period_qs.filter(type="income"))
    carry_over  = _sum(period_qs.filter(type="carry_over"))
    paid        = _sum(period_qs.filter(type="expense", settled=True))
    outstanding = _sum(period_qs.filter(type="expense", settled=False))
    sav_dep     = _sum(period_qs.filter(type="savings_dep"))
    sav_wit     = _sum(period_qs.filter(type="savings_wit"))
    savings     = sav_dep - sav_wit
    left        = income + carry_over - paid - outstanding - savings

    expense_qs = period_qs.filter(type="expense")

    cat_rows = list(
        expense_qs.values("category__title")
        .annotate(total=Sum("value"))
        .order_by("-total")
    )
    for r in cat_rows:
        if r["category__title"] is None:
            r["category__title"] = "Uncategorized"

    tag_rows = list(
        expense_qs.filter(tags__isnull=False)
        .values("tags__title")
        .annotate(total=Sum("value"))
        .order_by("-total")
    )

    ctx = {
        "active_nav": "dashboard",
        "income": income,
        "paid": paid,
        "outstanding": outstanding,
        "savings": savings,
        "left": left,
        "cat_labels": json.dumps([r["category__title"] for r in cat_rows]),
        "cat_values": json.dumps([float(r["total"]) for r in cat_rows]),
        "tag_labels": json.dumps([r["tags__title"] for r in tag_rows]),
        "tag_values": json.dumps([float(r["total"]) for r in tag_rows]),
    }
    ctx.update(nav_ctx)
    return render(request, "budget/dashboard.html", ctx)


@feuser_required
def categories_tags(request):
    feuser = request.feuser
    categories = Category.objects.filter(owning_feuser=feuser)
    tags = Tag.objects.filter(owning_feuser=feuser)
    return render(request, "budget/categories_tags.html", {
        "active_nav": "categories_tags",
        "categories": categories,
        "tags": tags,
    })


@feuser_required
@require_POST
def category_create(request):
    data = json.loads(request.body)
    title = data.get("title", "").strip()
    if not title:
        return JsonResponse({"error": "Title required."}, status=400)
    category = Category.objects.create(owning_feuser=request.feuser, title=title)
    return JsonResponse({"uid": category.uid, "title": category.title})


@feuser_required
@require_POST
def category_delete(request, uid):
    category = get_object_or_404(Category, uid=uid, owning_feuser=request.feuser)
    category.delete()
    return JsonResponse({"ok": True})


@feuser_required
@require_POST
def category_rename(request, uid):
    category = get_object_or_404(Category, uid=uid, owning_feuser=request.feuser)
    data = json.loads(request.body)
    title = data.get("title", "").strip()
    if not title:
        return JsonResponse({"error": "Title required."}, status=400)
    category.title = title
    category.save(update_fields=["title"])
    return JsonResponse({"uid": category.uid, "title": category.title})


@feuser_required
@require_POST
def tag_create(request):
    data = json.loads(request.body)
    title = data.get("title", "").strip()
    if not title:
        return JsonResponse({"error": "Title required."}, status=400)
    tag = Tag.objects.create(owning_feuser=request.feuser, title=title)
    return JsonResponse({"uid": tag.uid, "title": tag.title})


@feuser_required
@require_POST
def tag_delete(request, uid):
    tag = get_object_or_404(Tag, uid=uid, owning_feuser=request.feuser)
    tag.delete()
    return JsonResponse({"ok": True})


@feuser_required
@require_POST
def tag_rename(request, uid):
    tag = get_object_or_404(Tag, uid=uid, owning_feuser=request.feuser)
    data = json.loads(request.body)
    title = data.get("title", "").strip()
    if not title:
        return JsonResponse({"error": "Title required."}, status=400)
    tag.title = title
    tag.save(update_fields=["title"])
    return JsonResponse({"uid": tag.uid, "title": tag.title})


@feuser_required
def expenses_list(request):
    feuser = request.feuser
    mode = _get_period_mode(request)

    if mode == "year":
        year = _get_year(request, feuser.month_start_day, feuser.month_start_prev)
        start, end = financial_year_range(year, feuser.month_start_day, feuser.month_start_prev)
        nav_ctx = _year_nav_context(year, feuser.month_start_day, feuser.month_start_prev)
    else:
        year, month = _get_month(request, feuser.month_start_day, feuser.month_start_prev)
        start, end = financial_month_range(year, month, feuser.month_start_day, feuser.month_start_prev)
        nav_ctx = _month_nav_context(year, month, feuser.month_start_day, feuser.month_start_prev)

    expenses = (
        Expense.objects.filter(
            owning_feuser=feuser,
            date_due__gte=start,
            date_due__lte=end,
        )
        .select_related("category")
        .prefetch_related("tags")
        .order_by("-date_due", "-date_created")
    )
    ctx = {
        "active_nav": "expenses",
        "expenses": expenses,
    }
    ctx.update(nav_ctx)
    return render(request, "budget/expenses_list.html", ctx)


@feuser_required
def expenses_export(request):
    import csv
    from django.http import HttpResponse

    feuser = request.feuser
    mode = _get_period_mode(request)

    if mode == "year":
        year = _get_year(request, feuser.month_start_day, feuser.month_start_prev)
        start, end = financial_year_range(year, feuser.month_start_day, feuser.month_start_prev)
        label = str(year)
    else:
        year, month = _get_month(request, feuser.month_start_day, feuser.month_start_prev)
        start, end = financial_month_range(year, month, feuser.month_start_day, feuser.month_start_prev)
        label = date(year, month, 1).strftime("%B_%Y")

    expenses = (
        Expense.objects.filter(
            owning_feuser=feuser,
            date_due__gte=start,
            date_due__lte=end,
        )
        .select_related("category")
        .prefetch_related("tags")
        .order_by("date_due", "date_created")
    )
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="expenses_{label}.csv"'

    w = csv.writer(response)
    w.writerow(["date_due", "title", "type", "value", "payee", "category", "tags", "note", "settled"])
    for e in expenses:
        w.writerow([
            e.date_due or "",
            e.title,
            e.type,
            e.value,
            e.payee,
            e.category.title if e.category else "",
            "|".join(t.title for t in e.tags.all()),
            e.note,
            e.settled,
        ])
    return response


@feuser_required
def expense_create(request):
    if request.method == "POST":
        form = ExpenseForm(request.POST, feuser=request.feuser)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.owning_feuser = request.feuser
            expense.save()
            form.save_m2m()
            return redirect("budget:expenses_list")
    else:
        form = ExpenseForm(feuser=request.feuser, initial={"type": "expense", "settled": True})
    return render(request, "budget/expense_form.html", {
        "active_nav": "expenses",
        "form": form,
    })


@feuser_required
def expense_edit(request, uid):
    expense = get_object_or_404(Expense, uid=uid, owning_feuser=request.feuser)
    if expense.type == TransactionType.CARRY_OVER:
        return redirect("budget:expenses_list")
    if request.method == "POST":
        form = ExpenseForm(request.POST, instance=expense, feuser=request.feuser)
        if form.is_valid():
            form.save()
            return redirect("budget:expenses_list")
    else:
        form = ExpenseForm(instance=expense, feuser=request.feuser)
    return render(request, "budget/expense_form.html", {
        "active_nav": "expenses",
        "form": form,
        "expense": expense,
    })


@feuser_required
@require_POST
def expense_delete(request, uid):
    expense = get_object_or_404(Expense, uid=uid, owning_feuser=request.feuser)
    if expense.type == TransactionType.CARRY_OVER:
        return redirect("budget:expenses_list")
    expense.delete()
    return redirect("budget:expenses_list")


@feuser_required
@require_POST
def expense_clone(request, uid):
    original = get_object_or_404(Expense, uid=uid, owning_feuser=request.feuser)
    if original.type == TransactionType.CARRY_OVER:
        return redirect("budget:expenses_list")
    tags = list(original.tags.all())
    original.pk = None
    original.title = f"CLONE - {original.title}"
    original.save()
    original.tags.set(tags)
    return redirect("budget:expense_edit", uid=original.pk)


@feuser_required
def scheduled_list(request):
    scheduled = (
        ScheduledExpense.objects.filter(owning_feuser=request.feuser)
        .select_related("category")
        .prefetch_related("tags")
    )
    return render(request, "budget/scheduled_list.html", {
        "active_nav": "scheduled",
        "scheduled": scheduled,
    })


@feuser_required
def scheduled_create(request):
    if request.method == "POST":
        form = ScheduledExpenseForm(request.POST, feuser=request.feuser)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.owning_feuser = request.feuser
            obj.save()
            form.save_m2m()
            return redirect("budget:scheduled_list")
    else:
        form = ScheduledExpenseForm(feuser=request.feuser, initial={"type": "expense", "default_auto_settle_on_due_date": True})
    return render(request, "budget/scheduled_form.html", {
        "active_nav": "scheduled",
        "form": form,
    })


@feuser_required
def scheduled_edit(request, uid):
    obj = get_object_or_404(ScheduledExpense, uid=uid, owning_feuser=request.feuser)
    if request.method == "POST":
        form = ScheduledExpenseForm(request.POST, instance=obj, feuser=request.feuser)
        if form.is_valid():
            form.save()
            return redirect("budget:scheduled_list")
    else:
        form = ScheduledExpenseForm(instance=obj, feuser=request.feuser)
    return render(request, "budget/scheduled_form.html", {
        "active_nav": "scheduled",
        "form": form,
        "scheduled": obj,
    })


@feuser_required
@require_POST
def scheduled_delete(request, uid):
    obj = get_object_or_404(ScheduledExpense, uid=uid, owning_feuser=request.feuser)
    obj.delete()
    return redirect("budget:scheduled_list")


@feuser_required
@require_POST
def scheduled_clone(request, uid):
    original = get_object_or_404(ScheduledExpense, uid=uid, owning_feuser=request.feuser)
    tags = list(original.tags.all())
    original.pk = None
    original.title = f"CLONE - {original.title}"
    original.save()
    original.tags.set(tags)
    return redirect("budget:scheduled_edit", uid=original.pk)


# ---------------------------------------------------------------------------
# Express Creation (AI)
# ---------------------------------------------------------------------------

_SMART_CREATE_SYSTEM = """You are a financial data-entry assistant for a budgeting app.
The user may provide an image (receipt, invoice, order confirmation, etc.), a text description, or both.
Your job is to extract expense and income items and return a JSON array of expense objects.

CRITICAL GROUPING RULE — read this carefully:
All line items that share the same category AND the same tags MUST be merged into a single record.
Sum their values. Use a short collective title (e.g. "Cola and chips", "Toothpaste and shampoo", "Drinks at the bar").
This applies without exception — bottle deposits (Pfand), surcharges, or minor add-ons that belong
to the same category/tag group must be absorbed into that group's record, not given their own entry.
The goal is one record per (category, tags) combination, never one record per line item.

If an image is provided:
- Read every line item, assign each a category and tags, then apply the grouping rule above.
- A supermarket receipt will typically produce very few records (e.g. Groceries, Hygiene, Drinks, Household), not one per product.
- The payee is the store or vendor name from the receipt header.
- Use the user's text (if any) as additional context or filtering instructions.

Rules:
- Return ONLY a valid JSON array. Your entire response must start with [ and end with ]. No prose, no reasoning, no markdown, no code fences — just the raw JSON array.
- Each object must have exactly these keys:
    "title"        — collective name for the group, as short as possible (1–3 words)
    "type"         — "expense", "income", "savings_dep", or "savings_wit"
    "value"        — positive decimal, sum of all merged line items in this group
    "payee"        — merchant or person name, or "" if unknown
    "date_due"     — ISO date string YYYY-MM-DD if the purchase/transaction date is known or can be inferred (e.g. "yesterday", "last Tuesday", a printed date on a receipt or invoice), otherwise null
    "category_uid" — integer uid from the Categories list below, or null if none fits
    "tag_uids"     — array of integer uids from the Tags list below (can be [])
    "note"         — any extra context worth keeping, or ""
- Only use category_uid and tag_uids values that appear in the lists below.
- If the user describes a lump sum for categorically different things, split by category/tag group.
- Default type to "expense" unless the description clearly indicates income or savings movement.

{catalog}"""

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_IMAGE_MAX_PX = 1600  # longest side in pixels before downscaling
_IMAGE_QUALITY = 82   # JPEG compression quality after resize


def _prepare_image(image_file) -> tuple[str, str]:
    """Downscale and JPEG-compress an uploaded image, return (base64, mime_type)."""
    import base64 as _base64
    import io
    from PIL import Image

    img = Image.open(image_file)

    # Convert palette/RGBA modes so JPEG save works
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    # Downscale if either dimension exceeds the limit
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


# Pricing for claude-sonnet-4-6 (USD per 1M tokens)
_PRICE_INPUT       = 3.00
_PRICE_OUTPUT      = 15.00
_PRICE_CACHE_WRITE = 3.75   # 1.25× input
_PRICE_CACHE_READ  = 0.30   # 0.10× input


def _call_claude(
    api_key: str,
    system_prompt: str,
    description: str,
    image_b64: str = "",
    image_type: str = "image/jpeg",
) -> tuple[list[dict], dict]:
    """Return (parsed_items, usage_info_dict)."""
    import anthropic  # lazy import — only installed when feature is used

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
    import logging as _logging
    _log = _logging.getLogger(__name__)

    # Find the first text block — content may contain thinking or other block types
    raw = ""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            raw = block.text.strip()
            break

    _log.debug("smart_create raw response: %r", raw)

    if not raw:
        _log.error("smart_create: empty response. Full content: %r", response.content)
        raise ValueError(f"Claude returned an empty response. Content blocks: {[getattr(b, 'type', '?') for b in response.content]}")

    # Strip markdown code fences if the model wrapped the JSON despite instructions
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0].strip()

    # Extract JSON array even if the model prepended reasoning prose
    if not raw.startswith("["):
        start = raw.find("[")
        end   = raw.rfind("]")
        if start != -1 and end != -1 and end > start:
            raw = raw[start:end + 1]

    if not raw:
        raise ValueError("Claude returned only a code fence with no content inside.")

    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        _log.error("smart_create JSON parse failure. raw=%r exc=%s", raw, exc)
        raise ValueError(f"JSON parse failed ({exc}) — raw response was: {raw!r}") from exc

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
        "input_tokens":      input_tok,
        "output_tokens":     output_tok,
        "cache_write_tokens": cache_write_tok,
        "cache_read_tokens":  cache_read_tok,
        "total_tokens":      input_tok + output_tok + cache_write_tok + cache_read_tok,
        "cost_usd":          round(cost, 6),
        "cost_cents":        round(cost * 100, 1),
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
            "title": str(raw.get("title", "Untitled"))[:255],
            "type": tx_type,
            "value": str(value),
            "payee": str(raw.get("payee", "") or "")[:255],
            "note": str(raw.get("note", "") or ""),
            "date_due": date_due.isoformat() if date_due else "",
            "category_uid": cat_uid,
            "category_title": category_map.get(cat_uid, "—") if cat_uid else "—",
            "tag_uids": tag_uids,
            "tag_titles": [tag_map[u] for u in tag_uids],
        })

    return items, errors


def _trial_state(feuser):
    """Return (api_key, is_trial, trial_limit, trial_spent, trial_blocked).

    is_trial=True means the user has no personal key and is on the shared trial key.
    trial_blocked=True means they've hit or exceeded the limit.
    """
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
    from .ai_trial import disable_trial, notify_admin_billing, trial_is_disabled

    feuser = request.feuser
    api_key, is_trial, trial_limit, trial_spent, trial_blocked = _trial_state(feuser)

    if not api_key:
        return redirect("profile")

    trial_disabled = is_trial and trial_is_disabled()

    categories = list(Category.objects.filter(owning_feuser=feuser).values("uid", "title"))
    tags = list(Tag.objects.filter(owning_feuser=feuser).values("uid", "title"))
    context = {
        "active_nav": "express_creation",
        "description": "",
        "preview_items": None,
        "preview_json": "",
        "usage": None,
        "ai_error": None,
        "created_count": None,
        "categories": categories,
        "tags": tags,
        "is_trial": is_trial,
        "trial_limit": trial_limit,
        "trial_spent": round(trial_spent, 1),
        "trial_blocked": trial_blocked,
        "trial_disabled": trial_disabled,
    }

    if trial_disabled or trial_blocked:
        return render(request, "budget/express_creation.html", context)

    if request.method == "POST":
        action = request.POST.get("action", "parse")

        if action == "parse":
            import base64 as _base64
            description = request.POST.get("description", "").strip()
            image_b64 = ""
            image_type = "image/jpeg"
            image_file = request.FILES.get("image_file")
            if image_file:
                image_b64, image_type = _prepare_image(image_file)
            context["description"] = description
            if not description and not image_b64:
                context["ai_error"] = "Please enter a description or attach an image."
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
                    if not isinstance(raw_items, list):
                        raise ValueError("Expected a JSON array.")
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
                        context["trial_blocked"] = float(feuser.ai_trial_budget_spent) >= trial_limit
                except json.JSONDecodeError as exc:
                    import logging
                    logging.getLogger(__name__).error("smart_create JSON parse failure: %s", exc)
                    context["ai_error"] = f"Claude returned unexpected output (JSONDecodeError: {exc})."
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
            # Collect which indices the user selected (checkboxes)
            selected_indices = set(
                int(i) for i in request.POST.getlist("selected")
                if i.isdigit()
            )
            today = timezone.localdate()
            try:
                all_items = json.loads(preview_json)
                # If nothing checked, treat as all selected (fallback safety)
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
