import json
from datetime import date
from decimal import Decimal

from django.shortcuts import redirect, render
from django.utils import timezone

from ..decorators import feuser_required
from ..express_service import (
    AIInvalidResponseError,
    AIRefusalError,
    _SMART_CREATE_SYSTEM,
    _build_catalog,
    _call_claude,
    _parse_buddy_item,
    _prepare_image,
    _trial_state,
    _validate_items,
)
from ..expense_factory import create_expense
from ..models import Category, Tag, TransactionType
from .expenses import _buddy_context

import logging
_log = logging.getLogger(__name__)


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
    context.update(_buddy_context(feuser))

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

                    buddy = _parse_buddy_item(item, feuser)

                    common_kwargs = dict(
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

                    if buddy and buddy["upfront_type"] == "feuser" and buddy["upfront_feuser"]:
                        from buddies.services import BuddyEmailService
                        expense = create_expense(
                            owning_feuser=buddy["upfront_feuser"],
                            buddy_approved=False,
                            buddy_group=buddy["group"],
                            buddy_spendings=buddy["spendings"],
                            **common_kwargs,
                        )
                        BuddyEmailService.send_expense_approval_request(expense, feuser)
                    elif buddy:
                        create_expense(
                            owning_feuser=feuser,
                            is_dummy=(buddy["upfront_type"] == "dummy"),
                            upfront_payee_dummy=buddy["upfront_dummy"],
                            buddy_group=buddy["group"],
                            buddy_spendings=buddy["spendings"],
                            **common_kwargs,
                        )
                    else:
                        create_expense(owning_feuser=feuser, **common_kwargs)
                    count += 1
                if not context.get("ai_error"):
                    return redirect(f"{request.path}?created={count}")
                context["created_count"] = count
            except Exception as exc:
                context["ai_error"] = f"Could not save expenses: {exc}"

    if not context["created_count"] and request.GET.get("created", "").isdigit():
        context["created_count"] = int(request.GET["created"])

    return render(request, "budget/express_creation.html", context)
