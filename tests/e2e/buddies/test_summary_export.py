"""
Buddy summary export (/buddies/summary/export/), a ZIP mirroring the
per-project export:
- Returns application/zip
- Contains direct-buddies.csv, direct-buddy-expenses.csv,
  direct-buddy-expense-participation.csv
- direct-buddies.csv combines real-user and offline buddies into one roster,
  identified by "u-<pk>"/"d-<pk>"
- direct-buddy-expenses.csv covers both directions of a direct-buddy
  relationship: expenses a buddy owns where the feuser participates, the
  feuser's own expenses shared with a buddy, and the feuser's own expenses
  where a personal offline buddy paid upfront. Same column scheme as
  expenses.csv: raw owning_feuser_id/upfront_payee_dummy_id, no extra column
- direct-buddy-expense-participation.csv has one row per expense with each
  participant's share in percent (payer's implicit share included); the
  exporting feuser's own column is "self" rather than "u-<their pk>", since
  they are never listed under that id in direct-buddies.csv
- Project expense participation is excluded (covered by the project export)
- Respects an explicit date_from/date_to range; with no params given, defaults
  to the current financial month (NOT all-time -- only the account-wide
  export is all-time)
- Unauthenticated request is redirected
"""
import io
import time
import zipfile

import requests

from helpers import _url, setup_user, cleanup_user, session_cookies, run_cmd
from bhelpers import (
    _shell, _create_buddy_link, _get_pk,
    _create_personal_expense_with_buddy,
    _create_group, _add_group_member, _create_group_expense,
)


def _get_export(driver, date_from=None, date_to=None):
    cookies = session_cookies(driver)
    params = {}
    if date_from and date_to:
        params = {"date_from": date_from, "date_to": date_to}
    return requests.get(_url("/buddies/summary/export/"), cookies=cookies, params=params, timeout=30)


def _read_csv(zf, name):
    return zf.read(name).decode()


