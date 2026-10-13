"""
Confirmations and rejections on shared expenses, plus project expense removal.
Shared by the web views, the REST API and the MCP server.
"""
from django.utils import timezone

from ..models import BuddySpending, Project
from .email import BuddyEmailService
from .lifecycle import BuddyLifecycleService


class ApprovalError(Exception):
    """A refused approval action; `status` is the matching HTTP status."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class NotFound(ApprovalError):
    def __init__(self, message="Expense not found."):
        super().__init__(message, 404)


def _expense(**filters):
    from budget.models import Expense
    expense = Expense.objects.filter(**filters).distinct().first()
    if expense is None:
        raise NotFound()
    return expense


# ---------------------------------------------------------------------------
# "Did you pay for this?" (feuser recorded as upfront payer by someone else)
# ---------------------------------------------------------------------------

def confirm_paid(feuser, expense_id):
    expense = _expense(uid=expense_id, owning_feuser=feuser, buddy_approved=False, is_buddies_settlement=False)
    BuddyLifecycleService.approve_expense(expense)
    return expense


def reject_paid(feuser, expense_id):
    """feuser did not pay: their participation goes and the remaining shares are redistributed."""
    expense = _expense(uid=expense_id, owning_feuser=feuser, buddy_approved=False)
    BuddyLifecycleService.reject_expense(expense, feuser)
    return expense


# ---------------------------------------------------------------------------
# Settlement receipt (feuser is the creditor)
# ---------------------------------------------------------------------------

def _creditor_settlement(creditor, expense_id):
    return _expense(
        uid=expense_id, buddy_approved=False, is_buddies_settlement=True,
        buddy_spendings__participant_feuser=creditor,
    )


def confirm_settlement(creditor, expense_id):
    """The creditor received the money; books their "Settlement received" income."""
    expense = _creditor_settlement(creditor, expense_id)
    BuddyLifecycleService.confirm_settlement(expense, creditor)
    BuddyEmailService.send_settlement_approved_notification(expense, creditor, expense.owning_feuser)
    return expense


def reject_settlement(creditor, expense_id):
    """The creditor did not receive the money: the debtor's settlement is deleted and they are emailed."""
    expense = _creditor_settlement(creditor, expense_id)
    project = expense.project
    BuddyEmailService.send_settlement_rejection_notification(expense, creditor, expense.owning_feuser)
    expense.delete()
    if project:
        project.update_lastmod()
    return project


# ---------------------------------------------------------------------------
# Project admin deciding for an offline member
# ---------------------------------------------------------------------------

def _admin_offline_expense(admin, project_id, expense_id):
    project = Project.objects.filter(uid=project_id, admin_feuser=admin).first()
    if project is None:
        raise ApprovalError("Only the project admin can decide for offline members.", 403)
    expense = _expense(uid=expense_id, project=project, buddy_approved=False)
    return project, expense


def admin_confirm(admin, project_id, expense_id) -> bool:
    """
    Confirm an expense paid upfront by an offline member, or a settlement to one.
    Returns True for an offline-paid expense, False for a settlement.
    """
    project, expense = _admin_offline_expense(admin, project_id, expense_id)
    has_dummy_upfront = bool(expense.is_dummy and expense.upfront_payee_dummy_id)
    has_dummy_creditor = expense.buddy_spendings.filter(participant_dummy__owning_group=project).exists()
    if not (has_dummy_upfront or has_dummy_creditor):
        raise ApprovalError("This expense does not involve an offline member of this project.")
    if expense.is_buddies_settlement and expense.buddy_spendings.filter(participant_feuser__isnull=False).exists():
        raise ApprovalError("Only the creditor can confirm this settlement.", 403)
    BuddyLifecycleService.approve_expense(expense)
    return has_dummy_upfront and not expense.is_buddies_settlement


def admin_reject(admin, project_id, expense_id) -> bool:
    """
    Reject on behalf of an offline member: an offline-paid expense is removed, a
    settlement is deleted and its debtor emailed. Returns True for an offline-paid expense.
    """
    project, expense = _admin_offline_expense(admin, project_id, expense_id)
    has_dummy_upfront = bool(expense.is_dummy and expense.upfront_payee_dummy_id and not expense.is_buddies_settlement)
    has_dummy_creditor = expense.buddy_spendings.filter(participant_dummy__owning_group=project).exists()
    if not (has_dummy_creditor or has_dummy_upfront):
        raise ApprovalError("This expense does not involve an offline member of this project.")
    if not has_dummy_upfront:
        BuddyEmailService.send_settlement_rejection_notification(expense, admin, expense.owning_feuser)
    expense.delete()
    return has_dummy_upfront


# ---------------------------------------------------------------------------
# Participant consent (the Check/X per participant)
# ---------------------------------------------------------------------------

