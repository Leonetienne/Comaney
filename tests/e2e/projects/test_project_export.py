"""
Project data export (ZIP):
- Returns application/zip
- Contains meta.csv, members.csv, expenses.csv, participation_matrix.csv
- meta.csv lists project settings (never date-filtered)
- members.csv lists the member roster (never date-filtered)
- expenses.csv lists expenses logged within the selected date range
- participation_matrix.csv has one row per expense within that range, with
  each participant's share in percent (payer's implicit share included)
- Any project member (not just the admin) can export
- Non-members and unauthenticated requests are denied
- expenses.csv/participation_matrix.csv respect an explicit date_from/date_to
  range; with no params given, they default to the current financial month
  (NOT all-time -- that is only the case for the account-wide export)
"""
import io
import time
import zipfile

import pytest
import requests

from helpers import _url, setup_user, cleanup_user, session_cookies
from bhelpers import _shell, _login_as, _get_pk, _create_group, _add_group_member, _create_group_expense


def _get_export(driver, project_id, date_from=None, date_to=None):
    """Download the project export ZIP using the browser's session cookies."""
    cookies = session_cookies(driver)
    params = {}
    if date_from and date_to:
        params = {"date_from": date_from, "date_to": date_to}
    return requests.get(_url(f"/projects/{project_id}/export/"), cookies=cookies, params=params, timeout=30)


def _read_csv(zf, name):
    return zf.read(name).decode()


