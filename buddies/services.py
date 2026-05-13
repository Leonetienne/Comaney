"""
Service layer for the Buddies feature.

Import these classes wherever buddy logic is needed; never import model-level
logic directly from views or the API layer.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.template.loader import render_to_string

if TYPE_CHECKING:
    from feusers.models import FeUser

from .debt_utils import simplify_balances
from .models import (
    BuddyGroupInvite,
    BuddyGroupMember,
    BuddyGroup,
    BuddyInvite,
    BuddyLink,
    BuddyOnboardingInvite,
    BuddySpending,
    DummyMergeInvite,
    DummyUser,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _display_name(feuser) -> str:
    name = f"{feuser.first_name} {feuser.last_name}".strip()
    return name or feuser.email


# ---------------------------------------------------------------------------
# BuddyQueryService
# ---------------------------------------------------------------------------

class BuddyQueryService:
    """Read-only queries about a user's buddy network."""

    @staticmethod
    def get_actual_buddies(feuser) -> list:
        """Return list of FeUser objects that are actual buddies of feuser."""
        links = BuddyLink.for_user(feuser).select_related("user_a", "user_b")
        return [link.other(feuser) for link in links]

    @staticmethod
    def get_dummy_buddies(feuser) -> list:
        """Return list of personal DummyUser objects owned by feuser (not group dummies)."""
        return list(DummyUser.objects.filter(owning_feuser=feuser))

    @staticmethod
    def get_groups_for_feuser(feuser) -> list:
        """Return list of BuddyGroup objects the feuser is a member of."""
        return list(
            BuddyGroup.objects
            .filter(members__feuser=feuser)
            .prefetch_related("members__feuser", "members__dummy")
            .distinct()
            .order_by("name")
        )

    @staticmethod
    def get_group_summaries_for_feuser(feuser) -> list:
        """
        Lightweight summary of all groups for the buddy summary page.
        Returns a list of dicts with group, is_admin, members_display,
        extra_members, net, net_abs, and net_state ('positive'/'negative'/'settled').
        Only approved expenses count toward the balance.
        """
        from budget.models import Expense

        groups = list(
            BuddyGroup.objects
            .filter(members__feuser=feuser)
            .prefetch_related("members__feuser", "members__dummy")
            .distinct()
            .order_by("name")
        )

        feuser_key = f"f{feuser.pk}"
        MAX_SHOWN = 6
        result = []

        for group in groups:
            net = Decimal("0")
            expenses = (
                Expense.objects
                .filter(buddy_group=group, buddy_approved=True)
                .prefetch_related("buddy_spendings")
            )
            for exp in expenses:
                payer_key = (
                    f"d{exp.upfront_payee_dummy_id}"
                    if (exp.is_dummy and exp.upfront_payee_dummy_id)
                    else f"f{exp.owning_feuser_id}"
                )
                for bs in exp.buddy_spendings.all():
                    pk = (
                        f"f{bs.participant_feuser_id}"
                        if bs.participant_feuser_id
                        else f"d{bs.participant_dummy_id}"
                    )
                    amount = exp.value * bs.share_percent / 100
                    if pk == feuser_key:
                        net -= amount
                    if payer_key == feuser_key:
                        net += amount

            # Build member name list; current user shown as "You" and sorted first
            member_names = []
            for m in group.members.all():
                if m.feuser_id:
                    if m.feuser_id == feuser.pk:
                        member_names.append(("You", True))
                    else:
                        name = f"{m.feuser.first_name} {m.feuser.last_name}".strip() or m.feuser.email
                        member_names.append((name, False))
                else:
                    member_names.append((m.dummy.display_name, False))
            member_names.sort(key=lambda x: (0 if x[1] else 1, x[0]))
            all_names = [n for n, _ in member_names]
            members_display = all_names[:MAX_SHOWN]
            extra = max(0, len(all_names) - MAX_SHOWN)

            net_abs = abs(net)
            if net > Decimal("0.005"):
                net_state = "positive"
            elif net < Decimal("-0.005"):
                net_state = "negative"
            else:
                net_state = "settled"

            result.append({
                "group": group,
                "is_admin": group.admin_feuser_id == feuser.pk,
                "members_display": members_display,
                "extra_members": extra,
                "net": net,
                "net_abs": net_abs,
                "net_state": net_state,
            })

        return result

    @staticmethod
    def groups_data_for_expense_form(feuser) -> list:
        """
        Serialize group membership for JSON injection into the expense form.
        Returns a list of group dicts with member info.
        """
        groups = BuddyQueryService.get_groups_for_feuser(feuser)
        result = []
        for group in groups:
            members = []
            for m in group.members.select_related("feuser", "dummy").all():
                if m.feuser_id:
                    fu = m.feuser
                    name = f"{fu.first_name} {fu.last_name}".strip() or fu.email
                    members.append({
                        "type": "feuser",
                        "id": fu.pk,
                        "name": name,
                        "is_me": fu.pk == feuser.pk,
                    })
                else:
                    members.append({
                        "type": "dummy",
                        "id": m.dummy_id,
                        "name": m.dummy.display_name,
                        "is_me": False,
                    })
            result.append({
                "id": group.uid,
                "name": group.name,
                "is_admin": group.admin_feuser_id == feuser.pk,
                "members": members,
            })
        return result

    @staticmethod
    def are_buddies(feuser_a, feuser_b) -> bool:
        return BuddyLink.between(feuser_a, feuser_b) is not None

    @staticmethod
    def get_net_debt(feuser, buddy_feuser=None, buddy_dummy=None) -> Decimal:
        """
        Net debt from feuser's perspective for a single direct-buddy relationship.
        Positive = buddy owes feuser. Negative = feuser owes buddy.
        Only covers personal (non-group) expenses.
        """
        from budget.models import Expense

        owed_to_me = Decimal("0")
        i_owe = Decimal("0")

        if buddy_feuser is not None:
            owed_to_me = sum(
                (bs.expense.value * bs.share_percent / 100)
                for bs in BuddySpending.objects.filter(
                    participant_feuser=buddy_feuser,
                    expense__owning_feuser=feuser,
                    expense__is_dummy=False,
                    expense__buddy_group__isnull=True,
                    expense__buddy_approved=True,
                ).select_related("expense")
            )
            i_owe = sum(
                (bs.expense.value * bs.share_percent / 100)
                for bs in BuddySpending.objects.filter(
                    participant_feuser=feuser,
                    expense__owning_feuser=buddy_feuser,
                    expense__is_dummy=False,
                    expense__buddy_group__isnull=True,
                    expense__buddy_approved=True,
                ).select_related("expense")
            )

        elif buddy_dummy is not None:
            owed_to_me = sum(
                (bs.expense.value * bs.share_percent / 100)
                for bs in BuddySpending.objects.filter(
                    participant_dummy=buddy_dummy,
                    expense__owning_feuser=feuser,
                    expense__is_dummy=False,
                    expense__buddy_group__isnull=True,
                    expense__buddy_approved=True,
                ).select_related("expense")
            )
            dummy_expenses = Expense.objects.filter(
                owning_feuser=feuser,
                upfront_payee_dummy=buddy_dummy,
                is_dummy=True,
                buddy_group__isnull=True,
                buddy_approved=True,
            ).prefetch_related("buddy_spendings")
            for exp in dummy_expenses:
                participant_sum = sum(bs.share_percent for bs in exp.buddy_spendings.all())
                my_implicit_share = Decimal("100") - participant_sum
                i_owe += exp.value * my_implicit_share / 100

        return Decimal(owed_to_me) - Decimal(i_owe)

    @staticmethod
    def get_group_simplified_debts(feuser, group) -> list:
        """
        Compute minimum-transaction simplified debts for feuser within a group.
        Returns [{'person': FeUser | DummyUser, 'net': Decimal}, ...]
        where positive net means that person owes feuser.
        """
        from budget.models import Expense

        members = group.members.select_related("feuser", "dummy").all()

        key_to_obj: dict[str, object] = {}
        balances: dict[str, Decimal] = {}
        for m in members:
            if m.feuser_id:
                k = f"f{m.feuser_id}"
                key_to_obj[k] = m.feuser
            else:
                k = f"d{m.dummy_id}"
                key_to_obj[k] = m.dummy
            balances[k] = Decimal("0")

        expenses = (
            Expense.objects
            .filter(buddy_group=group, buddy_approved=True)
            .prefetch_related("buddy_spendings")
            .select_related("owning_feuser", "upfront_payee_dummy")
        )

        for exp in expenses:
            if exp.is_dummy and exp.upfront_payee_dummy_id:
                payer_key = f"d{exp.upfront_payee_dummy_id}"
            else:
                payer_key = f"f{exp.owning_feuser_id}"

            if payer_key not in balances:
                continue

            for bs in exp.buddy_spendings.all():
                if bs.participant_feuser_id:
                    pk = f"f{bs.participant_feuser_id}"
                else:
                    pk = f"d{bs.participant_dummy_id}"

                if pk not in balances:
                    continue

                amount = exp.value * bs.share_percent / 100
                balances[payer_key] += amount
                balances[pk] -= amount

        transactions = simplify_balances(balances)
        feuser_key = f"f{feuser.pk}"
        result = []
        for dk, ck, amount in transactions:
            if dk == feuser_key:
                obj = key_to_obj.get(ck)
                if obj:
                    result.append({"person": obj, "net": -amount})
            elif ck == feuser_key:
                obj = key_to_obj.get(dk)
                if obj:
                    result.append({"person": obj, "net": amount})
        return result

    @staticmethod
    def get_group_full_breakdown(feuser, group) -> dict:
        """
        Full financial breakdown for a group, suitable for an audit trail.

        Returns a dict with:
          expenses: list of per-expense dicts (payer, per-member share amounts)
          balances: list of per-member net balance dicts (positive = others owe them)
          simplified: list of minimum-transaction settlements
          member_map: {key: {name, is_me}} for all current members
        """
        from budget.models import Expense

        members = group.members.select_related("feuser", "dummy").all()

        member_map: dict[str, dict] = {}
        for m in members:
            if m.feuser_id:
                key = f"f{m.feuser_id}"
                member_map[key] = {
                    "name": _display_name(m.feuser),
                    "is_me": m.feuser_id == feuser.pk,
                }
            else:
                key = f"d{m.dummy_id}"
                member_map[key] = {
                    "name": m.dummy.display_name,
                    "is_me": False,
                }

        balances: dict[str, Decimal] = {k: Decimal("0") for k in member_map}

        feuser_key = f"f{feuser.pk}"
        expenses_qs = (
            Expense.objects
            .filter(buddy_group=group)  # all expenses shown in list; unapproved excluded from balances below
            .prefetch_related("buddy_spendings")
            .select_related("owning_feuser", "upfront_payee_dummy")
            .order_by("-date_created")
        )

        expenses_data = []
        for exp in expenses_qs:
            if exp.is_dummy and exp.upfront_payee_dummy_id:
                payer_key = f"d{exp.upfront_payee_dummy_id}"
            else:
                payer_key = f"f{exp.owning_feuser_id}"

            if payer_key not in member_map:
                continue

            payer_info = member_map[payer_key]
            participant_shares = []
            total_pct = Decimal("0")

            for bs in exp.buddy_spendings.all():
                pk = f"f{bs.participant_feuser_id}" if bs.participant_feuser_id else f"d{bs.participant_dummy_id}"
                amount = exp.value * bs.share_percent / 100
                total_pct += bs.share_percent
                p_info = member_map.get(pk, {"name": "Unknown", "is_me": False})
                participant_shares.append({
                    "key": pk,
                    "name": p_info["name"],
                    "is_me": p_info["is_me"],
                    "amount": amount,
                    "percent": bs.share_percent,
                })
                if exp.buddy_approved:
                    if pk in balances:
                        balances[pk] -= amount
                    if payer_key in balances:
                        balances[payer_key] += amount

            i_am_participant = any(
                (f"f{bs.participant_feuser_id}" == feuser_key)
                for bs in exp.buddy_spendings.all()
            )
            payer_pct = Decimal("100") - total_pct
            expenses_data.append({
                "expense": exp,
                "payer_key": payer_key,
                "payer_name": payer_info["name"],
                "payer_is_me": payer_info["is_me"],
                "i_am_participant": i_am_participant,
                "total": exp.value,
                "payer_amount": exp.value * payer_pct / 100,
                "payer_percent": payer_pct,
                "participant_shares": participant_shares,
            })

        simplified = [
            {
                "from_key": dk,
                "from_name": member_map[dk]["name"],
                "from_is_me": member_map[dk]["is_me"],
                "to_key": ck,
                "to_name": member_map[ck]["name"],
                "to_is_me": member_map[ck]["is_me"],
                "amount": amount,
            }
            for dk, ck, amount in simplify_balances(balances)
        ]

        balances_list = [
            {"key": k, "name": member_map[k]["name"], "is_me": member_map[k]["is_me"], "net": v}
            for k, v in balances.items()
        ]
        balances_list.sort(key=lambda x: -abs(x["net"]))

        return {
            "expenses": expenses_data,
            "balances": balances_list,
            "simplified": simplified,
            "member_map": member_map,
        }

    @staticmethod
    def get_all_debts_unified(feuser) -> list:
        """
        Unified debt list across direct buddies and groups.
        Returns [
          {
            'type': 'feuser' | 'dummy',
            'feuser': FeUser | None,
            'dummy': DummyUser | None,
            'display_name': str,
            'sources': list[str],
            'net': Decimal,
            'net_abs': Decimal,
            'link_uid': int | None,   # BuddyLink.uid when a Personal Buddy link exists
          }, ...
        ] sorted by abs(net) descending.
        """
        from feusers.models import FeUser as FU

        person_map: dict = {}

        def _upsert(key, p_type, obj, source, delta, link_uid=None):
            if key not in person_map:
                person_map[key] = {
                    "type": p_type,
                    "feuser": obj if p_type == "feuser" else None,
                    "dummy": obj if p_type == "dummy" else None,
                    "display_name": _display_name(obj) if p_type == "feuser" else obj.display_name,
                    "sources": [],
                    "net": Decimal("0"),
                    "link_uid": None,
                }
            if source not in person_map[key]["sources"]:
                person_map[key]["sources"].append(source)
            person_map[key]["net"] += delta
            if link_uid is not None:
                person_map[key]["link_uid"] = link_uid

        # Direct buddy debts
        for link in BuddyLink.for_user(feuser).select_related("user_a", "user_b"):
            buddy = link.other(feuser)
            net = BuddyQueryService.get_net_debt(feuser, buddy_feuser=buddy)
            _upsert(("feuser", buddy.pk), "feuser", buddy, "Direct", net, link_uid=link.uid)

        for dummy in DummyUser.objects.filter(owning_feuser=feuser):
            net = BuddyQueryService.get_net_debt(feuser, buddy_dummy=dummy)
            _upsert(("dummy", dummy.pk), "dummy", dummy, "Direct", net)

        # Annotate group membership for entries already in person_map
        groups = (
            BuddyGroup.objects
            .filter(members__feuser=feuser)
            .prefetch_related("members__feuser", "members__dummy")
            .distinct()
        )
        for group in groups:
            for m in group.members.all():
                if m.feuser_id and m.feuser_id != feuser.pk:
                    key = ("feuser", m.feuser_id)
                    if key in person_map and group.name not in person_map[key]["sources"]:
                        person_map[key]["sources"].append(group.name)
                elif m.dummy_id:
                    key = ("dummy", m.dummy_id)
                    if key in person_map and group.name not in person_map[key]["sources"]:
                        person_map[key]["sources"].append(group.name)

        result = list(person_map.values())
        for r in result:
            r["net_abs"] = abs(r["net"])
        result.sort(key=lambda x: (-x["net_abs"], x["display_name"]))
        return result

    @staticmethod
    def get_all_debts(feuser) -> dict:
        """Legacy method kept for existing code. Returns {'actual': {...}, 'dummy': {...}}."""
        result = {"actual": {}, "dummy": {}}
        for link in BuddyLink.for_user(feuser).select_related("user_a", "user_b"):
            buddy = link.other(feuser)
            net = BuddyQueryService.get_net_debt(feuser, buddy_feuser=buddy)
            result["actual"][buddy.pk] = {
                "feuser": buddy,
                "link": link,
                "net": net,
                "net_abs": abs(net),
            }
        for dummy in BuddyQueryService.get_dummy_buddies(feuser):
            net = BuddyQueryService.get_net_debt(feuser, buddy_dummy=dummy)
            result["dummy"][dummy.pk] = {
                "dummy": dummy,
                "net": net,
                "net_abs": abs(net),
            }
        return result

    @staticmethod
    def shared_expenses(feuser):
        """Queryset of all buddy-related expenses visible to feuser."""
        from budget.models import Expense

        buddy_feuserids = [b.pk for b in BuddyQueryService.get_actual_buddies(feuser)]
        group_ids = [g.uid for g in BuddyQueryService.get_groups_for_feuser(feuser)]

        return (
            Expense.objects
            .filter(
                Q(owning_feuser=feuser, buddy_spendings__isnull=False) |
                Q(owning_feuser=feuser, is_dummy=True) |
                Q(owning_feuser_id__in=buddy_feuserids, buddy_spendings__participant_feuser=feuser) |
                Q(buddy_group_id__in=group_ids, buddy_spendings__participant_feuser=feuser) |
                Q(buddy_group_id__in=group_ids, owning_feuser=feuser)
            )
            .distinct()
            .select_related("owning_feuser", "category", "upfront_payee_dummy", "buddy_group")
            .prefetch_related(
                "buddy_spendings__participant_feuser",
                "buddy_spendings__participant_dummy",
                "tags",
            )
            .order_by("-date_created")
        )

    @staticmethod
    def pending_invites_incoming(feuser):
        from django.utils import timezone
        return BuddyInvite.objects.filter(
            invitee_email=feuser.email,
            expires_at__gt=timezone.now(),
        ).select_related("inviter")

    @staticmethod
    def pending_invites_outgoing(feuser):
        from django.utils import timezone
        return BuddyInvite.objects.filter(
            inviter=feuser,
            expires_at__gt=timezone.now(),
        )

    @staticmethod
    def pending_merge_invites_incoming(feuser):
        from django.utils import timezone
        return DummyMergeInvite.objects.filter(
            invited_feuser=feuser,
            expires_at__gt=timezone.now(),
        ).select_related("inviting_feuser", "dummy")

    @staticmethod
    def pending_group_invites_incoming(feuser):
        from django.utils import timezone
        return BuddyGroupInvite.objects.filter(
            invitee_email=feuser.email,
            expires_at__gt=timezone.now(),
        ).select_related("group", "inviting_feuser")

    @staticmethod
    def pending_group_invites_for_group(group):
        from django.utils import timezone
        return BuddyGroupInvite.objects.filter(
            group=group,
            expires_at__gt=timezone.now(),
        )


