"""Expense writes shared by the web views, the REST API and the MCP server."""
import json
from dataclasses import dataclass
from typing import Callable

from .models import Category, Expense, ExpenseDataOverlay, Tag, TransactionType
from .notifications import send_settled_notification, set_initial_notification_class


class ExpenseActionError(Exception):
    """A requested expense action is not allowed; the message names why."""


BUDDY_TYPE_CONFLICT_MSG = (
    'Contact and project expenses must be type "Expense". '
    "Change the type back to Expense, or remove the assignment, then save again."
)

# update_expense(): leave the expense's contact/project assignment as it is
KEEP_ASSIGNMENT = object()


# ---------------------------------------------------------------------------
# Contact/project assignment
# ---------------------------------------------------------------------------

def parse_assignment(feuser, *, mode, upfront_type, upfront_id, project_id, spendings, expense_type) -> dict:
    """
    Validate a contact/project assignment for an expense or recurring expense.
    Returns a dict with keys mode ('single'|'group'), upfront_type ('me'|'feuser'|'dummy'),
    upfront_feuser, upfront_dummy, group, spendings, valid, type_conflict.
    Contact mode allows at most one participant.
    """
    from buddies.models import DummyUser, Project
    from feusers.models import FeUser

    result = {
        "mode": mode,
        "upfront_type": upfront_type,
        "upfront_feuser": None,
        "upfront_dummy": None,
        "group": None,
        "valid": True,
        "type_conflict": False,
    }

    # shared expenses feed the debt graph, where income/savings would invert who owes whom
    if expense_type != TransactionType.EXPENSE:
        result["valid"] = False
        result["type_conflict"] = True

    if upfront_type == "feuser":
        try:
            result["upfront_feuser"] = FeUser.objects.get(pk=int(upfront_id or 0), is_active=True)
        except (ValueError, TypeError, FeUser.DoesNotExist):
            result["valid"] = False
    elif upfront_type == "dummy":
        try:
            result["upfront_dummy"] = DummyUser.objects.get(pk=int(upfront_id or 0))
        except (ValueError, TypeError, DummyUser.DoesNotExist):
            result["valid"] = False

    if mode == "group":
        try:
            result["group"] = Project.objects.get(
                uid=int(project_id or 0), members__feuser=feuser, archived=False,
            )
        except (ValueError, TypeError, Project.DoesNotExist):
            result["valid"] = False

    result["spendings"] = spendings if isinstance(spendings, list) else []

    # any project expense may have zero participants (payer covers the cost alone)
    is_project_expense = mode == "group" and bool(result["group"])
    if not result["spendings"] and not is_project_expense:
        result["valid"] = False

    if mode == "single" and len(result["spendings"]) > 1:
        result["valid"] = False

    # every referenced payer/participant must be within the acting user's connected set
    if result["valid"]:
        from buddies.services import BuddyExpenseService
        if not BuddyExpenseService.validate_buddy_identities(
            feuser,
            group=result["group"],
            upfront_feuser=result["upfront_feuser"],
            upfront_dummy=result["upfront_dummy"],
            spendings=result["spendings"],
        ):
            result["valid"] = False

    return result


def parse_assignment_post(post, feuser):
    """parse_assignment() fed from the expense/recurring form POST; None when no assignment is set."""
    if not post.get("buddy_payment"):
        return None
    try:
        spendings = json.loads(post.get("buddy_spendings_json", "[]"))
    except (json.JSONDecodeError, ValueError):
        spendings = []
    return parse_assignment(
        feuser,
        mode=post.get("buddy_mode", "single"),
        upfront_type=post.get("buddy_upfront_type", "me"),
        upfront_id=post.get("buddy_upfront_id", 0),
        project_id=post.get("project_id", 0),
        spendings=spendings,
        expense_type=post.get("type"),
    )


