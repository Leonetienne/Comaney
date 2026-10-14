from django.utils import timezone

from budget.models import Expense
from buddies.models import BuddySpending, CatalogPartnershipInvite, DummyUser, Project
from buddies.services import BuddyQueryService, approvals, settlement_actions
from buddies.services.approvals import ApprovalError
from buddies.services.partnership_actions import OPEN_STATUSES
from buddies.services.settlement_actions import SettlementError

from .common import ID, MONEY, person_name, person_ref
from .contacts import _PERSON, person_key
from .projects import member_project
from ..registry import READ, WRITE, OpError, operation


def _run(fn):
    try:
        return fn()
    except (ApprovalError, SettlementError) as exc:
        raise OpError(str(exc), exc.status)


def _expense_ref(e):
    return {
        "id": e.uid, "title": e.title, "value": str(e.value),
        "date_due": e.date_due.isoformat() if e.date_due else None,
        "project": e.project.name if e.project_id else None,
        "recorded_by": person_name(e.initiated_by_feuser) if e.initiated_by_feuser_id else None,
    }


@operation(
    "pending_list", concern="approvals", access=READ, method="GET", path="pending/",
    description=(
        "Everything waiting for the feuser's decision: expenses recorded with them as upfront payer, "
        "settlements to confirm as creditor, shared expenses awaiting their consent, project admin decisions "
        "for offline members, and incoming contact, project and partnership invitations."
    ),
)
def pending_list(ctx, args):
    feuser = ctx.feuser
    paid = (
        Expense.objects.filter(owning_feuser=feuser, buddy_approved=False, is_buddies_settlement=False, is_dummy=False)
        .select_related("project", "initiated_by_feuser")
    )
    settlements = (
        Expense.objects.filter(buddy_approved=False, is_buddies_settlement=True, buddy_spendings__participant_feuser=feuser)
        .exclude(owning_feuser=feuser).distinct().select_related("project", "owning_feuser", "initiated_by_feuser")
    )
    consents = (
        BuddySpending.objects.filter(
            participant_feuser=feuser, approval_state=BuddySpending.APPROVAL_NEUTRAL, expense__is_buddies_settlement=False,
        ).exclude(expense__owning_feuser=feuser).select_related("expense__project", "expense__initiated_by_feuser")
    )
    admin_ids = list(Project.objects.filter(admin_feuser=feuser, archived=False).values_list("uid", flat=True))
    admin_items = (
        Expense.objects.filter(project_id__in=admin_ids, buddy_approved=False, is_dummy=True, is_buddies_settlement=False)
        | Expense.objects.filter(
            buddy_spendings__participant_dummy__owning_group_id__in=admin_ids, buddy_approved=False, is_buddies_settlement=True,
        )
    ).distinct().select_related("project", "initiated_by_feuser")
    return {
        "confirm_paid": {
            "description": "Did you pay for this? Confirm with approvals_decide kind=paid.",
            "items": [_expense_ref(e) for e in paid],
        },
        "confirm_settlement_received": {
            "description": "Did you receive this payment? Confirm with approvals_decide kind=settlement.",
            "items": [{**_expense_ref(e), "from": person_name(e.owning_feuser)} for e in settlements],
        },
        "participant_consent": {
            "description": "Shared expenses you take part in; approve or reject with approvals_decide kind=consent (locked after 24 hours).",
            "items": [
                {**_expense_ref(bs.expense), "share_percent": float(bs.share_percent)}
                for bs in consents if bs.can_change_consent
            ],
        },
        "admin_offline_decisions": {
            "description": "As project admin, decide for offline members with approvals_decide kind=admin.",
            "items": [{**_expense_ref(e), "project_id": e.project_id, "is_settlement": e.is_buddies_settlement} for e in admin_items],
        },
        "contact_invites": [
            {"id": inv.pk, "from": person_name(inv.inviter), "respond_with": "contacts_invite_respond"}
            for inv in BuddyQueryService.pending_invites_incoming(feuser)
        ],
        "project_invites": [
            {"id": inv.pk, "project": inv.group.name, "from": person_name(inv.inviting_feuser), "respond_with": "projects_invite_respond"}
            for inv in BuddyQueryService.pending_group_invites_incoming(feuser)
        ],
        "partnership_invites": [
            {"id": inv.pk, "from": person_name(inv.inviter), "respond_with": "partnership_onboarding_state, then preview and apply, or decline"}
            for inv in CatalogPartnershipInvite.objects.filter(invitee_email=feuser.email, status__in=OPEN_STATUSES).select_related("inviter")
        ],
        "checked_at": timezone.now().isoformat(),
    }