# ---------------------------------------------------------------------------
# BuddyExpenseService
# ---------------------------------------------------------------------------

class BuddyExpenseService:
    """Handles expense-level buddy operations."""

    @staticmethod
    def set_buddy_spendings(expense, participants: list[dict]):
        """
        Replace all BuddySpending rows for an expense.
        participants: [{'type': 'feuser'|'dummy', 'id': int, 'share_percent': Decimal}, ...]
        The expense owner must NOT appear in participants for non-group expenses.
        """
        expense.buddy_spendings.all().delete()
        rows = []
        for p in participants:
            bs = BuddySpending(expense=expense, share_percent=Decimal(str(p["share_percent"])))
            if p["type"] == "feuser":
                bs.participant_feuser_id = int(p["id"])
            else:
                bs.participant_dummy_id = int(p["id"])
            rows.append(bs)
        BuddySpending.objects.bulk_create(rows)

    @staticmethod
    def reconcile_categories_tags(expense, target_feuser):
        """
        Match expense's category and tags to target_feuser's sets by title.
        Mutates expense in-place; caller must save.
        """
        from budget.models import Category, Tag

        if expense.category_id:
            try:
                matched = Category.objects.get(
                    owning_feuser=target_feuser,
                    title=expense.category.title,
                )
                expense.category = matched
            except Category.DoesNotExist:
                expense.category = None

        current_tags = list(expense.tags.all())
        matched_tags = []
        for tag in current_tags:
            try:
                matched = Tag.objects.get(owning_feuser=target_feuser, title=tag.title)
                matched_tags.append(matched)
            except Tag.DoesNotExist:
                pass
        expense.tags.set(matched_tags)

    @staticmethod
    @transaction.atomic
    def clone_expense_for_feuser(source_expense, target_feuser, dummy_payer: DummyUser):
        """
        Clone source_expense for target_feuser.
        Result: owning_feuser=target_feuser, is_dummy=True, upfront_payee_dummy=dummy_payer.
        """
        clone = _clone_expense_object(source_expense, target_feuser)
        clone.is_dummy = True
        clone.upfront_payee_dummy = dummy_payer
        clone.buddy_approved = True
        clone.save()
        clone.tags.set(list(clone._reconciled_tags) if hasattr(clone, "_reconciled_tags") else [])

        for bs in source_expense.buddy_spendings.all():
            if bs.participant_feuser_id == target_feuser.pk:
                continue
            BuddySpending.objects.create(
                expense=clone,
                participant_feuser=bs.participant_feuser,
                participant_dummy=bs.participant_dummy,
                share_percent=bs.share_percent,
            )

        return clone

    @staticmethod
    @transaction.atomic
    def change_upfront_payer(expense, new_payer_feuser=None, new_payer_dummy=None):
        """
        Change who is the upfront payer for an existing buddy expense.
        Adjusts BuddySpending rows to maintain share percentages.
        Returns the (possibly mutated) expense.
        """
        old_owner = expense.owning_feuser
        old_dummy_payer = expense.upfront_payee_dummy

        if new_payer_feuser is not None and new_payer_feuser != old_owner:
            new_payer_bs = expense.buddy_spendings.filter(participant_feuser=new_payer_feuser).first()
            # Compute old owner's share BEFORE removing new payer's row
            participant_sum = sum(bs.share_percent for bs in expense.buddy_spendings.all())
            old_owner_share = Decimal("100") - participant_sum
            if new_payer_bs:
                new_payer_bs.delete()

            if old_owner_dummy := old_dummy_payer:
                BuddySpending.objects.create(
                    expense=expense,
                    participant_dummy=old_owner_dummy,
                    share_percent=old_owner_share,
                )
            else:
                BuddySpending.objects.create(
                    expense=expense,
                    participant_feuser=old_owner,
                    share_percent=old_owner_share,
                )

            expense.owning_feuser = new_payer_feuser
            expense.is_dummy = False
            expense.upfront_payee_dummy = None
            expense.buddy_approved = False
            BuddyExpenseService.reconcile_categories_tags(expense, new_payer_feuser)
            expense.save()

        elif new_payer_dummy is not None and new_payer_dummy != old_dummy_payer:
            dummy_bs = expense.buddy_spendings.filter(participant_dummy=new_payer_dummy).first()
            # Compute old payer's share BEFORE removing new dummy's row
            participant_sum = sum(bs.share_percent for bs in expense.buddy_spendings.all())
            old_payer_share = Decimal("100") - participant_sum
            if dummy_bs:
                dummy_bs.delete()

            if old_dummy_payer:
                BuddySpending.objects.create(
                    expense=expense,
                    participant_dummy=old_dummy_payer,
                    share_percent=old_payer_share,
                )
            else:
                BuddySpending.objects.create(
                    expense=expense,
                    participant_feuser=expense.owning_feuser,
                    share_percent=old_payer_share,
                )

            expense.is_dummy = True
            expense.upfront_payee_dummy = new_payer_dummy
            expense.buddy_approved = True
            expense.save()

        return expense