def current_assignment(expense, feuser):
    """The assignment the expense form would post for an unchanged expense; None when unshared."""
    if not (expense.buddy_spendings.exists() or expense.is_dummy or expense.project_id):
        return None
    spendings = []
    for bs in expense.buddy_spendings.all():
        if bs.participant_feuser_id:
            spendings.append({"type": "feuser", "id": bs.participant_feuser_id, "share_percent": float(bs.share_percent)})
        else:
            spendings.append({"type": "dummy", "id": bs.participant_dummy_id, "share_percent": float(bs.share_percent)})
    return {
        "mode": "group" if expense.project_id else "single",
        "upfront_type": "dummy" if expense.is_dummy else "me",
        "upfront_feuser": None,
        "upfront_dummy": expense.upfront_payee_dummy if expense.is_dummy else None,
        "group": expense.project,
        "spendings": spendings,
        "valid": True,
        "type_conflict": False,
    }


def apply_solo_spendings(expense, buddy, creator_feuser):
    """Solo project without participants: the creator carries 100%."""
    if buddy and buddy["mode"] == "group" and not buddy["spendings"] and buddy.get("group"):
        project = buddy["group"]
        feuser_count = project.members.filter(feuser__isnull=False).count()
        dummy_count = project.members.filter(dummy__isnull=False).count()
        if feuser_count == 1 and dummy_count == 0:
            from buddies.models import BuddySpending
            BuddySpending.objects.filter(expense=expense).delete()
            BuddySpending.objects.create(
                expense=expense,
                participant_feuser=creator_feuser,
                share_percent=100,
            )


# ---------------------------------------------------------------------------
# Create / update / delete
# ---------------------------------------------------------------------------

def save_new_expense(feuser, expense, tags, buddy) -> Expense:
    """
    Persist an unsaved, validated expense with its tags and optional assignment.
    `expense` carries feuser's own category; when another feuser paid upfront the
    expense moves to them and feuser keeps their classification as an overlay.
    """
    from buddies.services import BuddyEmailService, BuddyExpenseService, BuddyTrustService
    from .services import create_participant_overlays, upsert_overlay

    if buddy and buddy["upfront_type"] == "feuser" and buddy["upfront_feuser"]:
        other = buddy["upfront_feuser"]
        expense.owning_feuser = other
        expense.buddy_approved = False
        expense.project = buddy.get("group")
        expense.save()
        expense.tags.set(tags)
        upsert_overlay(expense, feuser, expense.category, list(tags))
        BuddyExpenseService.reconcile_categories_tags(expense, other)
        expense.save(update_fields=["category"])
        apply_solo_spendings(expense, buddy, feuser)
        BuddyExpenseService.set_buddy_spendings(expense, buddy["spendings"], acting_feuser=feuser)
        create_participant_overlays(expense)
        BuddyTrustService.record_action(expense, feuser)
        if not expense.buddy_approved:
            BuddyEmailService.send_expense_approval_request(expense, feuser)
        BuddyEmailService.notify_expense_created(expense, feuser)
        if expense.project:
            expense.project.update_lastmod()
    else:
        expense.owning_feuser = feuser
        if buddy:
            expense.is_dummy = buddy["upfront_type"] == "dummy"
            expense.upfront_payee_dummy = buddy.get("upfront_dummy")
            expense.project = buddy.get("group")
            # a non-admin naming a project's offline member as payer needs admin approval
            if (buddy["upfront_type"] == "dummy"
                    and expense.project
                    and expense.project.admin_feuser_id != feuser.pk):
                expense.buddy_approved = False
        expense.save()
        expense.tags.set(tags)
        if buddy:
            apply_solo_spendings(expense, buddy, feuser)
            BuddyExpenseService.set_buddy_spendings(expense, buddy["spendings"], acting_feuser=feuser)
            create_participant_overlays(expense)
            BuddyTrustService.record_action(expense, feuser)
            BuddyEmailService.notify_expense_created(expense, feuser)
            if expense.project:
                expense.project.update_lastmod()
    set_initial_notification_class(expense)
    return expense


def editable_expense(feuser, uid):
    """
    The expense feuser may edit, and whether that is a project admin editing an
    offline member's expense. Raises Expense.DoesNotExist or ExpenseActionError.
    """
    expense = Expense.objects.filter(uid=uid, owning_feuser=feuser).first()
    is_admin_edit = False
    if expense is None:
        expense = Expense.objects.get(uid=uid, is_dummy=True, project__admin_feuser=feuser)
        is_admin_edit = True
    if expense.is_buddies_settlement and not expense.settlement_can_edit:
        raise ExpenseActionError("This settlement is confirmed and can no longer be edited.")
    if (not is_admin_edit
            and expense.is_buddies_settlement
            and expense.buddy_approved
            and expense.project_id
            and expense.project.admin_feuser_id != feuser.pk):
        raise ExpenseActionError("Only the project admin can edit an approved project settlement.")
    return expense, is_admin_edit


