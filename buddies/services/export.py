from __future__ import annotations

import csv
import io
from decimal import Decimal

from django.conf import settings
from django.db.models import Q

from comaney.csv_export import write_model_csv


def _in_date_range(exp, start_date, end_date) -> bool:
    """True if exp falls within [start_date, end_date], using date_due when
    set and falling back to date_created otherwise (matches the convention
    used by the project/buddy expense list filters)."""
    d = exp.date_due if exp.date_due else exp.date_created.date()
    return start_date <= d <= end_date


def _identity_id(feuser_obj=None, dummy_obj=None, *, self_feuser=None) -> str:
    """A stable, unambiguous id for a feuser or dummy: "u-<pk>" or "d-<pk>".
    Feusers and dummies have separate id spaces, so the prefix is required to
    tell them apart. Look up the display name via direct-buddies.csv /
    members.csv, which map these ids to names.

    If feuser_obj is the feuser the export is being generated for, returns
    "self" instead: that feuser is never listed under their own "u-<pk>" id
    in direct-buddies.csv (you aren't your own buddy), so that id would
    otherwise be undefined anywhere else in the export."""
    if feuser_obj is not None:
        if self_feuser is not None and feuser_obj.pk == self_feuser.pk:
            return "self"
        return f"u-{feuser_obj.pk}"
    return f"d-{dummy_obj.pk}"


def _build_participation_matrix_csv(expenses, self_feuser=None) -> str:
    """Build a participation matrix CSV: rows are expenses (by id), columns
    are participants identified by "u-<feuser_pk>" or "d-<dummy_pk>" ("self"
    for self_feuser), cells are each participant's share in percent. The
    payer's own implicit share (100% minus the recorded participant shares)
    is included too.

    `expenses` must be an iterable of Expense objects with
    select_related("owning_feuser", "upfront_payee_dummy") and
    prefetch_related("buddy_spendings__participant_feuser",
    "buddy_spendings__participant_dummy") already applied."""
    matrix_rows = []
    columns = []
    seen_columns = set()
    for exp in expenses:
        if exp.is_dummy and exp.upfront_payee_dummy_id:
            payer_id = _identity_id(dummy_obj=exp.upfront_payee_dummy)
        else:
            payer_id = _identity_id(feuser_obj=exp.owning_feuser, self_feuser=self_feuser)

        shares = {}
        total_pct = Decimal("0")
        for bs in exp.buddy_spendings.all():
            col = (
                _identity_id(feuser_obj=bs.participant_feuser, self_feuser=self_feuser)
                if bs.participant_feuser_id
                else _identity_id(dummy_obj=bs.participant_dummy)
            )
            shares[col] = shares.get(col, Decimal("0")) + bs.share_percent
            total_pct += bs.share_percent
            if col not in seen_columns:
                seen_columns.add(col)
                columns.append(col)

        shares[payer_id] = shares.get(payer_id, Decimal("0")) + (Decimal("100") - total_pct)
        if payer_id not in seen_columns:
            seen_columns.add(payer_id)
            columns.append(payer_id)

        matrix_rows.append((exp.pk, shares))

    columns.sort()
    p = io.StringIO()
    w = csv.writer(p)
    w.writerow(["expense_id"] + columns)
    for expense_id, shares in matrix_rows:
        w.writerow([expense_id] + [shares.get(col, "") for col in columns])
    return p.getvalue()


class BuddyExportService:
    """Builds the direct-buddy data export: direct-buddies.csv (the combined
    real-user + offline buddy roster), direct-buddy-expenses.csv (all
    personal, non-project expenses shared with a direct buddy, in either
    direction), and direct-buddy-expense-participation.csv (per-expense share
    percent by participant). Project-related participation is excluded: it
    is covered by ProjectExportService for each project membership.

    Used both by the standalone /buddies/summary/export/ endpoint (a ZIP,
    mirroring the per-project export) and by the account-wide data export.
    """

    @staticmethod
    def _direct_expenses_qs(feuser):
        from .query import BuddyQueryService
        return BuddyQueryService.shared_expenses(feuser).filter(project__isnull=True)

    @staticmethod
    def write_buddy_csvs(zf, feuser, prefix: str = "", start_date=None, end_date=None) -> None:
        """Write direct-buddies.csv, direct-buddy-expenses.csv,
        direct-buddy-expense-participation.csv, and offline buddies' profile
        pictures into the open ZipFile `zf`, with all filenames prefixed by
        `prefix` (e.g. "direct_buddies/").

        direct-buddies.csv and pictures are never date-filtered. If
        start_date/end_date are omitted, the expense files include all-time
        data (used by the comprehensive account-wide export)."""
        from ..models import BuddyLink, DummyUser

        # --------------------------------------------------------------
        # direct-buddies.csv: real-user and offline buddies, combined.
        # --------------------------------------------------------------
        personal_dummies = list(DummyUser.objects.filter(owning_feuser=feuser))
        p = io.StringIO()
        w = csv.writer(p)
        w.writerow(["buddy_type", "id", "display_name", "email", "since"])
        for link in BuddyLink.for_user(feuser).select_related("user_a", "user_b"):
            other = link.other(feuser)
            w.writerow([
                "feuser",
                _identity_id(feuser_obj=other),
                f"{other.first_name} {other.last_name}".strip(),
                other.email,
                link.created_at.isoformat(),
            ])
        for dummy in personal_dummies:
            w.writerow([
                "dummy", _identity_id(dummy_obj=dummy), dummy.display_name, "",
                dummy.created_at.isoformat(),
            ])
        zf.writestr(f"{prefix}direct-buddies.csv", p.getvalue())

        # --------------------------------------------------------------
        # direct-buddy-expenses.csv / direct-buddy-expense-participation.csv
        # --------------------------------------------------------------
        qs = BuddyExportService._direct_expenses_qs(feuser)
        if start_date and end_date:
            matching_pks = [exp.pk for exp in qs if _in_date_range(exp, start_date, end_date)]
            qs = qs.filter(pk__in=matching_pks)

        p = io.StringIO()
        write_model_csv(
            p, qs,
            skip={"category", "project"},
        )
        zf.writestr(f"{prefix}direct-buddy-expenses.csv", p.getvalue())

        zf.writestr(
            f"{prefix}direct-buddy-expense-participation.csv",
            _build_participation_matrix_csv(qs, self_feuser=feuser),
        )

        # --------------------------------------------------------------
        # Pictures: personal offline buddies' photos.
        # --------------------------------------------------------------
        for dummy in personal_dummies:
            if dummy.profile_picture:
                pic = settings.MEDIA_ROOT / "offline-buddy-ppic" / f"{dummy.pk}.jpg"
                if pic.exists():
                    zf.write(pic, f"{prefix}offline_buddies/{dummy.pk}.jpg")


