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

from .models import BuddyInvite, BuddyLink, BuddySpending, DummyMergeInvite, DummyUser


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
        """Return queryset of DummyUser objects owned by feuser."""
        return list(DummyUser.objects.filter(owning_feuser=feuser))

    @staticmethod
    def are_buddies(feuser_a, feuser_b) -> bool:
        return BuddyLink.between(feuser_a, feuser_b) is not None

    @staticmethod
    def get_net_debt(feuser, buddy_feuser=None, buddy_dummy=None) -> Decimal:
        """
        Net debt from feuser's perspective.
        Positive = buddy owes feuser. Negative = feuser owes buddy.
        Exactly one of buddy_feuser / buddy_dummy must be provided.
        """
        from budget.models import Expense

        owed_to_me = Decimal("0")
        i_owe = Decimal("0")

        if buddy_feuser is not None:
            # Buddy owes me: expenses I own where buddy is a participant
            owed_to_me = sum(
                (bs.expense.value * bs.share_percent / 100)
                for bs in BuddySpending.objects.filter(
                    participant_feuser=buddy_feuser,
                    expense__owning_feuser=feuser,
                    expense__is_dummy=False,
                ).select_related("expense")
            )

            # I owe buddy: expenses buddy owns where I am a participant
            i_owe = sum(
                (bs.expense.value * bs.share_percent / 100)
                for bs in BuddySpending.objects.filter(
                    participant_feuser=feuser,
                    expense__owning_feuser=buddy_feuser,
                    expense__is_dummy=False,
                ).select_related("expense")
            )

        elif buddy_dummy is not None:
            # Dummy owes me: expenses I own where dummy is a participant
            owed_to_me = sum(
                (bs.expense.value * bs.share_percent / 100)
                for bs in BuddySpending.objects.filter(
                    participant_dummy=buddy_dummy,
                    expense__owning_feuser=feuser,
                    expense__is_dummy=False,
                ).select_related("expense")
            )

            # I owe dummy: dummy-payer expenses owned by feuser
            dummy_expenses = Expense.objects.filter(
                owning_feuser=feuser,
                upfront_payee_dummy=buddy_dummy,
                is_dummy=True,
            ).prefetch_related("buddy_spendings")
            for exp in dummy_expenses:
                participant_sum = sum(
                    bs.share_percent for bs in exp.buddy_spendings.all()
                )
                my_implicit_share = Decimal("100") - participant_sum
                i_owe += exp.value * my_implicit_share / 100

        return Decimal(owed_to_me) - Decimal(i_owe)

    @staticmethod
    def get_all_debts(feuser) -> dict:
        """
        Return a dict with two keys:
          'actual': {feuser_id: {'feuser': FeUser, 'link': BuddyLink, 'net': Decimal, 'net_abs': Decimal}, ...}
          'dummy':  {dummy_id:  {'dummy': DummyUser, 'net': Decimal, 'net_abs': Decimal}, ...}
        """
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
        """
        Queryset of all buddy-related expenses visible to feuser:
        - Owned by feuser (is_dummy or not) with BuddySpending rows
        - Owned by buddy actual users where feuser is a BuddySpending participant
        """
        from budget.models import Expense

        buddy_feuserids = [b.pk for b in BuddyQueryService.get_actual_buddies(feuser)]

        return (
            Expense.objects
            .filter(
                Q(owning_feuser=feuser, buddy_spendings__isnull=False) |
                Q(owning_feuser=feuser, is_dummy=True) |
                Q(owning_feuser_id__in=buddy_feuserids, buddy_spendings__participant_feuser=feuser)
            )
            .distinct()
            .select_related("owning_feuser", "category", "upfront_payee_dummy")
            .prefetch_related("buddy_spendings__participant_feuser", "buddy_spendings__participant_dummy", "tags")
            .order_by("-date_created")
        )

    @staticmethod
    def pending_invites_incoming(feuser):
        """BuddyInvites sent to feuser's email that are still valid."""
        from django.utils import timezone
        return BuddyInvite.objects.filter(
            invitee_email=feuser.email,
            expires_at__gt=timezone.now(),
        ).select_related("inviter")

    @staticmethod
    def pending_invites_outgoing(feuser):
        """BuddyInvites sent by feuser that are still valid."""
        from django.utils import timezone
        return BuddyInvite.objects.filter(
            inviter=feuser,
            expires_at__gt=timezone.now(),
        )

    @staticmethod
    def pending_merge_invites_incoming(feuser):
        """DummyMergeInvites sent to feuser that are still valid."""
        from django.utils import timezone
        return DummyMergeInvite.objects.filter(
            invited_feuser=feuser,
            expires_at__gt=timezone.now(),
        ).select_related("inviting_feuser", "dummy")


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
        The expense owner must NOT appear in participants.
        """
        from feusers.models import FeUser

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
        Keeps matches (updates FK), drops non-matches.
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
        Category/tag reconciliation applied. BuddySpending rows copied (excluding target_feuser).
        """
        clone = _clone_expense_object(source_expense, target_feuser)
        clone.is_dummy = True
        clone.upfront_payee_dummy = dummy_payer
        clone.buddy_approved = True
        # Category already reconciled inside _clone_expense_object; tags are set
        # after save because M2M requires a saved instance.
        clone.save()
        clone.tags.set(list(clone._reconciled_tags) if hasattr(clone, "_reconciled_tags") else [])

        # Copy BuddySpending rows, skipping target_feuser (now the owner)
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
        Adjusts BuddySpending rows to maintain consistency.
        Returns (old_owner, new_expense) where new_expense may be the same object
        or a different Expense if ownership changed.
        See requirement 6.1-6.4 for rules.
        """
        old_owner = expense.owning_feuser
        old_dummy_payer = expense.upfront_payee_dummy

        if new_payer_feuser is not None and new_payer_feuser != old_owner:
            # 6.1 / 6.3: actual user takes over as payer
            # Remove new payer from participants; add old payer as participant
            old_share = None
            new_payer_bs = expense.buddy_spendings.filter(participant_feuser=new_payer_feuser).first()
            if new_payer_bs:
                old_share = new_payer_bs.share_percent
                new_payer_bs.delete()

            # Add old_owner as participant (implicit share of old payer = 100 - sum of others)
            participant_sum = sum(
                bs.share_percent for bs in expense.buddy_spendings.all()
            )
            old_owner_share = Decimal("100") - participant_sum

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

            # Transfer ownership
            expense.owning_feuser = new_payer_feuser
            expense.is_dummy = False
            expense.upfront_payee_dummy = None
            expense.buddy_approved = False
            BuddyExpenseService.reconcile_categories_tags(expense, new_payer_feuser)
            expense.save()

        elif new_payer_dummy is not None and new_payer_dummy != old_dummy_payer:
            # 6.2 / 6.4: dummy becomes payer
            # Remove new dummy from participants; add old payer as participant
            dummy_bs = expense.buddy_spendings.filter(participant_dummy=new_payer_dummy).first()
            if dummy_bs:
                dummy_bs.delete()

            participant_sum = sum(bs.share_percent for bs in expense.buddy_spendings.all())
            old_payer_share = Decimal("100") - participant_sum

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
    # Reconcile category before saving (tags done after save due to M2M)
    if clone.category_id:
        from budget.models import Category
        try:
            clone.category = Category.objects.get(
                owning_feuser=target_feuser,
                title=source.category.title,
            )
        except Category.DoesNotExist:
            clone.category = None

    # Pre-compute matched tags so they can be set after save
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
        Invite an actual user by email.
        If DISABLE_EMAILING: create BuddyLink immediately (dev mode).
        Otherwise: create BuddyInvite and send email.
        Returns ('link', BuddyLink) or ('invite', BuddyInvite) or ('already_buddies', None).
        """
        from feusers.models import FeUser

        email = email.strip().lower()

        # Self-invite guard
        if email == feuser.email.lower():
            return ("self", None)

        # Already buddies?
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
            return ("not_found", None)

        invite = BuddyInvite(inviter=feuser, invitee_email=email)
        invite.save()
        BuddyEmailService.send_buddy_invite(invite)
        return ("invite", invite)

    @staticmethod
    def _create_link(feuser_a, feuser_b) -> BuddyLink:
        lo, hi = sorted([feuser_a, feuser_b], key=lambda u: u.pk)
        link, _ = BuddyLink.objects.get_or_create(user_a=lo, user_b=hi)
        return link

    @staticmethod
    @transaction.atomic
    def accept_invite(token: str, accepting_feuser) -> BuddyLink | None:
        """Accept a BuddyInvite. Returns the created link or None if invalid."""
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
        """
        Remove a dummy buddy. Returns {'debt_warning': Decimal} if over threshold and not accepted,
        else {'kicked': True}.
        """
        net = BuddyQueryService.get_net_debt(feuser, buddy_dummy=dummy)
        if abs(net) > Decimal("0.05") and not has_debt_warning_accepted:
            return {"debt_warning": net}

        # Delete BuddySpending rows where dummy is a participant
        BuddySpending.objects.filter(participant_dummy=dummy).delete()
        # Delete dummy expenses where dummy is the upfront payer
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
        """
        Kick an actual buddy. Non-consensual for other_feuser.
        Returns {'debt_warning': Decimal} if threshold exceeded and not accepted,
        else {'kicked': True}.
        """
        from budget.models import Expense

        net = BuddyQueryService.get_net_debt(feuser, buddy_feuser=other_feuser)
        if abs(net) > Decimal("0.05") and not has_debt_warning_accepted:
            return {"debt_warning": net}

        link = BuddyLink.between(feuser, other_feuser)
        if not link:
            return {"kicked": True}

        # --- For feuser (consensual): remove BuddySpending rows on feuser's expenses ---
        feuser_expenses_with_other = Expense.objects.filter(
            owning_feuser=feuser,
            is_dummy=False,
            buddy_spendings__participant_feuser=other_feuser,
        ).distinct()
        for exp in feuser_expenses_with_other:
            # Clone the expense for other_feuser before removing their row
            new_dummy = DummyUser.objects.create(
                owning_feuser=other_feuser,
                display_name=_display_name(feuser),
            )
            BuddyExpenseService.clone_expense_for_feuser(exp, other_feuser, new_dummy)
            exp.buddy_spendings.filter(participant_feuser=other_feuser).delete()

        # --- For other_feuser (non-consensual): replace feuser with a dummy ---
        # This dummy may already exist from above; reuse it if possible.
        # Create a single dummy to represent feuser on other_feuser's side.
        kicker_dummy_for_other = DummyUser.objects.create(
            owning_feuser=other_feuser,
            display_name=_display_name(feuser),
        )
        BuddySpending.objects.filter(
            participant_feuser=feuser,
            expense__owning_feuser=other_feuser,
        ).update(
            participant_feuser=None,
            participant_dummy=kicker_dummy_for_other,
        )

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
        Called before feuser.delete(). Converts all actual buddy relationships
        to dummy relationships from the other user's perspective.
        """
        from budget.models import Expense

        for link in BuddyLink.for_user(feuser):
            other = link.other(feuser)

            # Create dummy representing feuser on other's side
            ghost_dummy = DummyUser.objects.create(
                owning_feuser=other,
                display_name=_display_name(feuser),
            )

            # Update BuddySpending rows on other's expenses
            BuddySpending.objects.filter(
                participant_feuser=feuser,
                expense__owning_feuser=other,
            ).update(
                participant_feuser=None,
                participant_dummy=ghost_dummy,
            )

            # Clone feuser's expenses where other was a participant
            feuser_exps = Expense.objects.filter(
                owning_feuser=feuser,
                is_dummy=False,
                buddy_spendings__participant_feuser=other,
            ).distinct()
            for exp in feuser_exps:
                BuddyExpenseService.clone_expense_for_feuser(exp, other, ghost_dummy)

        BuddyLink.for_user(feuser).delete()

    @staticmethod
    @transaction.atomic
    def send_merge_invite(feuser, dummy: DummyUser, target_email: str):
        """
        Send a DummyMergeInvite for dummy -> actual user at target_email.
        Returns ('invite', invite) or ('not_found', None).
        """
        from feusers.models import FeUser

        target_email = target_email.strip().lower()
        try:
            invited = FeUser.objects.get(email__iexact=target_email, is_active=True)
        except FeUser.DoesNotExist:
            return ("not_found", None)

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
        """
        Accept a DummyMergeInvite.
        Transfers dummy's expense history to accepting_feuser and creates BuddyLink.
        Returns True on success, False on invalid/expired token.
        """
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

        # Transfer expenses where dummy was the upfront payer
        for exp in Expense.objects.filter(upfront_payee_dummy=dummy, is_dummy=True):
            exp.owning_feuser = accepting_feuser
            exp.is_dummy = False
            exp.upfront_payee_dummy = None
            BuddyExpenseService.reconcile_categories_tags(exp, accepting_feuser)
            exp.save()

        # Transfer BuddySpending rows referencing dummy
        BuddySpending.objects.filter(participant_dummy=dummy).update(
            participant_dummy=None,
            participant_feuser=accepting_feuser,
        )

        # Establish the actual buddy link
        BuddyLifecycleService._create_link(inviting_feuser, accepting_feuser)

        dummy.delete()
        invite.delete()
        return True

    @staticmethod
    @transaction.atomic
    def approve_expense(expense) -> bool:
        """Approve a buddy expense (buddy_approved=False -> True)."""
        if expense.buddy_approved:
            return False
        expense.buddy_approved = True
        expense.save(update_fields=["buddy_approved"])
        return True

    @staticmethod
    @transaction.atomic
    def reject_expense(expense, rejecting_feuser) -> bool:
        """
        Reject a buddy expense (buddy_approved=False).
        If rejecting_feuser is the expense owner, the expense is deleted entirely
        (they deny having paid for it). Otherwise, removes rejecting_feuser from
        BuddySpending and redistributes their share equally among remaining
        participants. Notifies all remaining actual-user participants.
        Returns True on success.
        """
        if expense.buddy_approved:
            return False

        # Owner rejecting: they say the payment never happened on their side
        if expense.owning_feuser_id == rejecting_feuser.pk:
            expense.delete()
            return True

        bs_row = expense.buddy_spendings.filter(participant_feuser=rejecting_feuser).first()
        if not bs_row:
            return False

        released_share = bs_row.share_percent
        bs_row.delete()

        # Redistribute released share equally among remaining participants
        remaining = list(expense.buddy_spendings.all())
        if remaining:
            per_participant = released_share / len(remaining)
            for bs in remaining:
                bs.share_percent += per_participant
            BuddySpending.objects.bulk_update(remaining, ["share_percent"])

        # Set approved since it's no longer "pending" for the rejector
        expense.buddy_approved = True
        expense.save(update_fields=["buddy_approved"])

        # Notify remaining actual-user participants
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
        """Low-level send. Returns True if sent."""
        if settings.DISABLE_EMAILING:
            return False

        # Check per-user preference if we have the feuser
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
        # Link to the view page (GET), not the accept endpoint (POST-only).
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
    def send_expense_approval_request(expense, initiating_feuser):
        """Sent to expense.owning_feuser (B) when A creates an expense for them."""
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
        # Link to the view page (GET), not the accept endpoint (POST-only).
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