def set_participant_consent(feuser, expense_id, approve: bool) -> BuddySpending:
    """Record feuser's consent on a shared expense they participate in; locked after 24 hours."""
    expense = _expense(uid=expense_id, is_buddies_settlement=False, buddy_spendings__participant_feuser=feuser)
    bs = expense.buddy_spendings.filter(participant_feuser=feuser).first()
    if bs is None:
        raise NotFound("feuser is not a participant of this expense.")
    if not bs.can_change_consent:
        raise ApprovalError("The decision is locked after 24 hours.", 403)
    new_state = BuddySpending.APPROVAL_APPROVED if approve else BuddySpending.APPROVAL_REJECTED
    if bs.approval_state != new_state:
        update_fields = ["approval_state", "last_mod"]
        if new_state == BuddySpending.APPROVAL_APPROVED:
            bs.consent_set_at = timezone.now()
            update_fields.append("consent_set_at")
        bs.approval_state = new_state
        bs.last_mod = timezone.now()
        bs.save(update_fields=update_fields)
        BuddyEmailService.send_participant_approval_notification(expense, feuser, new_state)
    return bs


# ---------------------------------------------------------------------------
# Removing an expense from a project
# ---------------------------------------------------------------------------

def _member_project(feuser, project_id):
    project = Project.objects.filter(uid=project_id, members__feuser=feuser).distinct().first()
    if project is None:
        raise NotFound("Project not found.")
    return project


def delete_project_expense(feuser, project_id, expense_id) -> None:
    """
    Delete an expense from a project: own expenses, and for the admin offline-paid
    expenses and their own settlements to offline members. Approved settlements stay.
    """
    from budget.models import Expense

    project = _member_project(feuser, project_id)
    is_admin = project.admin_feuser_id == feuser.pk
    dummy_pks = {m.dummy_id for m in project.members.all() if m.dummy_id}
    expense = Expense.objects.filter(uid=expense_id, project=project).first()
    if expense is None:
        raise NotFound()

    own = expense.owning_feuser_id == feuser.pk and not expense.is_dummy
    offline_paid = bool(expense.is_dummy and expense.upfront_payee_dummy_id in dummy_pks)
    own_settlement_to_offline = (
        expense.is_buddies_settlement and is_admin and own
        and expense.buddy_spendings.filter(participant_dummy_id__in=dummy_pks).exists()
    )
    if project.archived:
        raise ApprovalError("Cannot delete expenses from an archived project.", 403)
    if not (own or (is_admin and offline_paid) or own_settlement_to_offline):
        raise ApprovalError("You do not have permission to delete this expense.", 403)
    if expense.is_buddies_settlement and expense.buddy_approved:
        has_real_creditor = expense.buddy_spendings.filter(participant_feuser__isnull=False).exists()
        if not (own_settlement_to_offline or (is_admin and offline_paid and not has_real_creditor)):
            raise ApprovalError("An approved settlement cannot be deleted.", 403)
    if expense.is_buddies_settlement and not expense.buddy_approved and not own_settlement_to_offline:
        bs = expense.buddy_spendings.select_related("participant_feuser").filter(participant_feuser__isnull=False).first()
        if bs:
            BuddyEmailService.send_settlement_cancelled_notification(expense, bs.participant_feuser)
    expense.delete()
    project.update_lastmod()


def unlink_project_expense(feuser, project_id, expense_id) -> None:
    """Take an expense out of a project; it stays in its owner's list as a personal expense."""
    from budget.models import Expense

    project = _member_project(feuser, project_id)
    is_admin = project.admin_feuser_id == feuser.pk
    expense = Expense.objects.filter(uid=expense_id, project=project).first()
    if expense is None:
        raise NotFound()
    if project.archived:
        raise ApprovalError("Cannot unlink expenses from an archived project.", 403)
    own = expense.owning_feuser_id == feuser.pk and not expense.is_dummy
    if not (own or is_admin):
        raise ApprovalError("You do not have permission to unlink this expense.", 403)
    if own and not is_admin and not expense.buddy_approved and not expense.is_buddies_settlement:
        raise ApprovalError("Approve this expense before unlinking it.")

    notify = set()
    if is_admin and not own:
        if not expense.is_dummy:
            notify.add(expense.owning_feuser)
        for bs in expense.buddy_spendings.select_related("participant_feuser").all():
            if bs.participant_feuser_id and bs.participant_feuser_id != feuser.pk:
                notify.add(bs.participant_feuser)

    expense.buddy_spendings.all().delete()
    expense.project = None
    expense.is_dummy = False
    expense.upfront_payee_dummy = None
    expense.buddy_approved = True
    expense.save()
    for fu in notify:
        BuddyEmailService.send_expense_unlinked_notification(
            expense=expense, admin_feuser=feuser, group=project, notify_feuser=fu,
            is_owner=(fu.pk == expense.owning_feuser_id),
        )
