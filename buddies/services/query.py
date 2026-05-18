from __future__ import annotations

from decimal import Decimal

from django.db.models import Q

from feusers.templatetags.feuser_tags import avatar_color as _avatar_color

from ..debt_utils import simplify_balances
from ..models import (
    BuddyGroup,
    BuddyGroupInvite,
    BuddyInvite,
    BuddyLink,
    BuddySpending,
    DummyMergeInvite,
    DummyUser,
)
from ._helpers import _display_name


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
            group_total_spending = Decimal("0")
            expenses = (
                Expense.objects
                .filter(buddy_group=group, buddy_approved=True)
                .prefetch_related("buddy_spendings")
            )
            for exp in expenses:
                if not exp.is_buddies_settlement:
                    group_total_spending += exp.value
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

            member_names = []
            for m in group.members.all():
                if m.feuser_id:
                    if m.feuser_id == feuser.pk:
                        member_names.append(("You", True))
                    else:
                        name = f"{m.feuser.first_name} {m.feuser.last_name}".strip() or m.feuser.email
                        member_names.append((name, False))
                else:
                    member_names.append((m.dummy.display_name + " (offline member)", False))
            member_names.sort(key=lambda x: (0 if x[1] else 1, x[0]))
            all_names = [n for n, _ in member_names]
            members_display = all_names[:MAX_SHOWN]
            extra = max(0, len(all_names) - MAX_SHOWN)

            net_abs = abs(net)
            if net > Decimal("0.02"):
                net_state = "positive"
            elif net < Decimal("-0.02"):
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
                "group_total_spending": group_total_spending,
                "has_multiple_members": len(all_names) > 1,
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
                        "ppicUrl": fu.ppic_url if fu.profile_picture else "",
                        "initials": fu.initials,
                        "avatarColor": _avatar_color(fu.initials),
                    })
                else:
                    members.append({
                        "type": "dummy",
                        "id": m.dummy_id,
                        "name": m.dummy.display_name + " (offline member)",
                        "is_me": False,
                        "ppicUrl": m.dummy.ppic_url if m.dummy.profile_picture else "",
                        "initials": m.dummy.initials,
                        "avatarColor": _avatar_color(m.dummy.initials),
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
                spendings = list(exp.buddy_spendings.all())
                feuser_bs = next(
                    (bs for bs in spendings if bs.participant_feuser_id == feuser.pk), None
                )
                if feuser_bs is not None:
                    i_owe += exp.value * feuser_bs.share_percent / 100
                else:
                    participant_sum = sum(bs.share_percent for bs in spendings)
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
                    "user_obj": m.feuser,
                }
            else:
                key = f"d{m.dummy_id}"
                member_map[key] = {
                    "name": m.dummy.display_name + " (offline member)",
                    "is_me": False,
                    "user_obj": m.dummy,
                }

        balances: dict[str, Decimal] = {k: Decimal("0") for k in member_map}

        feuser_key = f"f{feuser.pk}"
        expenses_qs = (
            Expense.objects
            .filter(buddy_group=group)
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
                p_info = member_map.get(pk, {"name": "Unknown", "is_me": False, "user_obj": None})
                participant_shares.append({
                    "key": pk,
                    "name": p_info["name"],
                    "is_me": p_info["is_me"],
                    "user_obj": p_info.get("user_obj"),
                    "amount": amount,
                    "percent": bs.share_percent,
                })
                if exp.buddy_approved and pk in balances:
                    balances[pk] -= amount
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
                "payer_obj": payer_info.get("user_obj"),
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
            'link_uid': int | None,
          }, ...
        ] sorted by abs(net) descending.
        """
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

        for link in BuddyLink.for_user(feuser).select_related("user_a", "user_b"):
            buddy = link.other(feuser)
            net = BuddyQueryService.get_net_debt(feuser, buddy_feuser=buddy)
            _upsert(("feuser", buddy.pk), "feuser", buddy, "Direct", net, link_uid=link.uid)

        for dummy in DummyUser.objects.filter(owning_feuser=feuser):
            net = BuddyQueryService.get_net_debt(feuser, buddy_dummy=dummy)
            _upsert(("dummy", dummy.pk), "dummy", dummy, "Direct", net)

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
