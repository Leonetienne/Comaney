"""
Recording settlements, with their checks, shared by the web views, the REST API
and the MCP server. Members are keyed "f<feuser id>" or "d<offline member id>".
BuddySettlementService holds the underlying mechanics.
"""
from decimal import Decimal, InvalidOperation

from .settlement import BuddySettlementService


class SettlementError(Exception):
    """A refused settlement; `status` is the matching HTTP status."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def parse_amount(raw) -> Decimal:
    try:
        amount = Decimal(str(raw).replace(",", "."))
    except (InvalidOperation, ValueError):
        raise SettlementError("Invalid amount.")
    if not amount.is_finite() or amount < Decimal("0.01"):
        raise SettlementError("Amount must be at least 0.01.")
    return amount


def settle_with_contact(feuser, creditor_key, amount, debtor_key=None) -> str:
    """
    feuser pays a contact (default), or records that one of feuser's offline
    contacts (debtor_key) paid feuser. Returns the confirmation text.
    """
    feuser_key = f"f{feuser.pk}"
    debtor_key = debtor_key or feuser_key
    if debtor_key == feuser_key:
        if not BuddySettlementService.create_direct_individual_settlement(feuser, creditor_key, amount):
            raise SettlementError("Settlement could not be created.")
        return "Settlement recorded. You still need to send the money yourself."
    if not BuddySettlementService.create_direct_dummy_settlement(feuser, debtor_key, amount):
        raise SettlementError("Settlement could not be created.")
    return "Settlement recorded."


def settle_in_project(feuser, project, debtor_key, creditor_key, amount) -> str:
    """
    Record a payment between two project members. Non-admins can only pay
    themselves (debtor is always feuser). Returns the confirmation text.
    """
    if project.archived:
        raise SettlementError("Cannot create settlements for an archived project.", 403)
    is_admin = project.admin_feuser_id == feuser.pk
    feuser_key = f"f{feuser.pk}"
    if not is_admin:
        debtor_key = feuser_key
    member_keys = set()
    for m in project.members.all():
        if m.feuser_id:
            member_keys.add(f"f{m.feuser_id}")
        if m.dummy_id:
            member_keys.add(f"d{m.dummy_id}")
    if debtor_key not in member_keys or creditor_key not in member_keys:
        raise SettlementError("Invalid member selection.")
    if debtor_key == creditor_key:
        raise SettlementError("Debtor and creditor must be different.")
    if not BuddySettlementService.create_individual_group_settlement(feuser, project, debtor_key, creditor_key, amount):
        raise SettlementError("Settlement could not be created. Check the selected members and amount.")

    creditor_offline = creditor_key.startswith("d")
    debtor_offline = debtor_key.startswith("d")
    admin_pays_offline = not debtor_offline and debtor_key == feuser_key and is_admin and creditor_offline
    if (debtor_offline and creditor_offline) or admin_pays_offline:
        return "Settlement record created."
    if creditor_offline:
        return "Settlement record created. The group admin will be asked to confirm receipt."
    return "Settlement record created. The creditor will be asked to confirm receipt."


def settle_project_all(admin, project) -> int:
    """The admin clears every open debt in the project at once; returns the number of settlements created."""
    if project.archived:
        raise SettlementError("Cannot create settlements for an archived project.", 403)
    if project.admin_feuser_id != admin.pk:
        raise SettlementError("Only the project admin can clear all debts at once.", 403)
    return BuddySettlementService.create_group_wide_settlements(admin, project)["created"]