class TestProjectExport:
    """Admin Eve owns a project with member Bob holding a 25% share of one
    expense; outsider Olivia is never added to the project."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Eve", last_name="Exporter")
        b = setup_user(None, None, first_name="Bob", last_name="Buddy")
        o = setup_user(None, None, first_name="Olivia", last_name="Outsider")
        gid = int(_create_group(a["email"], "Export Test Project"))
        _add_group_member(gid, b["email"])
        exp_id = int(_create_group_expense(
            a["email"], b["email"], gid,
            title="ExportMatrixExpense", value="80.00", share="25.0",
        ))
        b_id = f"u-{_get_pk(b['email'])}"
        yield {"a": a, "b": b, "o": o, "gid": gid, "exp_id": exp_id, "b_id": b_id}
        cleanup_user(a["email"])
        cleanup_user(b["email"])
        cleanup_user(o["email"])

    def test_export_returns_zip_with_expected_csvs(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        resp = _get_export(driver, ctx["gid"])
        assert resp.status_code == 200
        assert "application/zip" in resp.headers.get("Content-Type", "")
        assert resp.content[:2] == b"PK", "Response must be a valid ZIP file"

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            names = zf.namelist()
        for expected in ("meta.csv", "members.csv", "expenses.csv", "participation_matrix.csv"):
            assert expected in names, f"{expected} missing from project export ZIP"

    def test_meta_csv_has_settings(self, driver, w, ctx):
        """The exporting admin (Eve, logged in) is also the project admin, so
        admin_id shows "self" rather than "u-<her pk>"."""
        resp = _get_export(driver, ctx["gid"])
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            meta_csv = _read_csv(zf, "meta.csv")

        assert "Export Test Project" in meta_csv, "Project name missing from meta.csv"
        assert "admin_id,self" in meta_csv, "Admin id (self) missing from meta.csv"

    def test_members_csv_has_roster(self, driver, w, ctx):
        """The exporting admin (Eve, logged in) shows up as "self"; other
        members keep their u-<pk> id."""
        resp = _get_export(driver, ctx["gid"])
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            members_csv = _read_csv(zf, "members.csv")

        assert "self" in members_csv, "Exporting admin's own id (self) missing from members.csv"
        assert ctx["a"]["email"] in members_csv, "Admin email missing from members.csv"
        assert ctx["b_id"] in members_csv, "Member id missing from members.csv"
        assert ctx["b"]["email"] in members_csv, "Member email missing from members.csv"

    def test_expenses_csv_has_project_expense(self, driver, w, ctx):
        resp = _get_export(driver, ctx["gid"])
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            expenses_csv = _read_csv(zf, "expenses.csv")

        assert "ExportMatrixExpense" in expenses_csv, "Expense title missing from expenses.csv"

    def test_participation_matrix_has_shares(self, driver, w, ctx):
        """The exporting admin (Eve, logged in) is the payer here and shows up
        as "self" in the matrix; the other participant keeps their u-<pk> id."""
        resp = _get_export(driver, ctx["gid"])
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            matrix_csv = _read_csv(zf, "participation_matrix.csv")

        lines = matrix_csv.splitlines()
        header = lines[0]
        assert "self" in header, "Payer (admin, exporting) self id missing from matrix header"
        assert ctx["b_id"] in header, "Participant id missing from matrix header"

        data_row = next(l for l in lines[1:] if l.startswith(f"{ctx['exp_id']},"))
        cols = header.split(",")
        row = dict(zip(cols, data_row.split(",")))
        assert row[ctx["b_id"]] == "25.000", "Participant share_percent missing/incorrect"
        assert row["self"] == "75.000", "Payer's implicit share missing/incorrect"

    def test_date_range_filters_expenses_but_not_meta_or_members(self, driver, w, ctx):
        """An explicit date_from/date_to must exclude out-of-range expenses from
        expenses.csv and participation_matrix.csv, but meta.csv/members.csv must
        always reflect the full, unfiltered project (settings/roster aren't
        time-scoped)."""
        old_exp_id = int(_shell(
            f"from budget.models import Expense; "
            f"from feusers.models import FeUser; "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"e = Expense.objects.create(owning_feuser=a, title='OldRangeExpense', "
            f"  type='expense', value='10.00', date_due='2000-01-01', "
            f"  settled=True, buddy_approved=True, project_id={ctx['gid']}); "
            f"print(e.pk)"
        ))
        try:
            # A far-future-only range must exclude both the old expense and
            # today's ExportMatrixExpense (created via the ctx fixture, date_due unset).
            resp = _get_export(driver, ctx["gid"], date_from="2099-01-01", date_to="2099-12-31")
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                expenses_csv = _read_csv(zf, "expenses.csv")
                matrix_rows = [l.split(",")[0] for l in _read_csv(zf, "participation_matrix.csv").splitlines()[1:]]
                meta_csv = _read_csv(zf, "meta.csv")
                members_csv = _read_csv(zf, "members.csv")

            assert "OldRangeExpense" not in expenses_csv, "Out-of-range expense leaked into expenses.csv"
            assert "ExportMatrixExpense" not in expenses_csv, "In-range-but-unrelated expense leaked into expenses.csv"
            assert str(old_exp_id) not in matrix_rows, "Out-of-range expense leaked into participation_matrix.csv"
            assert "Export Test Project" in meta_csv, "meta.csv must not be affected by date filtering"
            assert ctx["b"]["email"] in members_csv, "members.csv must not be affected by date filtering"

            # A wide range covering 2000 must include the old expense again,
            # in both expenses.csv and participation_matrix.csv.
            wide_resp = _get_export(driver, ctx["gid"], date_from="1999-01-01", date_to="2099-12-31")
            with zipfile.ZipFile(io.BytesIO(wide_resp.content)) as zf:
                wide_expenses_csv = _read_csv(zf, "expenses.csv")
                wide_matrix_rows = [l.split(",")[0] for l in _read_csv(zf, "participation_matrix.csv").splitlines()[1:]]
            assert "OldRangeExpense" in wide_expenses_csv, "Wide range must include the old expense"
            assert str(old_exp_id) in wide_matrix_rows, "Wide range must include the old expense in the matrix"
        finally:
            _shell(f"from budget.models import Expense; Expense.objects.filter(pk={old_exp_id}).delete()")

    def test_no_date_params_defaults_to_current_month_not_all_time(self, driver, w, ctx):
        """Omitting date_from/date_to entirely must NOT silently export all-time
        data: it must fall back to the current financial month, exactly like the
        date-range nav's own default. An old expense must still be excluded."""
        old_exp_id = int(_shell(
            f"from budget.models import Expense; "
            f"from feusers.models import FeUser; "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); "
            f"e = Expense.objects.create(owning_feuser=a, title='NoParamsOldExpense', "
            f"  type='expense', value='10.00', date_due='2000-01-01', "
            f"  settled=True, buddy_approved=True, project_id={ctx['gid']}); "
            f"print(e.pk)"
        ))
        try:
            resp = _get_export(driver, ctx["gid"])
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                expenses_csv = _read_csv(zf, "expenses.csv")
            assert "NoParamsOldExpense" not in expenses_csv, (
                "No date params must default to the current month, not all-time"
            )
            assert "ExportMatrixExpense" in expenses_csv, (
                "Today's expense (date_due unset) must still appear under the default current-month range"
            )
        finally:
            _shell(f"from budget.models import Expense; Expense.objects.filter(pk={old_exp_id}).delete()")

    def test_member_can_export_not_just_admin(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        resp = _get_export(driver, ctx["gid"])
        assert resp.status_code == 200
        assert "application/zip" in resp.headers.get("Content-Type", "")

    def test_non_member_cannot_export(self, driver, w, ctx):
        _login_as(driver, ctx["o"])
        resp = _get_export(driver, ctx["gid"])
        assert resp.status_code == 404

    def test_export_link_on_detail_not_settings(self, driver, w, ctx):
        """The small Export ZIP link lives on the project Overview (detail) page,
        not in a dedicated section on the Manage (settings) page."""
        _login_as(driver, ctx["a"])
        driver.get(_url(f"/projects/{ctx['gid']}/"))
        time.sleep(1)
        assert "Export ZIP" in driver.page_source, "Export link missing from project Overview page"

        driver.get(_url(f"/projects/{ctx['gid']}/settings/"))
        time.sleep(1)
        assert "Export project data" not in driver.page_source, (
            "The old dedicated Export section must be removed from the Manage page"
        )

    def test_export_requires_authentication(self, driver, w, ctx):
        resp = requests.get(
            _url(f"/projects/{ctx['gid']}/export/"), timeout=10, allow_redirects=False,
        )
        assert resp.status_code in (302, 403), (
            f"Unauthenticated export must redirect or deny, got {resp.status_code}"
        )