class TestBuddySummaryExport:

    def test_export_returns_zip_with_expected_csvs(self, driver, w):
        a = setup_user(driver, w, first_name="Exp", last_name="Orter")
        try:
            resp = _get_export(driver)
            assert resp.status_code == 200
            assert "application/zip" in resp.headers.get("Content-Type", "")
            assert resp.content[:2] == b"PK", "Response must be a valid ZIP file"

            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                names = zf.namelist()
            for expected in (
                "direct-buddies.csv",
                "direct-buddy-expenses.csv",
                "direct-buddy-expense-participation.csv",
            ):
                assert expected in names, f"{expected} missing from buddy summary export ZIP"
        finally:
            cleanup_user(a["email"])

    def test_direct_buddies_csv_combines_real_and_offline(self, driver, w):
        """direct-buddies.csv must list both a real-user buddy and a personal
        offline buddy in the same file, like members.csv does for projects."""
        a = setup_user(driver, w, first_name="Roster", last_name="Owner")
        b = setup_user(None, None, first_name="Roster", last_name="RealBuddy")
        _create_buddy_link(a["email"], b["email"])
        try:
            dummy_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import DummyUser; "
                f"owner = FeUser.objects.get(email='{a['email']}'); "
                f"d, _ = DummyUser.objects.get_or_create(owning_feuser=owner, display_name='RosterOfflineBuddy'); "
                f"print(d.pk)"
            ))
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                roster_csv = _read_csv(zf, "direct-buddies.csv")

            assert b["email"] in roster_csv, "Real-user buddy missing from direct-buddies.csv"
            assert "RosterOfflineBuddy" in roster_csv, "Offline buddy missing from direct-buddies.csv"
            assert "feuser" in roster_csv and "dummy" in roster_csv, (
                "Both buddy_type values must appear in the combined roster"
            )
        finally:
            _shell(f"from buddies.models import DummyUser; DummyUser.objects.filter(pk={dummy_pk}).delete()")
            cleanup_user(a["email"])
            cleanup_user(b["email"])

    def test_buddy_owned_expense_in_export(self, driver, w):
        a = setup_user(driver, w, first_name="Bud", last_name="OwnerTest")
        b = setup_user(None, None, first_name="Bud", last_name="Partner")
        _create_buddy_link(a["email"], b["email"])
        a_pk = int(_get_pk(a["email"]))
        b_pk = int(_get_pk(b["email"]))
        try:
            _create_personal_expense_with_buddy(
                owner_email=b["email"],
                participant_pk=a_pk,
                title="SummaryExportBuddyExpense",
                value="60.00",
                share="50.0",
                approved=True,
            )
            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                expenses_csv = _read_csv(zf, "direct-buddy-expenses.csv")
            assert "SummaryExportBuddyExpense" in expenses_csv, (
                "Buddy-owned expense title missing from direct-buddy-expenses.csv"
            )
            assert str(b_pk) in expenses_csv, "Buddy owner's owning_feuser_id missing from direct-buddy-expenses.csv"
        finally:
            cleanup_user(a["email"])
            cleanup_user(b["email"])

    def test_own_expense_shared_with_buddy_in_export(self, driver, w):
        """The feuser's OWN expense, shared with a real-user buddy who owes a
        share, must also appear (both directions of the relationship are
        covered, like the Buddy Expenses page itself)."""
        a = setup_user(driver, w, first_name="OwnShare", last_name="Owner")
        b = setup_user(None, None, first_name="OwnShare", last_name="Buddy")
        _create_buddy_link(a["email"], b["email"])
        a_pk = int(_get_pk(a["email"]))
        b_pk = int(_get_pk(b["email"]))
        expense_pk = None
        try:
            expense_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddySpending; "
                f"from budget.expense_factory import create_expense; "
                f"owner = FeUser.objects.get(email='{a['email']}'); "
                f"exp = create_expense(title='OwnShareExpense', type='expense', "
                f"  value='20.00', owning_feuser=owner, settled=True); "
                f"BuddySpending.objects.create(expense=exp, participant_feuser_id={b_pk}, share_percent='40.000'); "
                f"print(exp.pk)"
            ))
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                expenses_csv = _read_csv(zf, "direct-buddy-expenses.csv")
            assert "OwnShareExpense" in expenses_csv, "Own expense shared with a buddy missing from export"
            assert str(a_pk) in expenses_csv, "ctx user's own owning_feuser_id missing from direct-buddy-expenses.csv"
        finally:
            if expense_pk:
                _shell(f"from budget.models import Expense; Expense.objects.filter(pk={expense_pk}).delete()")
            cleanup_user(a["email"])
            cleanup_user(b["email"])

    def test_offline_buddy_paid_expense_in_export(self, driver, w):
        a = setup_user(driver, w, first_name="Off", last_name="BuddyOwner")
        try:
            dummy_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import DummyUser; "
                f"owner = FeUser.objects.get(email='{a['email']}'); "
                f"d, _ = DummyUser.objects.get_or_create(owning_feuser=owner, display_name='SummaryExportOfflinePayer'); "
                f"print(d.pk)"
            ))
            _shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import DummyUser; "
                f"from budget.expense_factory import create_expense; "
                f"owner = FeUser.objects.get(email='{a['email']}'); "
                f"dummy = DummyUser.objects.get(pk={dummy_pk}); "
                f"create_expense(title='SummaryExportOfflinePaidExpense', type='expense', "
                f"  value='25.00', owning_feuser=owner, settled=True, "
                f"  is_dummy=True, upfront_payee_dummy=dummy)"
            )
            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                expenses_csv = _read_csv(zf, "direct-buddy-expenses.csv")
                roster_csv = _read_csv(zf, "direct-buddies.csv")
            assert "SummaryExportOfflinePaidExpense" in expenses_csv
            assert str(dummy_pk) in expenses_csv, "Dummy's upfront_payee_dummy_id missing from direct-buddy-expenses.csv"
            assert "SummaryExportOfflinePayer" in roster_csv, (
                "Dummy display name must be looked up via direct-buddies.csv, not duplicated in the expense CSV"
            )
        finally:
            cleanup_user(a["email"])

    def test_participation_matrix_in_export(self, driver, w):
        """direct-buddy-expense-participation.csv must show the participant's
        recorded share and the payer's implicit remaining share. The
        exporting feuser (a, the participant here) shows up as "self"; the
        buddy who owns the expense (b, the payer) keeps their u-<pk> id."""
        a = setup_user(driver, w, first_name="Matrix", last_name="Owner")
        b = setup_user(None, None, first_name="Matrix", last_name="Buddy")
        _create_buddy_link(a["email"], b["email"])
        a_pk = int(_get_pk(a["email"]))
        b_pk = int(_get_pk(b["email"]))
        b_id = f"u-{b_pk}"
        expense_pk = None
        try:
            expense_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddySpending; "
                f"from budget.expense_factory import create_expense; "
                f"owner = FeUser.objects.get(email='{b['email']}'); "
                f"exp = create_expense(title='MatrixSummaryExpense', type='expense', "
                f"  value='50.00', owning_feuser=owner, settled=True); "
                f"BuddySpending.objects.create(expense=exp, participant_feuser_id={a_pk}, share_percent='20.000'); "
                f"print(exp.pk)"
            ))
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                matrix_csv = _read_csv(zf, "direct-buddy-expense-participation.csv")

            lines = matrix_csv.splitlines()
            header = lines[0]
            assert "self" in header, "Participant (exporting feuser) self id missing from matrix header"
            assert b_id in header, "Payer id missing from matrix header"

            data_row = next(l for l in lines[1:] if l.startswith(f"{expense_pk},"))
            cols = header.split(",")
            row = dict(zip(cols, data_row.split(",")))
            assert row["self"] == "20.000", "Participant share_percent missing/incorrect"
            assert row[b_id] == "80.000", "Payer's implicit share missing/incorrect"
        finally:
            if expense_pk:
                _shell(f"from budget.models import Expense; Expense.objects.filter(pk={expense_pk}).delete()")
            cleanup_user(a["email"])
            cleanup_user(b["email"])

    def test_project_expense_excluded_from_export(self, driver, w):
        a = setup_user(driver, w, first_name="Proj", last_name="ExclTest")
        admin_email = "summary_export_proj_admin@example.com"
        run_cmd("create_user", admin_email, "-p", "testpass123")
        proj_pk = None
        try:
            proj_pk = int(_create_group(admin_email, "SummaryExportExclProject"))
            _add_group_member(proj_pk, a["email"])
            _create_group_expense(
                admin_email, a["email"], proj_pk,
                title="SummaryExportProjectExpense", value="40.00", share="50.0",
            )
            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                expenses_csv = _read_csv(zf, "direct-buddy-expenses.csv")
            assert "SummaryExportProjectExpense" not in expenses_csv, \
                "Project expense must not appear in the buddy summary export"
        finally:
            if proj_pk:
                _shell(f"from buddies.models import Project; Project.objects.filter(pk={proj_pk}).delete()")
            cleanup_user(admin_email)
            cleanup_user(a["email"])

    def test_date_range_filters_buddy_expenses(self, driver, w):
        """An explicit date_from/date_to must exclude a buddy expense whose
        date_due falls outside the range, and include it again for a wide range.
        direct-buddies.csv must not be affected by date filtering."""
        a = setup_user(driver, w, first_name="Range", last_name="Tester")
        b = setup_user(None, None, first_name="Range", last_name="Buddy")
        _create_buddy_link(a["email"], b["email"])
        a_pk = int(_get_pk(a["email"]))
        old_exp_id = None
        try:
            old_exp_id = int(_shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddySpending; "
                f"from budget.expense_factory import create_expense; "
                f"owner = FeUser.objects.get(email='{b['email']}'); "
                f"exp = create_expense(title='OldRangeBuddyExpense', type='expense', "
                f"  value='10.00', owning_feuser=owner, settled=True, date_due='2000-01-01'); "
                f"BuddySpending.objects.create(expense=exp, participant_feuser_id={a_pk}, share_percent='50.000'); "
                f"print(exp.pk)"
            ))
            resp = _get_export(driver, date_from="2099-01-01", date_to="2099-12-31")
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                expenses_csv = _read_csv(zf, "direct-buddy-expenses.csv")
                roster_csv = _read_csv(zf, "direct-buddies.csv")
            assert "OldRangeBuddyExpense" not in expenses_csv, "Out-of-range buddy expense leaked into export"
            assert b["email"] in roster_csv, "direct-buddies.csv must not be affected by date filtering"

            wide_resp = _get_export(driver, date_from="1999-01-01", date_to="2099-12-31")
            with zipfile.ZipFile(io.BytesIO(wide_resp.content)) as zf:
                wide_expenses_csv = _read_csv(zf, "direct-buddy-expenses.csv")
            assert "OldRangeBuddyExpense" in wide_expenses_csv, "Wide range must include the old buddy expense"
        finally:
            if old_exp_id:
                _shell(f"from budget.models import Expense; Expense.objects.filter(pk={old_exp_id}).delete()")
            cleanup_user(a["email"])
            cleanup_user(b["email"])

    def test_no_date_params_defaults_to_current_month_not_all_time(self, driver, w):
        """Omitting date_from/date_to entirely must NOT silently export all-time
        data: it must fall back to the current financial month, exactly like the
        date-range nav's own default. An old expense must still be excluded."""
        a = setup_user(driver, w, first_name="Default", last_name="RangeUser")
        b = setup_user(None, None, first_name="Default", last_name="RangeBuddy")
        _create_buddy_link(a["email"], b["email"])
        a_pk = int(_get_pk(a["email"]))
        old_exp_id = None
        try:
            old_exp_id = int(_shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddySpending; "
                f"from budget.expense_factory import create_expense; "
                f"owner = FeUser.objects.get(email='{b['email']}'); "
                f"exp = create_expense(title='NoParamsOldBuddyExpense', type='expense', "
                f"  value='10.00', owning_feuser=owner, settled=True, date_due='2000-01-01'); "
                f"BuddySpending.objects.create(expense=exp, participant_feuser_id={a_pk}, share_percent='50.000'); "
                f"print(exp.pk)"
            ))
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                expenses_csv = _read_csv(zf, "direct-buddy-expenses.csv")
            assert "NoParamsOldBuddyExpense" not in expenses_csv, (
                "No date params must default to the current month, not all-time"
            )
        finally:
            if old_exp_id:
                _shell(f"from budget.models import Expense; Expense.objects.filter(pk={old_exp_id}).delete()")
            cleanup_user(a["email"])
            cleanup_user(b["email"])

    def test_export_requires_authentication(self, driver, w):
        resp = requests.get(_url("/buddies/summary/export/"), timeout=10, allow_redirects=False)
        assert resp.status_code in (302, 403), (
            f"Unauthenticated export must redirect or deny, got {resp.status_code}"
        )