def _clone_expense_object(source, target_feuser):
    """Return an unsaved Expense copy for target_feuser (no M2M yet)."""
    from budget.models import Expense

    clone = Expense(
        owning_feuser=target_feuser,
        title=source.title,
        payee=source.payee,
        note=source.note,
        type=source.type,
        value=source.value,
        date_due=source.date_due,
        settled=source.settled,
        auto_settle_on_due_date=source.auto_settle_on_due_date,
        notify=source.notify,
        category=source.category,
    )
    if clone.category_id:
        from budget.models import Category
        try:
            clone.category = Category.objects.get(
                owning_feuser=target_feuser,
                title=source.category.title,
            )
        except Category.DoesNotExist:
            clone.category = None

    from budget.models import Tag
    clone._reconciled_tags = []
    for tag in source.tags.all():
        try:
            matched = Tag.objects.get(owning_feuser=target_feuser, title=tag.title)
            clone._reconciled_tags.append(matched)
        except Tag.DoesNotExist:
            pass

    return clone


# ---------------------------------------------------------------------------
# BuddyGroupService
# ---------------------------------------------------------------------------

class BuddyGroupService:
    """Manages buddy group lifecycle."""

    @staticmethod
    @transaction.atomic
    def create_group(admin_feuser, name: str) -> BuddyGroup:
        name = name.strip()
        group = BuddyGroup.objects.create(name=name, admin_feuser=admin_feuser)
        BuddyGroupMember.objects.create(group=group, feuser=admin_feuser)
        return group

    @staticmethod
    @transaction.atomic
    def invite_member(group, admin_feuser, email: str):
        """
        Invite a user by email to join a group.
        Creates a BuddyLink simultaneously if they are not yet buddies.
        Returns one of:
          ('self', None)
          ('already_member', BuddyGroupMember)
          ('member', BuddyGroupMember) - DISABLE_EMAILING path
          ('invite', BuddyGroupInvite)
          ('onboarding', BuddyOnboardingInvite)
          ('onboarding_no_email', BuddyOnboardingInvite)
          ('registration_disabled', None)
        """
        from feusers.models import FeUser

        email = email.strip().lower()

        if email == admin_feuser.email.lower():
            return ("self", None)

        try:
            invitee = FeUser.objects.get(email__iexact=email, is_active=True)
        except FeUser.DoesNotExist:
            invitee = None

        if invitee:
            existing = BuddyGroupMember.objects.filter(group=group, feuser=invitee).first()
            if existing:
                return ("already_member", existing)

        if settings.DISABLE_EMAILING:
            if invitee:
                if not BuddyLink.between(admin_feuser, invitee):
                    BuddyLifecycleService._create_link(admin_feuser, invitee)
                member, _ = BuddyGroupMember.objects.get_or_create(group=group, feuser=invitee)
                return ("member", member)
            if not settings.ENABLE_REGISTRATION:
                return ("registration_disabled", None)
            ob = BuddyOnboardingInvite(
                inviting_feuser=admin_feuser, group=group, invitee_email=email
            )
            ob.save()
            return ("onboarding_no_email", ob)

        if invitee:
            invite = BuddyGroupInvite(
                group=group, inviting_feuser=admin_feuser, invitee_email=email
            )
            invite.save()
            BuddyEmailService.send_group_invite(invite, invitee)
            return ("invite", invite)

        if not settings.ENABLE_REGISTRATION:
            return ("registration_disabled", None)

        ob = BuddyOnboardingInvite(
            inviting_feuser=admin_feuser, group=group, invitee_email=email
        )
        ob.save()
        BuddyEmailService.send_group_onboarding_invite(ob)
        return ("onboarding", ob)

    @staticmethod
    @transaction.atomic
    def accept_group_invite(token: str, accepting_feuser) -> BuddyGroup | None:
        """Accept a BuddyGroupInvite. Returns the group or None if invalid."""
        try:
            invite = BuddyGroupInvite.objects.select_related(
                "group", "inviting_feuser"
            ).get(token=token)
        except BuddyGroupInvite.DoesNotExist:
            return None

        if not invite.is_valid():
            invite.delete()
            return None

        if invite.invitee_email.lower() != accepting_feuser.email.lower():
            return None

        group = invite.group
        inviting_feuser = invite.inviting_feuser

        if not BuddyLink.between(inviting_feuser, accepting_feuser):
            BuddyLifecycleService._create_link(inviting_feuser, accepting_feuser)

        BuddyGroupMember.objects.get_or_create(group=group, feuser=accepting_feuser)

        invite.delete()
        return group

    @staticmethod
    def decline_group_invite(token: str, declining_feuser) -> bool:
        try:
            invite = BuddyGroupInvite.objects.get(
                token=token, invitee_email=declining_feuser.email
            )
        except BuddyGroupInvite.DoesNotExist:
            return False
        invite.delete()
        return True

    @staticmethod
    def revoke_group_invite(token: str, revoking_feuser) -> bool:
        try:
            invite = BuddyGroupInvite.objects.get(
                token=token, group__admin_feuser=revoking_feuser
            )
        except BuddyGroupInvite.DoesNotExist:
            return False
        invite.delete()
        return True

    @staticmethod
    @transaction.atomic
    def remove_member(group, admin_feuser, target_member: BuddyGroupMember) -> DummyUser:
        """
        Remove a feuser member from the group.
        Replaces them with a group dummy in all historical group expenses.
        Returns the created ghost dummy.
        """
        removed_feuser = target_member.feuser
        ghost_dummy = DummyUser.objects.create(
            owning_group=group,
            display_name=_display_name(removed_feuser),
        )
        BuddyGroupMember.objects.create(group=group, dummy=ghost_dummy)

        BuddySpending.objects.filter(
            participant_feuser=removed_feuser,
            expense__buddy_group=group,
        ).update(participant_feuser=None, participant_dummy=ghost_dummy)

        target_member.delete()
        return ghost_dummy

    @staticmethod
    @transaction.atomic
    def create_group_dummy(group, admin_feuser, display_name: str) -> DummyUser:
        dummy = DummyUser.objects.create(
            owning_group=group,
            display_name=display_name.strip(),
        )
        BuddyGroupMember.objects.create(group=group, dummy=dummy)
        return dummy

    @staticmethod
    @transaction.atomic
    def delete_group_dummy(group, admin_feuser, dummy: DummyUser) -> None:
        """Delete a group dummy. Clears expense references."""
        from budget.models import Expense
        BuddySpending.objects.filter(participant_dummy=dummy).delete()
        Expense.objects.filter(upfront_payee_dummy=dummy).update(
            upfront_payee_dummy=None, is_dummy=False
        )
        dummy.delete()

    @staticmethod
    @transaction.atomic
    def send_group_dummy_merge_invite(group, admin_feuser, dummy: DummyUser, target_email: str):
        """
        Invite a real user to take over a group dummy's history.
        Also joins them to the group as a member.
        Returns same tuple format as BuddyLifecycleService.send_merge_invite.
        """
        from feusers.models import FeUser

        target_email = target_email.strip().lower()
        try:
            invited = FeUser.objects.get(email__iexact=target_email, is_active=True)
        except FeUser.DoesNotExist:
            invited = None

        if invited is None:
            if settings.DISABLE_EMAILING:
                if not settings.ENABLE_REGISTRATION:
                    return ("registration_disabled", None)
                ob = BuddyOnboardingInvite(
                    inviting_feuser=admin_feuser,
                    dummy=dummy,
                    group=group,
                    invitee_email=target_email,
                )
                ob.save()
                return ("onboarding_no_email", ob)
            if not settings.ENABLE_REGISTRATION:
                return ("registration_disabled", None)
            ob = BuddyOnboardingInvite(
                inviting_feuser=admin_feuser,
                dummy=dummy,
                group=group,
                invitee_email=target_email,
            )
            ob.save()
            BuddyEmailService.send_onboarding_invite(ob)
            return ("onboarding", ob)

        invite = DummyMergeInvite(
            inviting_feuser=admin_feuser,
            dummy=dummy,
            invited_feuser=invited,
        )
        invite.save()
        BuddyEmailService.send_merge_invite(invite)
        return ("invite", invite)

    @staticmethod
    @transaction.atomic
    def accept_group_dummy_merge(token: str, accepting_feuser) -> bool:
        """
        Accept a DummyMergeInvite for a group dummy.
        Transfers the dummy's expense history, adds the user to the group.
        """
        from budget.models import Expense

        try:
            invite = DummyMergeInvite.objects.select_related(
                "dummy__owning_group", "inviting_feuser"
            ).get(token=token)
        except DummyMergeInvite.DoesNotExist:
            return False

        if not invite.is_valid():
            invite.delete()
            return False

        if invite.invited_feuser_id != accepting_feuser.pk:
            return False

        dummy = invite.dummy
        inviting_feuser = invite.inviting_feuser
        group = dummy.owning_group

        for exp in Expense.objects.filter(upfront_payee_dummy=dummy, is_dummy=True):
            exp.owning_feuser = accepting_feuser
            exp.is_dummy = False
            exp.upfront_payee_dummy = None
            BuddyExpenseService.reconcile_categories_tags(exp, accepting_feuser)
            exp.save()

        BuddySpending.objects.filter(participant_dummy=dummy).update(
            participant_dummy=None,
            participant_feuser=accepting_feuser,
        )

        if not BuddyLink.between(inviting_feuser, accepting_feuser):
            BuddyLifecycleService._create_link(inviting_feuser, accepting_feuser)

        if group:
            dummy_member = BuddyGroupMember.objects.filter(group=group, dummy=dummy).first()
            if dummy_member:
                dummy_member.delete()
            BuddyGroupMember.objects.get_or_create(group=group, feuser=accepting_feuser)

        dummy.delete()
        invite.delete()
        return True

    @staticmethod
    @transaction.atomic
    def transfer_admin(group, current_admin, new_admin_feuser) -> bool:
        """Transfer admin rights to another feuser group member."""
        if not BuddyGroupMember.objects.filter(group=group, feuser=new_admin_feuser).exists():
            return False
        group.admin_feuser = new_admin_feuser
        group.save(update_fields=["admin_feuser"])
        return True

    @staticmethod
    @transaction.atomic
    def dissolve_group(group, admin_feuser) -> None:
        """
        Dissolve a group. Group dummies are transferred to the admin as personal dummies.
        Group expenses lose their group context (buddy_group becomes NULL via FK cascade).
        """
        DummyUser.objects.filter(owning_group=group).update(
            owning_group=None,
            owning_feuser=admin_feuser,
        )
        group.delete()