class ProjectExportService:
    """Builds the CSV/media files for a single project's data export.

    Used both by the standalone per-project export endpoint and by the
    account-wide data export, which nests one copy per project membership.
    """

    @staticmethod
    def write_project_csvs(zf, project, feuser, prefix: str = "", start_date=None, end_date=None) -> None:
        """Write meta.csv, members.csv, expenses.csv, participation_matrix.csv,
        and any pictures for `project` into the open ZipFile `zf`, with all
        filenames prefixed by `prefix` (e.g. "projects/<uid>/"). `feuser` is
        the feuser the export is being generated for, so their own id can be
        shown as "self" in members.csv and participation_matrix.csv.

        meta.csv, members.csv, and pictures are never date-filtered. If
        start_date/end_date are omitted, expenses.csv and
        participation_matrix.csv include all-time data (used by the
        comprehensive account-wide export)."""
        from budget.models import Expense

        # --------------------------------------------------------------
        # meta.csv: project settings.
        # --------------------------------------------------------------
        p = io.StringIO()
        w = csv.writer(p)
        w.writerow(["field", "value"])
        w.writerow(["uid", project.pk])
        w.writerow(["name", project.name])
        w.writerow(["description", project.description])
        w.writerow(["admin_id", _identity_id(feuser_obj=project.admin_feuser, self_feuser=feuser)])
        w.writerow(["has_picture", project.group_picture])
        w.writerow(["created_at", project.created_at.isoformat()])
        w.writerow(["archived", project.archived])
        w.writerow(["last_mod", project.last_mod.isoformat()])
        zf.writestr(f"{prefix}meta.csv", p.getvalue())

        # --------------------------------------------------------------
        # members.csv: the member roster.
        # --------------------------------------------------------------
        members = list(project.members.all())
        p = io.StringIO()
        w = csv.writer(p)
        w.writerow(["member_type", "id", "display_name", "email", "is_admin", "joined_at"])
        for m in members:
            if m.feuser_id:
                w.writerow([
                    "feuser",
                    _identity_id(feuser_obj=m.feuser, self_feuser=feuser),
                    f"{m.feuser.first_name} {m.feuser.last_name}".strip(),
                    m.feuser.email,
                    m.feuser_id == project.admin_feuser_id,
                    m.joined_at.isoformat(),
                ])
            else:
                w.writerow([
                    "dummy", _identity_id(dummy_obj=m.dummy), m.dummy.display_name, "",
                    False, m.joined_at.isoformat(),
                ])
        zf.writestr(f"{prefix}members.csv", p.getvalue())

        # --------------------------------------------------------------
        # expenses.csv: every expense ever recorded in this project.
        # --------------------------------------------------------------
        expenses_qs = (
            Expense.objects.filter(project=project)
            .prefetch_related("tags")
            .order_by("date_created")
        )
        if start_date and end_date:
            matching_pks = [exp.pk for exp in expenses_qs if _in_date_range(exp, start_date, end_date)]
            expenses_qs = expenses_qs.filter(pk__in=matching_pks)
        p = io.StringIO()
        write_model_csv(
            p, expenses_qs, skip={"project"},
            extra=[("tag_ids", lambda obj: ",".join(str(t.uid) for t in obj.tags.all()))],
        )
        zf.writestr(f"{prefix}expenses.csv", p.getvalue())

        # --------------------------------------------------------------
        # participation_matrix.csv
        # --------------------------------------------------------------
        matrix_qs = (
            Expense.objects.filter(project=project)
            .select_related("owning_feuser", "upfront_payee_dummy")
            .prefetch_related("buddy_spendings__participant_feuser", "buddy_spendings__participant_dummy")
            .order_by("date_created")
        )
        if start_date and end_date:
            matrix_qs = [exp for exp in matrix_qs if _in_date_range(exp, start_date, end_date)]
        zf.writestr(
            f"{prefix}participation_matrix.csv",
            _build_participation_matrix_csv(matrix_qs, self_feuser=feuser),
        )

        # --------------------------------------------------------------
        # Pictures: the project's cover image, and offline members' photos.
        # --------------------------------------------------------------
        if project.group_picture:
            pic = settings.MEDIA_ROOT / "bgpics" / f"{project.pk}.webp"
            if pic.exists():
                zf.write(pic, f"{prefix}project_picture.webp")

        for m in members:
            if m.dummy_id and m.dummy.profile_picture:
                pic = settings.MEDIA_ROOT / "offline-buddy-ppic" / f"{m.dummy.pk}.jpg"
                if pic.exists():
                    zf.write(pic, f"{prefix}offline_members/{m.dummy.pk}.jpg")