def update_expense(feuser, expense, apply_fields: Callable[[], None], buddy, *, is_admin_edit=False) -> bool:
    """
    Apply a validated edit. `apply_fields` saves the plain fields and tags;
    `buddy` is the new assignment, None to unshare, or KEEP_ASSIGNMENT.
    Title, value, participant or share changes reset participant approvals.
    Returns True when the expense moved to another owner.
    """
    from buddies.models import BuddySpending
    from buddies.services import BuddyEmailService, BuddyExpenseService, BuddyTrustService

    if buddy is KEEP_ASSIGNMENT:
        buddy = current_assignment(expense, feuser)

    # form validation already wrote the new values onto `expense`, so compare against the stored row
    before = Expense.objects.only("title", "value", "settled").get(pk=expense.pk)
    was_settled = before.settled
    old_title = before.title
    old_value = before.value
    old_participants = {
        bs.participant_feuser_id: (bs.participant_feuser, bs.share_percent)
        for bs in expense.buddy_spendings.select_related("participant_feuser").filter(participant_feuser__isnull=False)
    }
    old_spend_sig = BuddyExpenseService.spend_signature(expense)
    old_approvals = BuddyExpenseService.snapshot_approvals(expense)
    # only participants who had approved are told their approval was reset
    prev_approved_pks = {
        pid for (ptype, pid), (state, _c) in old_approvals.items()
        if ptype == "feuser" and state == BuddySpending.APPROVAL_APPROVED
    }
    extra_notify = expense.owning_feuser if is_admin_edit else None

    pre_edit_project = expense.project
    apply_fields()
    if buddy:
        new_type = buddy["upfront_type"]
        new_feuser = buddy.get("upfront_feuser")
        new_dummy = buddy.get("upfront_dummy")
        expense.project = buddy.get("group")
        expense.save(update_fields=["project"])
        payer_changed = (
            (new_type == "feuser" and new_feuser and new_feuser.pk != feuser.pk) or
            (new_type == "dummy" and new_dummy and new_dummy != expense.upfront_payee_dummy) or
            (new_type == "me" and expense.is_dummy)
        )
        if payer_changed:
            expense = BuddyExpenseService.change_upfront_payer(
                expense,
                new_payer_feuser=(new_feuser if new_type == "feuser" else None),
                new_payer_dummy=(new_dummy if new_type == "dummy" else None),
            )
            if new_type == "dummy" and new_dummy:
                proj = buddy.get("group")
                if proj and proj.admin_feuser_id != feuser.pk:
                    expense.buddy_approved = False
                    expense.save(update_fields=["buddy_approved"])
            if new_type == "feuser" and new_feuser:
                # ownership changed hands, so no remaining approval applies
                BuddyExpenseService.reset_participant_approvals(expense)
                BuddyTrustService.record_action(expense, feuser)
                if not expense.buddy_approved:
                    BuddyEmailService.send_expense_approval_request(expense, feuser)
                BuddyEmailService.notify_expense_updated(
                    expense, feuser, old_title, old_value, old_participants,
                    extra_notify_feuser=extra_notify,
                    reset_participant_pks=prev_approved_pks,
                )
                return True
        approval_reset = False
        # a settlement's creditor share never changes
        if not expense.is_buddies_settlement:
            apply_solo_spendings(expense, buddy, feuser)
            BuddyExpenseService.set_buddy_spendings(expense, buddy["spendings"], acting_feuser=feuser)
            approval_reset = (
                payer_changed
                or old_title != expense.title
                or old_value != expense.value
                or old_spend_sig != BuddyExpenseService.spend_signature(expense)
            )
            if approval_reset:
                BuddyExpenseService.reset_participant_approvals(expense)
                BuddyTrustService.record_action(expense, feuser)
            else:
                BuddyExpenseService.restore_approvals(expense, old_approvals)
        BuddyEmailService.notify_expense_updated(
            expense, feuser, old_title, old_value, old_participants,
            extra_notify_feuser=extra_notify,
            reset_participant_pks=(prev_approved_pks if approval_reset else set()),
        )
        if expense.project:
            expense.project.update_lastmod()
        if pre_edit_project and pre_edit_project != expense.project:
            pre_edit_project.update_lastmod()
    else:
        expense.buddy_spendings.all().delete()
        expense.is_dummy = False
        expense.buddy_approved = True
        expense.upfront_payee_dummy = None
        expense.project = None
        expense.save(update_fields=["is_dummy", "buddy_approved", "upfront_payee_dummy", "project"])
        if pre_edit_project:
            pre_edit_project.update_lastmod()
        if old_participants:
            BuddyEmailService.notify_expense_updated(
                expense, feuser, old_title, old_value, old_participants,
                extra_notify_feuser=extra_notify,
            )

    if expense.is_buddies_settlement and not expense.buddy_approved:
        BuddyTrustService.record_action(expense, feuser)
        # pre-edit snapshot: the form auto-adds the editor as participant for an offline payer
        creditor = next(
            (fu for (fu, _) in old_participants.values() if fu.pk != expense.owning_feuser_id),
            None,
        )
        if creditor:
            BuddyEmailService.send_settlement_updated_notification(expense, creditor)
    if not was_settled and expense.settled:
        send_settled_notification(expense)
    else:
        set_initial_notification_class(expense)
    return False


