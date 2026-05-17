from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from ..models import BuddyLink, DummyUser
from ._helpers import _display_name
from .email import BuddyEmailService
from .query import BuddyQueryService


class BuddySettlementService:
    """Creates settlement expense records to clear debts between buddies."""

    @staticmethod
    @transaction.atomic
    def create_direct_settlements(feuser, selected_keys: list[str]) -> int:
        from budget.expense_factory import create_expense
        from budget.models import TransactionType
        from datetime import date as _date
        from feusers.models import FeUser

        count = 0
        for key in selected_keys:
            if key.startswith("f"):
                try:
                    buddy = FeUser.objects.get(pk=int(key[1:]))
                except (ValueError, FeUser.DoesNotExist):
                    continue
                if not BuddyLink.between(feuser, buddy):
                    continue
                net = BuddyQueryService.get_net_debt(feuser, buddy_feuser=buddy)
                if net >= Decimal("-0.005"):
                    continue
                amount = -net
                title = f"Settlement to {_display_name(buddy)} of {feuser.currency}{amount:.2f}"
                create_expense(
                    owning_feuser=feuser,
                    title=title,
                    type=TransactionType.EXPENSE,
                    value=amount,
                    date_due=_date.today(),
                    settled=True,
                    notify=False,
                    is_buddies_settlement=True,
                    buddy_approved=True,
                    buddy_spendings=[{"type": "feuser", "id": buddy.pk, "share_percent": Decimal("100")}],
                )
                count += 1

            elif key.startswith("d"):
                try:
                    dummy = DummyUser.objects.get(pk=int(key[1:]), owning_feuser=feuser)
                except (ValueError, DummyUser.DoesNotExist):
                    continue
                net = BuddyQueryService.get_net_debt(feuser, buddy_dummy=dummy)
                if net >= Decimal("-0.005"):
                    continue
                amount = -net
                title = f"Settlement to {dummy.display_name} (offline member) of {feuser.currency}{amount:.2f}"
                create_expense(
                    owning_feuser=feuser,
                    title=title,
                    type=TransactionType.EXPENSE,
                    value=amount,
                    date_due=_date.today(),
                    settled=True,
                    notify=False,
                    is_buddies_settlement=True,
                    buddy_approved=True,
                    buddy_spendings=[{"type": "dummy", "id": dummy.pk, "share_percent": Decimal("100")}],
                )
                count += 1

        return count

    @staticmethod
    @transaction.atomic
    def create_direct_individual_settlement(feuser, buddy_key: str, amount: "Decimal") -> bool:
        """
        Create a single settlement expense for a direct (non-group) buddy pair.

        buddy_key: "f{pk}" for a real user, "d{pk}" for a feuser-owned dummy.
        For real users the creditor must confirm receipt; for dummies it is auto-approved.
        Returns True on success.
        """
        from budget.expense_factory import create_expense
        from budget.models import TransactionType
        from datetime import date as _date
        from feusers.models import FeUser

        amount = Decimal(str(amount))
        if amount < Decimal("0.01"):
            return False

        if buddy_key.startswith("f"):
            try:
                buddy = FeUser.objects.get(pk=int(buddy_key[1:]))
            except (ValueError, FeUser.DoesNotExist):
                return False
            if not BuddyLink.between(feuser, buddy):
                return False

            title = f"Settlement to {_display_name(buddy)}"
            expense = create_expense(
                owning_feuser=feuser,
                title=title,
                type=TransactionType.EXPENSE,
                value=amount,
                date_due=_date.today(),
                settled=True,
                notify=False,
                is_buddies_settlement=True,
                buddy_approved=False,
                buddy_spendings=[{"type": "feuser", "id": buddy.pk, "share_percent": Decimal("100")}],
            )
            BuddyEmailService.send_direct_settlement_confirmation_request(
                expense, feuser, buddy
            )
            return True

        elif buddy_key.startswith("d"):
            try:
                dummy = DummyUser.objects.get(pk=int(buddy_key[1:]), owning_feuser=feuser)
            except (ValueError, DummyUser.DoesNotExist):
                return False

            title = f"Settlement to {dummy.display_name} (offline member)"
            create_expense(
                owning_feuser=feuser,
                title=title,
                type=TransactionType.EXPENSE,
                value=amount,
                date_due=_date.today(),
                settled=True,
                notify=False,
                is_buddies_settlement=True,
                buddy_approved=True,
                buddy_spendings=[{"type": "dummy", "id": dummy.pk, "share_percent": Decimal("100")}],
            )
            return True

        return False

    @staticmethod
    @transaction.atomic
    def create_individual_group_settlement(
        acting_feuser, group, debtor_key: str, creditor_key: str, amount: "Decimal"
    ) -> bool:
        """
        Create a single settlement expense within a group.

        debtor_key/creditor_key: "f{pk}" for a real user, "d{pk}" for a group dummy.
        acting_feuser is the logged-in user (must be admin when debtor is a dummy).
        Returns True on success.
        """
        from budget.expense_factory import create_expense
        from budget.models import TransactionType
        from feusers.models import FeUser

        amount = Decimal(str(amount))
        if amount < Decimal("0.01"):
            return False

        if debtor_key.startswith("f"):
            try:
                debtor_feuser = FeUser.objects.get(pk=int(debtor_key[1:]))
            except (ValueError, FeUser.DoesNotExist):
                return False
            debtor_dummy = None
            is_dummy_expense = False
            expense_owner = debtor_feuser
            debtor_name = _display_name(debtor_feuser)
        else:
            try:
                debtor_dummy = DummyUser.objects.get(pk=int(debtor_key[1:]), owning_group=group)
            except (ValueError, DummyUser.DoesNotExist):
                return False
            debtor_feuser = None
            is_dummy_expense = True
            expense_owner = acting_feuser
            debtor_name = debtor_dummy.display_name + " (offline member)"

        if creditor_key.startswith("f"):
            try:
                creditor_feuser = FeUser.objects.get(pk=int(creditor_key[1:]))
            except (ValueError, FeUser.DoesNotExist):
                return False
            creditor_dummy = None
            creditor_name = _display_name(creditor_feuser)
            bs = [{"type": "feuser", "id": creditor_feuser.pk, "share_percent": Decimal("100")}]
        else:
            try:
                creditor_dummy = DummyUser.objects.get(pk=int(creditor_key[1:]), owning_group=group)
            except (ValueError, DummyUser.DoesNotExist):
                return False
            creditor_feuser = None
            creditor_name = creditor_dummy.display_name + " (offline member)"
            bs = [{"type": "dummy", "id": creditor_dummy.pk, "share_percent": Decimal("100")}]

        both_dummies = (debtor_dummy is not None) and (creditor_dummy is not None)
        admin_is_debtor_paying_dummy = (
            debtor_feuser is not None
            and debtor_feuser.pk == acting_feuser.pk
            and acting_feuser.pk == group.admin_feuser_id
            and creditor_dummy is not None
        )
        auto_approve = both_dummies or admin_is_debtor_paying_dummy

        from datetime import date as _date
        title = f"Settlement: {debtor_name} to {creditor_name} ({group.name})"
        expense = create_expense(
            owning_feuser=expense_owner,
            title=title,
            type=TransactionType.EXPENSE,
            value=amount,
            date_due=_date.today(),
            settled=True,
            notify=False,
            is_buddies_settlement=True,
            buddy_approved=auto_approve,
            buddy_group=group,
            buddy_spendings=bs,
            is_dummy=is_dummy_expense,
            upfront_payee_dummy=debtor_dummy if is_dummy_expense else None,
        )

        if not auto_approve and creditor_feuser:
            BuddyEmailService.send_settlement_confirmation_request(
                expense, acting_feuser, creditor_feuser, debtor_name
            )

        return True

    @staticmethod
    def create_group_wide_settlements(admin_feuser, group) -> dict:
        """
        Create settlements for every simplified debt pair in the group (admin only).
        Sends summary emails to debtors, creditors, and admin for dummy creditors.
        Returns {'created': int}.
        """
        from budget.expense_factory import create_expense
        from budget.models import TransactionType
        from feusers.models import FeUser

        breakdown = BuddyQueryService.get_group_full_breakdown(admin_feuser, group)
        created_settlements = []

        with transaction.atomic():
            for t in breakdown["simplified"]:
                dk, ck, amount = t["from_key"], t["to_key"], t["amount"]
                if amount < Decimal("0.005"):
                    continue

                if dk.startswith("f"):
                    try:
                        debtor_feuser = FeUser.objects.get(pk=int(dk[1:]))
                    except (ValueError, FeUser.DoesNotExist):
                        continue
                    debtor_dummy = None
                    expense_owner = debtor_feuser
                    debtor_name = _display_name(debtor_feuser)
                    is_dummy_exp = False
                else:
                    try:
                        debtor_dummy = DummyUser.objects.get(pk=int(dk[1:]))
                    except (ValueError, DummyUser.DoesNotExist):
                        continue
                    debtor_feuser = None
                    expense_owner = admin_feuser
                    debtor_name = debtor_dummy.display_name + " (offline member)"
                    is_dummy_exp = True

                if ck.startswith("f"):
                    try:
                        creditor_feuser = FeUser.objects.get(pk=int(ck[1:]))
                    except (ValueError, FeUser.DoesNotExist):
                        continue
                    creditor_dummy = None
                    creditor_name = _display_name(creditor_feuser)
                    bs = [{"type": "feuser", "id": creditor_feuser.pk, "share_percent": Decimal("100")}]
                else:
                    try:
                        creditor_dummy = DummyUser.objects.get(pk=int(ck[1:]))
                    except (ValueError, DummyUser.DoesNotExist):
                        continue
                    creditor_feuser = None
                    creditor_name = creditor_dummy.display_name + " (offline member)"
                    bs = [{"type": "dummy", "id": creditor_dummy.pk, "share_percent": Decimal("100")}]

                both_dummies = (debtor_dummy is not None) and (creditor_dummy is not None)
                auto_approve = both_dummies or (creditor_dummy is not None)

                from datetime import date as _date
                title = f"Settlement: {debtor_name} to {creditor_name} ({group.name})"
                expense = create_expense(
                    owning_feuser=expense_owner,
                    title=title,
                    type=TransactionType.EXPENSE,
                    value=amount,
                    date_due=_date.today(),
                    settled=True,
                    notify=False,
                    is_buddies_settlement=True,
                    buddy_approved=auto_approve,
                    buddy_group=group,
                    buddy_spendings=bs,
                    is_dummy=is_dummy_exp,
                    upfront_payee_dummy=debtor_dummy if is_dummy_exp else None,
                )
                created_settlements.append({
                    "expense": expense,
                    "debtor_feuser": debtor_feuser,
                    "debtor_dummy": debtor_dummy,
                    "debtor_name": debtor_name,
                    "creditor_feuser": creditor_feuser,
                    "creditor_dummy": creditor_dummy,
                    "creditor_name": creditor_name,
                    "auto_approve": auto_approve,
                    "amount": amount,
                })

        BuddyEmailService.send_group_settlement_emails(admin_feuser, group, created_settlements)
        return {"created": len(created_settlements)}
