import json
import logging
from datetime import date
from decimal import Decimal

from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from ..ai_service import (
    AIAuthenticationError,
    AIBillingError,
    AIBudgetExceededError,
    AIInvalidResponseError,
    AIRefusalError,
    AIService,
    AITransientError,
)
from ..decorators import feuser_required
from ..express_service import (
    _build_catalog,
    _parse_buddy_item,
    _prepare_image,
    _select_smart_create_blocks,
    _validate_items,
    build_express_system_prompt,
)
from ..expense_factory import create_expense
from ..models import Category, Tag, TransactionType
from .expenses import _buddy_context

_log = logging.getLogger(__name__)


@feuser_required
def express_creation(request):
    from ..ai_trial import trial_is_disabled

    feuser = request.feuser
    api_key, is_trial, trial_limit, trial_spent, trial_blocked = AIService.trial_state_for(feuser)

    if not api_key:
        return redirect("profile")

    trial_disabled = is_trial and trial_is_disabled()

    categories = list(Category.objects.filter(owning_feuser=feuser).values("uid", "title"))
    tags = list(Tag.objects.filter(owning_feuser=feuser).values("uid", "title"))
    context = {
        "active_nav":         "express_creation",
        "description":        request.GET.get("prefill", "") if request.method != "POST" else "",
        "preview_items":      None,
        "preview_json":       "",
        "usage":              None,
        "ai_error":           None,
        "ai_error_overloaded": False,
        "ai_error_detail":    "",
        "created_count":      None,
        "view_expenses_url":  None,
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
                # Reuse this same request's buddy-widget data (context["projects_data"]/
                # ["single_buddies_data"]) for the catalog, so the AI's idx values always
                # line up with the widget's own member/buddy arrays -- see _build_catalog.
                catalog = _build_catalog(feuser, context["projects_data"], context["single_buddies_data"])
                blocks = _select_smart_create_blocks(context["projects_data"], context["single_buddies_data"])
                system_prompt = build_express_system_prompt(catalog, blocks, feuser.ai_custom_instructions)
                today_str = timezone.localdate().isoformat()
                description_with_date = f"[Today's date: {today_str}]\n\n{description}" if description else f"[Today's date: {today_str}]"

                service = None
                try:
                    service = AIService(feuser)
                    raw_items = service.prompt_express_expense_gen(
                        system_prompt, description_with_date,
                        image_b64=image_b64, image_type=image_type,
                    )
                    items, errors = _validate_items(
                        raw_items, feuser, context["projects_data"], context["single_buddies_data"]
                    )
                    if errors:
                        context["ai_error"] = " | ".join(errors)
                    if items:
                        context["preview_items"] = items
                        context["preview_json"] = json.dumps(items)
                except AIRefusalError as exc:
                    context["ai_error"] = str(exc)
                    context["ai_raw_output"] = exc.raw
                except AIInvalidResponseError as exc:
                    # A JSON-repair fallback may have been attempted (see
                    # AIService._call_and_repair) and still ultimately failed --
                    # real tokens may have been spent on both calls; AIService
                    # already billed that combined cost before raising.
                    _log.error("smart_create invalid response: cause=%s raw=%r", exc.cause, exc.raw)
                    context["ai_raw_output"] = exc.raw
                except AIBillingError as exc:
                    if is_trial:
                        context["trial_disabled"] = True
                    else:
                        context["ai_error"] = str(exc)
                except AIAuthenticationError as exc:
                    context["ai_error"] = str(exc)
                except AITransientError as exc:
                    if exc.overloaded:
                        context["ai_error_overloaded"] = True
                        context["ai_error_detail"] = exc.detail
                    else:
                        context["ai_error"] = str(exc)
                except AIBudgetExceededError as exc:
                    context["ai_error"] = str(exc) or "AI budget exceeded."
                except Exception as exc:
                    context["ai_error"] = f"Unexpected error: {exc}"

                if service is not None:
                    if service.last_usage:
                        context["usage"] = service.last_usage
                    if service.is_trial:
                        context["trial_spent"] = round(service.trial_spent, 1)
                        if service.trial_spent >= trial_limit:
                            context["trial_just_exhausted"] = True

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
                # Track where each saved expense landed so the success banner's
                # "View expenses" link can jump to the most relevant place:
                # ("buddy", None) = direct buddy; ("project", uid); ("personal", None).
                created_targets: list[tuple[str, int | None]] = []
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

                    project = None
                    if not buddy:
                        project_uid = item.get("project_uid")
                        if project_uid:
                            from buddies.models import Project
                            try:
                                project = Project.objects.get(
                                    uid=project_uid, members__feuser=feuser, archived=False
                                )
                            except Project.DoesNotExist:
                                pass

                    # Buddy/project assignment only makes sense for type=expense (see
                    # budget/expense_factory.py); the preview UI lets the AI/user pick
                    # type and assignment independently, so force it here rather than
                    # reject the whole batch.
                    item_type = TransactionType(item["type"])
                    if (buddy or project) and item_type != TransactionType.EXPENSE:
                        item_type = TransactionType.EXPENSE

                    common_kwargs = dict(
                        title=item["title"],
                        type=item_type,
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
                            project=buddy["group"],
                            buddy_spendings=buddy["spendings"],
                            **common_kwargs,
                        )
                        BuddyEmailService.send_expense_approval_request(expense, feuser)
                        BuddyEmailService.notify_expense_created(expense, feuser)
                    elif buddy:
                        expense = create_expense(
                            owning_feuser=feuser,
                            is_dummy=(buddy["upfront_type"] == "dummy"),
                            upfront_payee_dummy=buddy["upfront_dummy"],
                            project=buddy["group"],
                            buddy_spendings=buddy["spendings"],
                            **common_kwargs,
                        )
                        from buddies.services import BuddyEmailService
                        BuddyEmailService.notify_expense_created(expense, feuser)
                    else:
                        create_expense(owning_feuser=feuser, project=project, **common_kwargs)

                    if buddy:
                        grp = buddy["group"]
                        created_targets.append(("project", grp.uid) if grp else ("buddy", None))
                    elif project:
                        created_targets.append(("project", project.uid))
                    else:
                        created_targets.append(("personal", None))
                    count += 1
                if not context.get("ai_error"):
                    redirect_url = f"{request.path}?created={count}"
                    kinds = {t[0] for t in created_targets}
                    if created_targets and kinds == {"buddy"}:
                        redirect_url += "&view=buddies"
                    elif created_targets and kinds == {"project"}:
                        project_ids = {t[1] for t in created_targets}
                        if len(project_ids) == 1:
                            redirect_url += f"&view=project&pid={project_ids.pop()}"
                    return redirect(redirect_url)
                context["created_count"] = count
            except Exception as exc:
                context["ai_error"] = f"Could not save expenses: {exc}"

    if not context["created_count"] and request.GET.get("created", "").isdigit():
        context["created_count"] = int(request.GET["created"])

    view = request.GET.get("view")
    if view == "buddies":
        context["view_expenses_url"] = reverse("buddies:buddy_summary")
    elif view == "project" and request.GET.get("pid", "").isdigit():
        context["view_expenses_url"] = reverse(
            "projects:project_detail", args=[int(request.GET["pid"])]
        )

    return render(request, "budget/express_creation.html", context)