def delete_expense(feuser, expense) -> None:
    """Delete one of feuser's own expenses, applying the settlement rules."""
    from buddies.services import BuddyEmailService

    if expense.is_buddies_settlement:
        if not expense.settlement_can_delete:
            raise ExpenseActionError("This settlement is confirmed and can no longer be deleted.")
        if expense.buddy_approved and expense.project_id and expense.project.admin_feuser_id != feuser.pk:
            raise ExpenseActionError("Only the project admin can delete an approved project settlement.")
        if not expense.buddy_approved:
            bs = expense.buddy_spendings.select_related("participant_feuser").filter(
                participant_feuser__isnull=False
            ).first()
            if bs:
                BuddyEmailService.send_settlement_cancelled_notification(expense, bs.participant_feuser)
    project = expense.project
    expense.delete()
    if project:
        project.update_lastmod()


def settle_expense(expense) -> None:
    if not expense.settled:
        expense.settled = True
        expense.save(update_fields=["settled"])
        send_settled_notification(expense)


def clone_expense(feuser, original) -> Expense:
    """Copy one of feuser's own expenses, participants included, titled "CLONE - ..."."""
    from buddies.models import BuddySpending
    from buddies.services import BuddyEmailService, BuddyTrustService

    if original.is_buddies_settlement:
        raise ExpenseActionError("Settlements cannot be cloned.")
    tags = list(original.tags.all())
    spendings = list(original.buddy_spendings.all())
    project = original.project
    original.pk = None
    original.title = f"CLONE - {original.title}"
    original.initiated_by_feuser = feuser
    original.save()
    original.tags.set(tags)
    if spendings:
        BuddySpending.objects.bulk_create([
            BuddySpending(
                expense=original,
                participant_feuser=bs.participant_feuser,
                participant_dummy=bs.participant_dummy,
                share_percent=bs.share_percent,
            )
            for bs in spendings
        ])
        BuddyTrustService.record_action(original, feuser)
        BuddyEmailService.notify_expense_created(original, feuser)
        if project:
            project.update_lastmod()
    return original


# ---------------------------------------------------------------------------
# Overlays (a participant's own classification of a foreign expense)
# ---------------------------------------------------------------------------

def participant_expense(feuser, uid) -> Expense:
    """A foreign expense feuser participates in. Raises Expense.DoesNotExist."""
    return Expense.objects.filter(uid=uid, buddy_spendings__participant_feuser=feuser).distinct().get()


def set_overlay(feuser, expense, category, tags, note=None) -> None:
    from .services import upsert_overlay
    upsert_overlay(expense, feuser, category, list(tags), note=note)