@operation(
    "approvals_decide", concern="approvals", access=WRITE, method="POST", path="pending/decide/",
    description=(
        "Answer a pending item. kind=paid: confirm or deny having paid upfront (deny removes the feuser and "
        "redistributes shares). kind=settlement: confirm or deny receiving a payment (deny deletes it and "
        "tells the debtor). kind=consent: approve or reject a shared expense. kind=admin: as project admin, "
        "confirm or reject for an offline member (reject deletes it)."
    ),
    params={
        "kind": {"type": "string", "enum": ["paid", "settlement", "consent", "admin"]},
        "expense_id": ID,
        "approve": {"type": "boolean"},
        "project_id": {**ID, "description": "Required for kind=admin."},
    },
    required=["kind", "expense_id", "approve"],
)
def approvals_decide(ctx, args):
    feuser, eid, approve = ctx.feuser, args["expense_id"], args["approve"]
    kind = args["kind"]
    if kind == "paid":
        _run(lambda: (approvals.confirm_paid if approve else approvals.reject_paid)(feuser, eid))
    elif kind == "settlement":
        _run(lambda: (approvals.confirm_settlement if approve else approvals.reject_settlement)(feuser, eid))
    elif kind == "consent":
        _run(lambda: approvals.set_participant_consent(feuser, eid, approve))
    else:
        if not args.get("project_id"):
            raise OpError("'project_id' is required for kind=admin.")
        _run(lambda: (approvals.admin_confirm if approve else approvals.admin_reject)(feuser, args["project_id"], eid))
    return {"kind": kind, "expense_id": eid, "approved": approve}


def _person_key_of(person) -> str | None:
    if person is None:
        return None
    return ("d" if isinstance(person, DummyUser) else "f") + str(person.pk)


@operation(
    "settlements_list", concern="approvals", access=READ, method="GET", path="settlements/",
    description=(
        "Recorded settlements, newest first. With project_id: every settlement in that project. Without: "
        "every settlement the feuser paid or received, with contacts and in projects. payer paid recipient; "
        "status pending means the recipient has not confirmed receipt yet and the debt still stands."
    ),
    params={
        "project_id": ID,
        "person_type": {"type": "string", "enum": ["feuser", "offline"], "description": "With person_id: only settlements this person paid or received."},
        "person_id": ID,
        "status": {"type": "string", "enum": ["pending", "confirmed"]},
    },
)
def settlements_list(ctx, args):
    feuser = ctx.feuser
    project = member_project(feuser, args["project_id"]) if args.get("project_id") else None
    wanted = None
    if args.get("person_type") or args.get("person_id"):
        wanted = person_key({"type": args.get("person_type"), "id": args.get("person_id")})
    status = args.get("status")
    rows = []
    for e in BuddyQueryService.settlements_visible_to(feuser, project):
        payer, recipient = BuddyQueryService.settlement_parties(e)
        if wanted and wanted not in (_person_key_of(payer), _person_key_of(recipient)):
            continue
        row_status = "confirmed" if e.buddy_approved else "pending"
        if status and status != row_status:
            continue
        rows.append({
            "id": e.uid, "amount": str(e.value),
            "date": e.date_due.isoformat() if e.date_due else None,
            "payer": person_ref(payer), "recipient": person_ref(recipient), "status": row_status,
            "project": {"id": e.project.uid, "name": e.project.name} if e.project_id else None,
        })
    return {"currency": feuser.currency, "settlements": rows}


@operation(
    "settlements_create", concern="approvals", access=WRITE, method="POST", path="settlements/",
    description=(
        "Record a payment that settles debt. Without project_id: the feuser paid a contact (creditor), or with "
        "debtor an own offline contact paid the feuser. With project_id: a payment between two members; "
        "non-admins can only record their own payments. Real creditors must confirm receipt. The money itself "
        "is not moved."
    ),
    params={"creditor": _PERSON, "debtor": _PERSON, "amount": MONEY, "project_id": ID},
    required=["creditor", "amount"], status=201,
)
def settlements_create(ctx, args):
    feuser = ctx.feuser
    amount = _run(lambda: settlement_actions.parse_amount(args["amount"]))
    creditor = person_key(args["creditor"])
    debtor = person_key(args["debtor"]) if args.get("debtor") else None
    if args.get("project_id"):
        project = member_project(feuser, args["project_id"])
        message = _run(lambda: settlement_actions.settle_in_project(feuser, project, debtor or f"f{feuser.pk}", creditor, amount))
    else:
        message = _run(lambda: settlement_actions.settle_with_contact(feuser, creditor, amount, debtor))
    return {"message": message}


@operation(
    "settlements_clear_project", concern="approvals", access=WRITE, method="POST", path="projects/<int:id>/settle-all/",
    description="As project admin, record settlements for every open debt in the project at once and email all members.",
    params={"id": ID}, required=["id"], status=201,
)
def settlements_clear_project(ctx, args):
    project = member_project(ctx.feuser, args["id"])
    return {"created": _run(lambda: settlement_actions.settle_project_all(ctx.feuser, project))}