# ---------------------------------------------------------------------------
# BuddyLifecycleService
# ---------------------------------------------------------------------------

class BuddyLifecycleService:
    """Buddy relationship management: add, invite, kick, merge."""

    @staticmethod
    def add_dummy(feuser, display_name: str) -> DummyUser:
        return DummyUser.objects.create(
            owning_feuser=feuser,
            display_name=display_name.strip(),
        )

    @staticmethod
    @transaction.atomic
    def invite_actual(feuser, email: str):
        """
        Invite an actual user by email as a personal buddy.
        Returns ('link'|'invite'|'onboarding'|'onboarding_no_email'|
                 'already_buddies'|'self'|'registration_disabled', obj).
        """
        from feusers.models import FeUser

        email = email.strip().lower()

        if email == feuser.email.lower():
            return ("self", None)

        try:
            invitee = FeUser.objects.get(email__iexact=email, is_active=True)
        except FeUser.DoesNotExist:
            invitee = None

        if invitee and BuddyLink.between(feuser, invitee):
            return ("already_buddies", None)

        if settings.DISABLE_EMAILING:
            if invitee:
                link = BuddyLifecycleService._create_link(feuser, invitee)
                return ("link", link)
            if not settings.ENABLE_REGISTRATION:
                return ("registration_disabled", None)
            ob = BuddyOnboardingInvite(inviting_feuser=feuser, invitee_email=email)
            ob.save()
            return ("onboarding_no_email", ob)

        if invitee:
            invite = BuddyInvite(inviter=feuser, invitee_email=email)
            invite.save()
            BuddyEmailService.send_buddy_invite(invite)
            return ("invite", invite)

        if not settings.ENABLE_REGISTRATION:
            return ("registration_disabled", None)
        ob = BuddyOnboardingInvite(inviting_feuser=feuser, invitee_email=email)
        ob.save()
        BuddyEmailService.send_onboarding_invite(ob)
        return ("onboarding", ob)

    @staticmethod
    def _create_link(feuser_a, feuser_b) -> BuddyLink:
        lo, hi = sorted([feuser_a, feuser_b], key=lambda u: u.pk)
        link, _ = BuddyLink.objects.get_or_create(user_a=lo, user_b=hi)
        return link

    @staticmethod
    @transaction.atomic
    def accept_invite(token: str, accepting_feuser) -> BuddyLink | None:
        try:
            invite = BuddyInvite.objects.get(token=token)
        except BuddyInvite.DoesNotExist:
            return None

        if not invite.is_valid():
            invite.delete()
            return None

        if invite.invitee_email.lower() != accepting_feuser.email.lower():
            return None

        link = BuddyLifecycleService._create_link(invite.inviter, accepting_feuser)
        invite.delete()
        return link

    @staticmethod
    def decline_invite(token: str, declining_feuser) -> bool:
        try:
            invite = BuddyInvite.objects.get(token=token, invitee_email=declining_feuser.email)
        except BuddyInvite.DoesNotExist:
            return False
        invite.delete()
        return True

    @staticmethod
    def revoke_invite(token: str, revoking_feuser) -> bool:
        try:
            invite = BuddyInvite.objects.get(token=token, inviter=revoking_feuser)
        except BuddyInvite.DoesNotExist:
            return False
        invite.delete()
        return True

    @staticmethod
    @transaction.atomic
    def kick_dummy(feuser, dummy: DummyUser, has_debt_warning_accepted: bool = False) -> dict:
        net = BuddyQueryService.get_net_debt(feuser, buddy_dummy=dummy)
        if abs(net) > Decimal("0.05") and not has_debt_warning_accepted:
            return {"debt_warning": net}

        BuddySpending.objects.filter(participant_dummy=dummy).delete()
        from budget.models import Expense
        Expense.objects.filter(
            owning_feuser=feuser,
            upfront_payee_dummy=dummy,
            is_dummy=True,
        ).delete()
        dummy.delete()
        return {"kicked": True}

    @staticmethod
    @transaction.atomic
    def kick_actual(feuser, other_feuser, has_debt_warning_accepted: bool = False) -> dict:
        from budget.models import Expense

        net = BuddyQueryService.get_net_debt(feuser, buddy_feuser=other_feuser)
        if abs(net) > Decimal("0.05") and not has_debt_warning_accepted:
            return {"debt_warning": net}

        link = BuddyLink.between(feuser, other_feuser)
        if not link:
            return {"kicked": True}

        feuser_expenses_with_other = Expense.objects.filter(
            owning_feuser=feuser,
            is_dummy=False,
            buddy_group__isnull=True,
            buddy_spendings__participant_feuser=other_feuser,
        ).distinct()
        for exp in feuser_expenses_with_other:
            new_dummy = DummyUser.objects.create(
                owning_feuser=other_feuser,
                display_name=_display_name(feuser),
            )
            BuddyExpenseService.clone_expense_for_feuser(exp, other_feuser, new_dummy)
            exp.buddy_spendings.filter(participant_feuser=other_feuser).delete()

        kicker_dummy_for_other = DummyUser.objects.create(
            owning_feuser=other_feuser,
            display_name=_display_name(feuser),
        )
        BuddySpending.objects.filter(
            participant_feuser=feuser,
            expense__owning_feuser=other_feuser,
            expense__buddy_group__isnull=True,
        ).update(participant_feuser=None, participant_dummy=kicker_dummy_for_other)

        link.delete()
        BuddyEmailService.send_kicked_notification(
            kicked_feuser=other_feuser,
            kicking_display_name=_display_name(feuser),
        )
        return {"kicked": True}

    @staticmethod
    @transaction.atomic
    def handle_account_deletion(feuser):
        """
        Called before feuser.delete().
        Converts all actual buddy relationships to dummy relationships.
        Also handles group memberships.
        """
        from budget.models import Expense

        # Handle individual buddy links
        for link in BuddyLink.for_user(feuser):
            other = link.other(feuser)

            ghost_dummy = DummyUser.objects.create(
                owning_feuser=other,
                display_name=_display_name(feuser),
            )

            BuddySpending.objects.filter(
                participant_feuser=feuser,
                expense__owning_feuser=other,
                expense__buddy_group__isnull=True,
            ).update(participant_feuser=None, participant_dummy=ghost_dummy)

            feuser_exps = Expense.objects.filter(
                owning_feuser=feuser,
                is_dummy=False,
                buddy_group__isnull=True,
                buddy_spendings__participant_feuser=other,
            ).distinct()
            for exp in feuser_exps:
                BuddyExpenseService.clone_expense_for_feuser(exp, other, ghost_dummy)

        BuddyLink.for_user(feuser).delete()

        # Handle group memberships: replace feuser with a group dummy in each group
        for membership in BuddyGroupMember.objects.filter(feuser=feuser).select_related("group"):
            group = membership.group
            if group.admin_feuser_id == feuser.pk:
                # Transfer admin to another feuser member, or dissolve if no others
                other_member = (
                    BuddyGroupMember.objects
                    .filter(group=group, feuser__isnull=False)
                    .exclude(feuser=feuser)
                    .select_related("feuser")
                    .first()
                )
                if other_member:
                    group.admin_feuser = other_member.feuser
                    group.save(update_fields=["admin_feuser"])
                else:
                    BuddyGroupService.dissolve_group(group, feuser)
                    continue

            BuddyGroupService.remove_member(group, group.admin_feuser, membership)

    @staticmethod
    @transaction.atomic
    def send_merge_invite(feuser, dummy: DummyUser, target_email: str):
        from feusers.models import FeUser

        target_email = target_email.strip().lower()
        try:
            invited = FeUser.objects.get(email__iexact=target_email, is_active=True)
        except FeUser.DoesNotExist:
            invited = None

        if invited is None:
            if settings.DISABLE_EMAILING:
                if not settings.ENABLE_REGISTRATION:
                    return ("registration_disabled", None)
                ob = BuddyOnboardingInvite(
                    inviting_feuser=feuser, dummy=dummy, invitee_email=target_email
                )
                ob.save()
                return ("onboarding_no_email", ob)
            if not settings.ENABLE_REGISTRATION:
                return ("registration_disabled", None)
            ob = BuddyOnboardingInvite(
                inviting_feuser=feuser, dummy=dummy, invitee_email=target_email
            )
            ob.save()
            BuddyEmailService.send_onboarding_invite(ob)
            return ("onboarding", ob)

        invite = DummyMergeInvite(
            inviting_feuser=feuser,
            dummy=dummy,
            invited_feuser=invited,
        )
        invite.save()
        BuddyEmailService.send_merge_invite(invite)
        return ("invite", invite)

    @staticmethod
    @transaction.atomic
    def accept_merge(token: str, accepting_feuser) -> bool:
        from budget.models import Expense

        try:
            invite = DummyMergeInvite.objects.select_related(
                "dummy", "inviting_feuser"
            ).get(token=token)
        except DummyMergeInvite.DoesNotExist:
            return False

        if not invite.is_valid():
            invite.delete()
            return False

        if invite.invited_feuser_id != accepting_feuser.pk:
            return False

        dummy = invite.dummy
        inviting_feuser = invite.inviting_feuser

        if dummy.owning_group_id:
            # Group dummy merge: delegate to group service
            invite.delete()
            return BuddyGroupService.accept_group_dummy_merge(token, accepting_feuser)

        for exp in Expense.objects.filter(upfront_payee_dummy=dummy, is_dummy=True):
            exp.owning_feuser = accepting_feuser
            exp.is_dummy = False
            exp.upfront_payee_dummy = None
            BuddyExpenseService.reconcile_categories_tags(exp, accepting_feuser)
            exp.save()

        BuddySpending.objects.filter(participant_dummy=dummy).update(
            participant_dummy=None,
            participant_feuser=accepting_feuser,
        )

        BuddyLifecycleService._create_link(inviting_feuser, accepting_feuser)

        dummy.delete()
        invite.delete()
        return True

    @staticmethod
    @transaction.atomic
    def complete_onboarding_invites(new_feuser) -> None:
        from django.utils import timezone
        from budget.models import Expense

        pending = BuddyOnboardingInvite.objects.filter(
            invitee_email__iexact=new_feuser.email,
            expires_at__gt=timezone.now(),
        ).select_related("inviting_feuser", "dummy", "group")

        for invite in pending:
            if invite.group_id and invite.dummy_id:
                # Group dummy merge
                BuddyLifecycleService._create_link(invite.inviting_feuser, new_feuser)
                dummy = invite.dummy
                group = invite.group
                for exp in Expense.objects.filter(upfront_payee_dummy=dummy, is_dummy=True):
                    exp.owning_feuser = new_feuser
                    exp.is_dummy = False
                    exp.upfront_payee_dummy = None
                    BuddyExpenseService.reconcile_categories_tags(exp, new_feuser)
                    exp.save()
                BuddySpending.objects.filter(participant_dummy=dummy).update(
                    participant_dummy=None, participant_feuser=new_feuser
                )
                dummy_member = BuddyGroupMember.objects.filter(group=group, dummy=dummy).first()
                if dummy_member:
                    dummy_member.delete()
                BuddyGroupMember.objects.get_or_create(group=group, feuser=new_feuser)
                dummy.delete()

            elif invite.group_id:
                # Group join (also creates buddy link)
                BuddyLifecycleService._create_link(invite.inviting_feuser, new_feuser)
                BuddyGroupMember.objects.get_or_create(group=invite.group, feuser=new_feuser)

            elif invite.dummy_id:
                # Personal dummy merge
                dummy = invite.dummy
                inviting_feuser = invite.inviting_feuser
                for exp in Expense.objects.filter(upfront_payee_dummy=dummy, is_dummy=True):
                    exp.owning_feuser = new_feuser
                    exp.is_dummy = False
                    exp.upfront_payee_dummy = None
                    BuddyExpenseService.reconcile_categories_tags(exp, new_feuser)
                    exp.save()
                BuddySpending.objects.filter(participant_dummy=dummy).update(
                    participant_dummy=None, participant_feuser=new_feuser
                )
                BuddyLifecycleService._create_link(inviting_feuser, new_feuser)
                dummy.delete()

            else:
                # Plain buddy invite
                BuddyLifecycleService._create_link(invite.inviting_feuser, new_feuser)

            invite.delete()

    @staticmethod
    @transaction.atomic
    def approve_expense(expense) -> bool:
        if expense.buddy_approved:
            return False
        expense.buddy_approved = True
        expense.save(update_fields=["buddy_approved"])
        return True

    @staticmethod
    @transaction.atomic
    def reject_expense(expense, rejecting_feuser) -> bool:
        if expense.buddy_approved:
            return False

        if expense.owning_feuser_id == rejecting_feuser.pk:
            expense.delete()
            return True

        bs_row = expense.buddy_spendings.filter(participant_feuser=rejecting_feuser).first()
        if not bs_row:
            return False

        released_share = bs_row.share_percent
        bs_row.delete()

        remaining = list(expense.buddy_spendings.all())
        if remaining:
            per_participant = released_share / len(remaining)
            for bs in remaining:
                bs.share_percent += per_participant
            BuddySpending.objects.bulk_update(remaining, ["share_percent"])

        expense.buddy_approved = True
        expense.save(update_fields=["buddy_approved"])

        remaining_actual = [
            bs.participant_feuser
            for bs in expense.buddy_spendings.select_related("participant_feuser").all()
            if bs.participant_feuser_id
        ]
        for participant in remaining_actual:
            BuddyEmailService.send_rejection_notification(
                expense=expense,
                rejecting_feuser=rejecting_feuser,
                notifying_feuser=participant,
            )

        return True