def _overlay_parts(expense, feuser):
    overlay = ExpenseDataOverlay.objects.filter(expense=expense, feuser=feuser).first()
    if not overlay:
        return None, [], None
    return overlay.category, list(overlay.tags.all()), overlay.note


# ---------------------------------------------------------------------------
# Bulk actions
# ---------------------------------------------------------------------------

BULK_ACTIONS = ("settle", "unsettle", "delete", "add-tag", "remove-tag", "set-category")


@dataclass
class BulkResult:
    updated: int
    foreign: int
    via_overlay: int


def _accessible_foreign_expenses(foreign_uids, feuser):
    return list(
        Expense.objects.filter(
            uid__in=foreign_uids, is_dummy=False, buddy_spendings__participant_feuser=feuser,
        ).distinct()
    )


def bulk_action(feuser, action, uids, *, tag_uid=None, category_uid=None) -> BulkResult:
    """
    Apply one action to many expenses. Own expenses change directly; tag and
    category actions on foreign expenses go to feuser's overlay. Settlements are
    never bulk deleted. Raises ExpenseActionError for an unknown action, tag or category.
    """
    if action not in BULK_ACTIONS:
        raise ExpenseActionError(f"Unknown bulk action '{action}'.")
    tag = category = None
    if action in ("add-tag", "remove-tag"):
        try:
            tag = Tag.objects.get(uid=int(tag_uid), owning_feuser=feuser)
        except (Tag.DoesNotExist, ValueError, TypeError):
            raise ExpenseActionError(f"Tag {tag_uid} not found.")
    if action == "set-category" and category_uid:
        try:
            category = Category.objects.get(uid=int(category_uid), owning_feuser=feuser)
        except (Category.DoesNotExist, ValueError, TypeError):
            raise ExpenseActionError(f"Category {category_uid} not found.")

    qs = Expense.objects.filter(owning_feuser=feuser, uid__in=uids, is_dummy=False)
    own_ids = set(qs.values_list("uid", flat=True))
    foreign_uids = [u for u in uids if u not in own_ids]
    via_overlay = 0
    updated = len(own_ids)

    if action == "settle":
        if len(uids) == 1:
            single = qs.filter(settled=False).select_related("owning_feuser").first()
            qs.update(settled=True)
            if single:
                single.settled = True
                send_settled_notification(single)
        else:
            qs.update(settled=True)
    elif action == "unsettle":
        qs.update(settled=False)
    elif action == "delete":
        from buddies.models import Project
        qs_del = qs.exclude(is_buddies_settlement=True)
        updated = qs_del.count()
        project_pks = set(qs_del.filter(project__isnull=False).values_list("project_id", flat=True))
        qs_del.delete()
        for project in Project.objects.filter(pk__in=project_pks):
            project.update_lastmod()
    elif action in ("add-tag", "remove-tag"):
        if action == "add-tag":
            Expense.tags.through.objects.bulk_create(
                [Expense.tags.through(expense_id=eid, tag_id=tag.pk) for eid in own_ids],
                ignore_conflicts=True,
            )
        else:
            Expense.tags.through.objects.filter(expense_id__in=own_ids, tag_id=tag.pk).delete()
        if foreign_uids:
            accessible = _accessible_foreign_expenses(foreign_uids, feuser)
            for exp in accessible:
                cat, tags, note = _overlay_parts(exp, feuser)
                if action == "add-tag":
                    if tag not in tags:
                        tags.append(tag)
                elif not tags and cat is None and note is None:
                    continue
                else:
                    tags = [t for t in tags if t.pk != tag.pk]
                set_overlay(feuser, exp, cat, tags, note)
            via_overlay = len(accessible)
    elif action == "set-category":
        qs.update(category=category)
        if foreign_uids:
            accessible = _accessible_foreign_expenses(foreign_uids, feuser)
            for exp in accessible:
                _cat, tags, note = _overlay_parts(exp, feuser)
                set_overlay(feuser, exp, category, tags, note)
            via_overlay = len(accessible)

    return BulkResult(updated=updated, foreign=len(foreign_uids), via_overlay=via_overlay)
