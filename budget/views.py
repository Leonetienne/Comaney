import json
from decimal import Decimal, InvalidOperation

from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .decorators import feuser_required
from .expense_factory import create_expense
from .forms import ExpenseForm, ScheduledExpenseForm
from .models import Category, Expense, ScheduledExpense, Tag, TransactionType


@feuser_required
def dashboard(request):
    feuser = request.feuser
    today = timezone.localdate()
    month_qs = Expense.objects.filter(
        owning_feuser=feuser,
        date_created__year=today.year,
        date_created__month=today.month,
    )

    def _sum(qs):
        return qs.aggregate(t=Sum("value"))["t"] or Decimal("0")

    income      = _sum(month_qs.filter(type="income"))
    paid        = _sum(month_qs.filter(type="expense", settled=True))
    outstanding = _sum(month_qs.filter(type="expense", settled=False))
    left        = income - paid - outstanding

    return render(request, "budget/dashboard.html", {
        "active_nav": "dashboard",
        "income": income,
        "paid": paid,
        "outstanding": outstanding,
        "left": left,
        "month_label": today.strftime("%B %Y"),
    })


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
def expenses_list(request):
    expenses = (
        Expense.objects.filter(owning_feuser=request.feuser)
        .select_related("category")
        .prefetch_related("tags")
    )
    return render(request, "budget/expenses_list.html", {
        "active_nav": "expenses",
        "expenses": expenses,
    })


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
    expense.delete()
    return redirect("budget:expenses_list")


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
        form = ScheduledExpenseForm(feuser=request.feuser, initial={"type": "expense"})
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


# ---------------------------------------------------------------------------
# Smart Create (AI)
# ---------------------------------------------------------------------------

_SMART_CREATE_SYSTEM = """You are a financial data-entry assistant for a budgeting app.
The user may provide an image (receipt, invoice, order confirmation, etc.), a text description, or both.
Your job is to extract every expense or income item and return a JSON array of expense objects.

If an image is provided:
- Read every distinct line item from the receipt or document.
- Use the user's text (if any) as additional context or filtering instructions.
- Group items intelligently using the available categories and tags: for example, a supermarket receipt may contain groceries, household cleaning products, and personal care items — split them into separate expense objects assigned to fitting categories rather than one combined total. Items of the same category and tags should stay within the same expense item!
- The payee is typically the store or vendor name shown on the receipt header.

Rules:
- Return ONLY a valid JSON array — no prose, no markdown, no code fences.
- Each object must have exactly these keys:
    "title"        — as short as possible (2–4 words max, e.g. "Groceries", "Netflix sub", "Diesel")
    "type"         — "expense" or "income"
    "value"        — positive decimal number (e.g. 9.99)
    "payee"        — merchant or person name, or "" if unknown
    "category_uid" — integer uid from the Categories list below, or null if none fits
    "tag_uids"     — array of integer uids from the Tags list below (can be [])
    "note"         — any extra context worth keeping, or ""
- Only use category_uid and tag_uids values that appear in the lists below.
- If the user mentions a single lump sum for multiple things, split them into separate objects.
- Default type to "expense" unless the description clearly indicates income.

{catalog}"""

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


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
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": content}],
    )
    raw = response.content[0].text.strip()
    items = json.loads(raw)

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
        "cost_str":          f"${cost:.4f}" if cost >= 0.0001 else "<$0.0001",
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
        if tx_type not in ("expense", "income"):
            tx_type = "expense"

        cat_uid = raw.get("category_uid")
        if cat_uid not in valid_category_uids:
            cat_uid = None

        tag_uids = [u for u in (raw.get("tag_uids") or []) if u in valid_tag_uids]

        items.append({
            "title": str(raw.get("title", "Untitled"))[:255],
            "type": tx_type,
            "value": str(value),
            "payee": str(raw.get("payee", "") or "")[:255],
            "note": str(raw.get("note", "") or ""),
            "category_uid": cat_uid,
            "category_title": category_map.get(cat_uid, "—") if cat_uid else "—",
            "tag_uids": tag_uids,
            "tag_titles": [tag_map[u] for u in tag_uids],
        })

    return items, errors


@feuser_required
def smart_create(request):
    feuser = request.feuser
    if not feuser.anthropic_api_key:
        return redirect("profile")

    categories = list(Category.objects.filter(owning_feuser=feuser).values("uid", "title"))
    tags = list(Tag.objects.filter(owning_feuser=feuser).values("uid", "title"))
    context = {
        "active_nav": "smart_create",
        "description": "",
        "preview_items": None,
        "preview_json": "",
        "usage": None,
        "ai_error": None,
        "created_count": None,
        "categories": categories,
        "tags": tags,
    }

    if request.method == "POST":
        action = request.POST.get("action", "parse")

        if action == "parse":
            import base64 as _base64
            description = request.POST.get("description", "").strip()
            image_b64 = ""
            image_type = "image/jpeg"
            image_file = request.FILES.get("image_file")
            if image_file:
                image_type = image_file.content_type or "image/jpeg"
                if image_type not in _ALLOWED_IMAGE_TYPES:
                    image_type = "image/jpeg"
                image_b64 = _base64.b64encode(image_file.read()).decode("utf-8")
            context["description"] = description
            if not description and not image_b64:
                context["ai_error"] = "Please enter a description or attach an image."
            else:
                catalog = _build_catalog(feuser)
                system_prompt = _SMART_CREATE_SYSTEM.format(catalog=catalog)
                try:
                    raw_items, usage = _call_claude(
                        feuser.anthropic_api_key, system_prompt, description,
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
                except json.JSONDecodeError:
                    context["ai_error"] = "Claude returned an unexpected format. Please rephrase and try again."
                except Exception as exc:
                    context["ai_error"] = f"AI error: {exc}"

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

                    create_expense(
                        owning_feuser=feuser,
                        title=item["title"],
                        type=TransactionType(item["type"]),
                        value=Decimal(item["value"]),
                        payee=item.get("payee", ""),
                        note=item.get("note", ""),
                        category=category,
                        tags=tags or None,
                        date_due=today,
                        settled=True,
                    )
                    count += 1
                context["created_count"] = count
            except Exception as exc:
                context["ai_error"] = f"Could not save expenses: {exc}"

    return render(request, "budget/smart_create.html", context)