# ---------------------------------------------------------------------------
# BuddyEmailService
# ---------------------------------------------------------------------------

class BuddyEmailService:
    """All buddy-related email sending. Respects DISABLE_EMAILING and email_notifications."""

    @staticmethod
    def _send(subject: str, template: str, ctx: dict, recipient_email: str, respect_prefs: bool = True):
        if settings.DISABLE_EMAILING:
            return False

        if respect_prefs:
            feuser = ctx.get("feuser_recipient")
            if feuser and not feuser.email_notifications:
                return False

        html = render_to_string(template, {**ctx, "site_url": getattr(settings, "SITE_URL", "")})
        try:
            send_mail(
                subject=subject,
                message="",
                html_message=html,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"),
                recipient_list=[recipient_email],
            )
            return True
        except Exception:
            return False

    @staticmethod
    def send_buddy_invite(invite: BuddyInvite):
        site_url = getattr(settings, "SITE_URL", "")
        invite_url = f"{site_url}/buddies/invite/{invite.token}/"
        BuddyEmailService._send(
            subject=f"{_display_name(invite.inviter)} invited you to be spending buddies on Comaney",
            template="emails/buddy_invite.html",
            ctx={
                "invite": invite,
                "inviter_name": _display_name(invite.inviter),
                "invite_url": invite_url,
            },
            recipient_email=invite.invitee_email,
            respect_prefs=False,
        )

    @staticmethod
    def send_group_invite(invite: BuddyGroupInvite, invitee):
        site_url = getattr(settings, "SITE_URL", "")
        invite_url = f"{site_url}/buddies/group-invite/{invite.token}/"
        BuddyEmailService._send(
            subject=f"{_display_name(invite.inviting_feuser)} invited you to join the group \"{invite.group.name}\" on Comaney",
            template="emails/buddy_group_invite.html",
            ctx={
                "invite": invite,
                "inviter_name": _display_name(invite.inviting_feuser),
                "group_name": invite.group.name,
                "invite_url": invite_url,
                "feuser_recipient": invitee,
            },
            recipient_email=invite.invitee_email,
        )

    @staticmethod
    def send_group_onboarding_invite(invite: BuddyOnboardingInvite):
        site_url = getattr(settings, "SITE_URL", "")
        register_url = f"{site_url}/register/"
        BuddyEmailService._send(
            subject=f"{_display_name(invite.inviting_feuser)} invited you to join their group on Comaney",
            template="emails/buddy_onboarding_invite.html",
            ctx={
                "invite": invite,
                "inviter_name": _display_name(invite.inviting_feuser),
                "dummy_name": invite.dummy.display_name if invite.dummy_id else None,
                "is_merge": bool(invite.dummy_id),
                "is_group": True,
                "group_name": invite.group.name if invite.group_id else None,
                "register_url": register_url,
            },
            recipient_email=invite.invitee_email,
            respect_prefs=False,
        )

    @staticmethod
    def send_expense_approval_request(expense, initiating_feuser):
        site_url = getattr(settings, "SITE_URL", "")
        approve_url = f"{site_url}/buddies/expense/{expense.uid}/approve/"
        reject_url = f"{site_url}/buddies/expense/{expense.uid}/reject/"
        BuddyEmailService._send(
            subject=f"New shared expense needs your approval: {expense.title}",
            template="emails/buddy_expense_approval.html",
            ctx={
                "expense": expense,
                "initiating_name": _display_name(initiating_feuser),
                "approve_url": approve_url,
                "reject_url": reject_url,
                "feuser_recipient": expense.owning_feuser,
            },
            recipient_email=expense.owning_feuser.email,
        )

    @staticmethod
    def send_rejection_notification(expense, rejecting_feuser, notifying_feuser):
        site_url = getattr(settings, "SITE_URL", "")
        BuddyEmailService._send(
            subject=f"Shared expense rejected by {_display_name(rejecting_feuser)}: {expense.title}",
            template="emails/buddy_expense_rejected.html",
            ctx={
                "expense": expense,
                "rejecting_name": _display_name(rejecting_feuser),
                "feuser_recipient": notifying_feuser,
            },
            recipient_email=notifying_feuser.email,
        )

    @staticmethod
    def send_merge_invite(invite: DummyMergeInvite):
        site_url = getattr(settings, "SITE_URL", "")
        merge_url = f"{site_url}/buddies/merge/{invite.token}/"
        BuddyEmailService._send(
            subject=f"{_display_name(invite.inviting_feuser)} wants to link your account with their buddy record on Comaney",
            template="emails/buddy_merge_invite.html",
            ctx={
                "invite": invite,
                "inviting_name": _display_name(invite.inviting_feuser),
                "dummy_name": invite.dummy.display_name,
                "merge_url": merge_url,
                "feuser_recipient": invite.invited_feuser,
            },
            recipient_email=invite.invited_feuser.email,
        )

    @staticmethod
    def send_onboarding_invite(invite: BuddyOnboardingInvite):
        site_url = getattr(settings, "SITE_URL", "")
        register_url = f"{site_url}/register/"
        is_merge = invite.dummy_id is not None
        subject = (
            f"{_display_name(invite.inviting_feuser)} wants to link a buddy record with your account on Comaney"
            if is_merge else
            f"{_display_name(invite.inviting_feuser)} invited you to be spending buddies on Comaney"
        )
        BuddyEmailService._send(
            subject=subject,
            template="emails/buddy_onboarding_invite.html",
            ctx={
                "invite": invite,
                "inviter_name": _display_name(invite.inviting_feuser),
                "dummy_name": invite.dummy.display_name if is_merge else None,
                "is_merge": is_merge,
                "is_group": False,
                "group_name": None,
                "register_url": register_url,
            },
            recipient_email=invite.invitee_email,
            respect_prefs=False,
        )

    @staticmethod
    def send_kicked_notification(kicked_feuser, kicking_display_name: str):
        site_url = getattr(settings, "SITE_URL", "")
        BuddyEmailService._send(
            subject=f"{kicking_display_name} removed you as a spending buddy on Comaney",
            template="emails/buddy_kicked.html",
            ctx={
                "kicking_name": kicking_display_name,
                "feuser_recipient": kicked_feuser,
            },
            recipient_email=kicked_feuser.email,
        )
