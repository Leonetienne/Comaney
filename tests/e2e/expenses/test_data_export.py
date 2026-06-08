"""
Account data export (ZIP):
- Returns application/zip
- Contains all expected CSV files
- Expense and category data appears in the correct CSV
- anthropic_api_key is masked (only last 4 chars visible)
- Unauthenticated request is redirected
- direct-buddies.csv / direct-buddy-expenses.csv /
  direct-buddy-expense-participation.csv: the combined real-user + offline
  buddy roster, all-time personal (non-project) expenses shared with a
  direct buddy in either direction, and the per-expense participation
  breakdown. Project-related participation is excluded (it is already
  covered by the nested projects/<uid>/ export). These three replace the
  old expense_participants.csv, real_user_buddies.csv, and
  offline_buddies.csv, which are no longer included (now redundant).
- direct-buddy-expense-approval-matrix.csv / direct-buddy-expense-approval-timestamps.csv:
  per-participant approval state (neutral/approved/rejected) and the
  timestamp it was last set, one row per non-settlement direct-buddy expense
- expense_overlays.csv: feuser's personal overlays on shared expenses
- projects/<uid>/...: full export nested for every project the feuser
  belongs to, including approval_matrix.csv / approval_matrix_timestamps.csv
  and pending_payer_confirmations.csv (see tests/e2e/projects/test_project_export.py)
- pending_project_invites.csv / pending_buddy_invites.csv /
  pending_partnership_invites.csv: unexpired invites sent by or addressed to
  the feuser, tagged with a sent/received direction
- pending_expense_approvals.csv: personal (non-project) expenses where
  someone else designated the feuser as the upfront payer and the feuser
  hasn't yet confirmed they actually paid ("Did you pay for this?"); excludes
  settlements and dummy-paid expenses (separate confirmation flows) and
  project expenses (covered by projects/<uid>/pending_payer_confirmations.csv
  instead, like direct-buddy-expenses.csv excludes project expenses)
"""
import io
import subprocess
import time
import zipfile

import pytest
import requests
from selenium.webdriver.common.by import By

from helpers import (
    _url, fill,
    api_post, api_patch, api_delete, server_today,
    session_cookies, setup_user, cleanup_user,
    run_cmd, ai_test_api_key_args,
)
from bhelpers import _get_pk, _create_group, _add_group_member, _create_group_expense

DOCKER_WEB = "comaney-web-1"


def _shell(code: str) -> str:
    r = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c", code],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _get_export(driver):
    """Download the export ZIP using the browser's session cookies."""
    cookies = session_cookies(driver)
    return requests.get(_url("/account/export/"), cookies=cookies, timeout=30)


def _read_csv(zf, name):
    return zf.read(name).decode()


def _submit_form(driver, action_value):
    driver.execute_script(
        f"document.querySelector(\"input[name='action'][value='{action_value}']\").closest('form').submit()"
    )


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestDataExport:

    def test_export_returns_zip(self, driver, w, ctx):
        resp = _get_export(driver)
        assert resp.status_code == 200
        assert "application/zip" in resp.headers.get("Content-Type", "")
        assert resp.content[:2] == b"PK", "Response must be a valid ZIP file"

    def test_export_contains_all_csvs(self, driver, w, ctx):
        resp = _get_export(driver)
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            names = zf.namelist()
        for expected in (
            "profile.csv",
            "categories.csv",
            "tags.csv",
            "expenses.csv",
            "scheduled_expenses.csv",
            "dashboard_cards.csv",
            "direct-buddies.csv",
            "direct-buddy-expenses.csv",
            "direct-buddy-expense-participation.csv",
            "direct-buddy-expense-approval-matrix.csv",
            "direct-buddy-expense-approval-timestamps.csv",
            "expense_overlays.csv",
            "pending_project_invites.csv",
            "pending_buddy_invites.csv",
            "pending_partnership_invites.csv",
            "pending_expense_approvals.csv",
        ):
            assert expected in names, f"{expected} missing from export ZIP"
        for removed in (
            "expense_participants.csv",
            "real_user_buddies.csv",
            "offline_buddies.csv",
        ):
            assert removed not in names, f"{removed} is redundant and must no longer be in the export ZIP"

    def test_expense_appears_in_export(self, driver, w, ctx):
        r = api_post("/api/v1/expenses/", ctx, json={
            "title": "ExportTestExpense",
            "type": "expense",
            "value": "99.99",
            "date_due": server_today(),
            "settled": True,
        })
        assert r.status_code == 201
        eid = r.json()["id"]

        resp = _get_export(driver)
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            expenses_csv = _read_csv(zf, "expenses.csv")
        assert "ExportTestExpense" in expenses_csv

        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_profile_email_in_export(self, driver, w, ctx):
        resp = _get_export(driver)
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            profile_csv = _read_csv(zf, "profile.csv")
        assert ctx["email"] in profile_csv

    def test_anthropic_key_masked_in_export(self, driver, w, ctx):
        fake_key = "sk-ant-api03-exporttest9999"
        driver.get(_url("/profile/"))
        time.sleep(1)
        fill(w, By.ID, "id_anthropic_api_key", fake_key)
        fill(w, By.ID, "id_ai_custom_instructions", "")
        _submit_form(driver, "ai")
        time.sleep(2)
        assert "Saved." in driver.page_source

        resp = _get_export(driver)
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            profile_csv = _read_csv(zf, "profile.csv")

        assert fake_key not in profile_csv, "Full API key must not appear in export"
        assert "9999" in profile_csv, "Last 4 chars of key must be visible in export"

        # Clear the key
        driver.get(_url("/profile/"))
        time.sleep(1)
        driver.find_element(By.ID, "id_anthropic_api_key").clear()
        fill(w, By.ID, "id_ai_custom_instructions", "")
        _submit_form(driver, "ai")
        time.sleep(2)

    def test_category_appears_in_export(self, driver, w, ctx):
        r = api_post("/api/v1/categories/", ctx, json={"title": "ExportCat"})
        assert r.status_code == 201
        cat_id = r.json()["id"]

        resp = _get_export(driver)
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            cats_csv = _read_csv(zf, "categories.csv")
        assert "ExportCat" in cats_csv

        api_delete(f"/api/v1/categories/{cat_id}/", ctx)

    def test_buddy_owned_expense_appears_in_export(self, driver, w, ctx):
        """Personal expense owned by a direct (BuddyLink-connected) buddy where ctx user
        is a participant must appear in direct-buddy-expenses.csv (with the
        owner's raw owning_feuser_id, same column scheme as expenses.csv), and
        must NOT appear in own expenses.csv."""
        owner_email = "export_owner_buddy@example.com"
        run_cmd("create_user", owner_email, "-p", "testpass123", *ai_test_api_key_args())
        owner_pk = int(_get_pk(owner_email))
        try:
            participant_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"print(FeUser.objects.get(email='{ctx['email']}').pk)"
            ))
            _shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddyLink; "
                f"a = FeUser.objects.get(email='{owner_email}'); "
                f"b = FeUser.objects.get(pk={participant_pk}); "
                f"lo, hi = sorted([a, b], key=lambda u: u.pk); "
                f"BuddyLink.objects.get_or_create(user_a=lo, user_b=hi)"
            )
            expense_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from budget.expense_factory import create_expense; "
                f"owner = FeUser.objects.get(email='{owner_email}'); "
                f"exp = create_expense(title='BuddyExportExpense', type='expense', "
                f"  value='55.00', owning_feuser=owner, settled=True); "
                f"print(exp.pk)"
            ))
            _shell(
                f"from buddies.models import BuddySpending; "
                f"from budget.models import Expense; "
                f"from feusers.models import FeUser; "
                f"exp = Expense.objects.get(pk={expense_pk}); "
                f"part = FeUser.objects.get(pk={participant_pk}); "
                f"BuddySpending.objects.create(expense=exp, participant_feuser=part, share_percent='50.000')"
            )

            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                buddies_csv = _read_csv(zf, "direct-buddy-expenses.csv")
                own_csv     = _read_csv(zf, "expenses.csv")

            assert "BuddyExportExpense" in buddies_csv, "Buddy expense title missing from direct-buddy-expenses.csv"
            assert str(owner_pk) in buddies_csv, "Buddy owner's owning_feuser_id missing from direct-buddy-expenses.csv"
            assert "BuddyExportExpense" not in own_csv, "Buddy expense must not appear in expenses.csv"
        finally:
            cleanup_user(owner_email)

    def test_own_expense_shared_with_buddy_appears_in_export(self, driver, w, ctx):
        """ctx user's OWN expense, shared with a direct real-user buddy who owes
        a share, must appear in direct-buddy-expenses.csv too (the export covers
        both directions of a direct-buddy relationship, like the Buddy Expenses
        page does), with ctx user's own raw owning_feuser_id."""
        buddy_email = "export_buddy_of_owner@example.com"
        run_cmd("create_user", buddy_email, "-p", "testpass123", *ai_test_api_key_args())
        ctx_pk = int(_get_pk(ctx["email"]))
        try:
            buddy_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"print(FeUser.objects.get(email='{buddy_email}').pk)"
            ))
            _shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddyLink; "
                f"a = FeUser.objects.get(email='{ctx['email']}'); "
                f"b = FeUser.objects.get(pk={buddy_pk}); "
                f"lo, hi = sorted([a, b], key=lambda u: u.pk); "
                f"BuddyLink.objects.get_or_create(user_a=lo, user_b=hi)"
            )
            expense_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddySpending; "
                f"from budget.expense_factory import create_expense; "
                f"owner = FeUser.objects.get(email='{ctx['email']}'); "
                f"exp = create_expense(title='OwnExpenseSharedWithBuddy', type='expense', "
                f"  value='30.00', owning_feuser=owner, settled=True); "
                f"BuddySpending.objects.create(expense=exp, participant_feuser_id={buddy_pk}, share_percent='40.000'); "
                f"print(exp.pk)"
            ))
            try:
                time.sleep(1)
                resp = _get_export(driver)
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    buddies_csv = _read_csv(zf, "direct-buddy-expenses.csv")

                assert "OwnExpenseSharedWithBuddy" in buddies_csv, (
                    "Own expense shared with a buddy missing from direct-buddy-expenses.csv"
                )
                assert str(ctx_pk) in buddies_csv, "ctx user's own owning_feuser_id missing from direct-buddy-expenses.csv"
            finally:
                _shell(f"from budget.models import Expense; Expense.objects.filter(pk={expense_pk}).delete()")
        finally:
            cleanup_user(buddy_email)

    def test_offline_buddy_paid_expense_in_buddies_export(self, driver, w, ctx):
        """An expense the feuser owns but recorded as paid upfront by their own
        (personal, non-project) offline buddy must appear in
        direct-buddy-expenses.csv with the raw upfront_payee_dummy_id; the
        dummy's display name is looked up via direct-buddies.csv, not
        duplicated here."""
        dummy_pk = int(_shell(
            f"from feusers.models import FeUser; "
            f"from buddies.models import DummyUser; "
            f"owner = FeUser.objects.get(email='{ctx['email']}'); "
            f"d, _ = DummyUser.objects.get_or_create(owning_feuser=owner, display_name='OfflineBuddyExportPayer'); "
            f"print(d.pk)"
        ))
        expense_pk = int(_shell(
            f"from feusers.models import FeUser; "
            f"from buddies.models import DummyUser; "
            f"from budget.expense_factory import create_expense; "
            f"owner = FeUser.objects.get(email='{ctx['email']}'); "
            f"dummy = DummyUser.objects.get(pk={dummy_pk}); "
            f"exp = create_expense(title='OfflineBuddyPaidExpense', type='expense', "
            f"  value='40.00', owning_feuser=owner, settled=True, "
            f"  is_dummy=True, upfront_payee_dummy=dummy); "
            f"print(exp.pk)"
        ))
        try:
            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                buddies_csv = _read_csv(zf, "direct-buddy-expenses.csv")
                roster_csv = _read_csv(zf, "direct-buddies.csv")

            assert "OfflineBuddyPaidExpense" in buddies_csv, "Title missing from direct-buddy-expenses.csv"
            assert str(dummy_pk) in buddies_csv, "Dummy's upfront_payee_dummy_id missing from direct-buddy-expenses.csv"
            assert "OfflineBuddyExportPayer" in roster_csv, "Offline buddy missing from direct-buddies.csv"
        finally:
            _shell(f"from budget.models import Expense; Expense.objects.filter(pk={expense_pk}).delete()")
            _shell(f"from buddies.models import DummyUser; DummyUser.objects.filter(pk={dummy_pk}).delete()")

    def test_participation_matrix_in_buddies_export(self, driver, w, ctx):
        """direct-buddy-expense-participation.csv must have one row per
        direct-buddy expense, with the participant's recorded share and the
        payer's implicit remaining share. ctx is the exporting feuser and the
        participant here, so it shows up as "self"; the buddy who owns the
        expense keeps their u-<pk> id."""
        owner_email = "export_owner_matrix@example.com"
        run_cmd("create_user", owner_email, "-p", "testpass123", *ai_test_api_key_args())
        owner_pk = int(_get_pk(owner_email))
        try:
            participant_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"print(FeUser.objects.get(email='{ctx['email']}').pk)"
            ))
            owner_id = f"u-{owner_pk}"
            _shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddyLink; "
                f"a = FeUser.objects.get(email='{owner_email}'); "
                f"b = FeUser.objects.get(pk={participant_pk}); "
                f"lo, hi = sorted([a, b], key=lambda u: u.pk); "
                f"BuddyLink.objects.get_or_create(user_a=lo, user_b=hi)"
            )
            expense_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddySpending; "
                f"from budget.expense_factory import create_expense; "
                f"owner = FeUser.objects.get(email='{owner_email}'); "
                f"exp = create_expense(title='MatrixBuddyExpense', type='expense', "
                f"  value='90.00', owning_feuser=owner, settled=True); "
                f"BuddySpending.objects.create(expense=exp, participant_feuser_id={participant_pk}, share_percent='30.000'); "
                f"print(exp.pk)"
            ))
            try:
                time.sleep(1)
                resp = _get_export(driver)
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    matrix_csv = _read_csv(zf, "direct-buddy-expense-participation.csv")

                lines = matrix_csv.splitlines()
                header = lines[0]
                assert owner_id in header, "Payer id missing from matrix header"
                assert "self" in header, "Participant (ctx, exporting feuser) self id missing from matrix header"

                data_row = next(l for l in lines[1:] if l.startswith(f"{expense_pk},"))
                cols = header.split(",")
                row = dict(zip(cols, data_row.split(",")))
                assert row["self"] == "30.000", "Participant share_percent missing/incorrect"
                assert row[owner_id] == "70.000", "Payer's implicit share missing/incorrect"
            finally:
                _shell(f"from budget.models import Expense; Expense.objects.filter(pk={expense_pk}).delete()")
        finally:
            cleanup_user(owner_email)

    def test_approval_matrix_in_buddies_export(self, driver, w, ctx):
        """direct-buddy-expense-approval-matrix.csv must show ctx user's
        (self) approval_state label for a non-settlement direct-buddy
        expense they participate in; direct-buddy-expense-approval-timestamps.csv
        must carry the matching consent_set_at."""
        owner_email = "export_owner_approval_matrix@example.com"
        run_cmd("create_user", owner_email, "-p", "testpass123", *ai_test_api_key_args())
        try:
            participant_pk = int(_get_pk(ctx["email"]))
            _shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddyLink; "
                f"a = FeUser.objects.get(email='{owner_email}'); "
                f"b = FeUser.objects.get(pk={participant_pk}); "
                f"lo, hi = sorted([a, b], key=lambda u: u.pk); "
                f"BuddyLink.objects.get_or_create(user_a=lo, user_b=hi)"
            )
            expense_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddySpending; "
                f"from budget.expense_factory import create_expense; "
                f"from django.utils import timezone; "
                f"owner = FeUser.objects.get(email='{owner_email}'); "
                f"exp = create_expense(title='ApprovalMatrixBuddyExpense', type='expense', "
                f"  value='40.00', owning_feuser=owner, settled=True); "
                f"BuddySpending.objects.create(expense=exp, participant_feuser_id={participant_pk}, "
                f"  share_percent='50.000', approval_state=BuddySpending.APPROVAL_APPROVED, consent_set_at=timezone.now()); "
                f"print(exp.pk)"
            ))
            try:
                time.sleep(1)
                resp = _get_export(driver)
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    state_csv = _read_csv(zf, "direct-buddy-expense-approval-matrix.csv")
                    ts_csv = _read_csv(zf, "direct-buddy-expense-approval-timestamps.csv")

                state_lines = state_csv.splitlines()
                state_header = state_lines[0]
                assert "self" in state_header, "Participant (ctx) self id missing from approval matrix header"
                state_row = next(l for l in state_lines[1:] if l.startswith(f"{expense_pk},"))
                state_cols = state_header.split(",")
                assert dict(zip(state_cols, state_row.split(",")))["self"] == "approved", (
                    "Participant's approval_state label missing/incorrect"
                )

                ts_lines = ts_csv.splitlines()
                ts_row = next(l for l in ts_lines[1:] if l.startswith(f"{expense_pk},"))
                ts_value = dict(zip(ts_lines[0].split(","), ts_row.split(",")))["self"]
                assert ts_value, "consent_set_at timestamp missing for an approved participant"
            finally:
                _shell(f"from budget.models import Expense; Expense.objects.filter(pk={expense_pk}).delete()")
        finally:
            cleanup_user(owner_email)

    def test_project_participation_excluded_from_buddies_export(self, driver, w, ctx):
        """A project expense where ctx user is a participant (paid by someone else)
        must NOT appear in direct-buddy-expenses.csv: it is already covered by the
        nested projects/<uid>/ export."""
        admin_email = "export_project_admin_excl@example.com"
        run_cmd("create_user", admin_email, "-p", "testpass123", *ai_test_api_key_args())
        proj_pk = None
        try:
            proj_pk = int(_create_group(admin_email, "BuddyExclusionProject"))
            _add_group_member(proj_pk, ctx["email"])
            _create_group_expense(
                admin_email, ctx["email"], proj_pk,
                title="ProjectComboExpense", value="40.00", share="50.0",
            )

            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                buddies_csv = _read_csv(zf, "direct-buddy-expenses.csv")

            assert "ProjectComboExpense" not in buddies_csv, (
                "Project expense must not appear in direct-buddy-expenses.csv"
            )
        finally:
            if proj_pk:
                _shell(f"from buddies.models import Project; Project.objects.filter(pk={proj_pk}).delete()")
            cleanup_user(admin_email)

    def test_dummy_participant_in_own_expense_appears_in_export(self, driver, w, ctx):
        """A personal offline buddy participating (not paying) in ctx user's
        own expense must appear in direct-buddy-expenses.csv, with the correct
        share split in direct-buddy-expense-participation.csv (dummy's
        recorded share, ctx user's implicit remaining share as "self")."""
        dummy_pk = int(_shell(
            f"from feusers.models import FeUser; "
            f"from buddies.models import DummyUser; "
            f"owner = FeUser.objects.get(email='{ctx['email']}'); "
            f"d, _ = DummyUser.objects.get_or_create(owning_feuser=owner, display_name='ExportParticipant'); "
            f"print(d.pk)"
        ))
        expense_pk = int(_shell(
            f"from feusers.models import FeUser; "
            f"from budget.expense_factory import create_expense; "
            f"from buddies.models import BuddySpending; "
            f"owner = FeUser.objects.get(email='{ctx['email']}'); "
            f"exp = create_expense(title='ParticipantTestExpense', type='expense', "
            f"  value='30.00', owning_feuser=owner, settled=True); "
            f"BuddySpending.objects.create(expense=exp, participant_dummy_id={dummy_pk}, share_percent='33.000'); "
            f"print(exp.pk)"
        ))
        try:
            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                expenses_csv = _read_csv(zf, "direct-buddy-expenses.csv")
                matrix_csv = _read_csv(zf, "direct-buddy-expense-participation.csv")

            assert "ParticipantTestExpense" in expenses_csv, "Expense title missing from direct-buddy-expenses.csv"

            lines = matrix_csv.splitlines()
            header = lines[0]
            dummy_id = f"d-{dummy_pk}"
            assert dummy_id in header, "Dummy participant id missing from matrix header"

            data_row = next(l for l in lines[1:] if l.startswith(f"{expense_pk},"))
            row = dict(zip(header.split(","), data_row.split(",")))
            assert row[dummy_id] == "33.000", "Dummy share_percent missing/incorrect"
            assert row["self"] == "67.000", "ctx user's implicit share missing/incorrect"
        finally:
            _shell(f"from budget.models import Expense; Expense.objects.filter(pk={expense_pk}).delete()")
            _shell(f"from buddies.models import DummyUser; DummyUser.objects.filter(pk={dummy_pk}).delete()")

    def test_expense_tag_ids_in_export(self, driver, w, ctx):
        """expenses.csv must contain tag UIDs, not tag titles."""
        r = api_post("/api/v1/tags/", ctx, json={"title": "ExportTagTitle"})
        assert r.status_code == 201
        tag_id = str(r.json()["id"])

        r = api_post("/api/v1/expenses/", ctx, json={
            "title": "TagIdFormatExpense", "type": "expense",
            "value": "1.00", "date_due": server_today(), "settled": True,
        })
        assert r.status_code == 201
        eid = r.json()["id"]
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"tag_ids": [int(tag_id)]})

        try:
            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                expenses_csv = _read_csv(zf, "expenses.csv")

            assert tag_id in expenses_csv, "Tag UID must appear in expenses.csv"
            assert "ExportTagTitle" not in expenses_csv, "Tag title must NOT appear in expenses.csv"
        finally:
            api_delete(f"/api/v1/expenses/{eid}/", ctx)
            api_delete(f"/api/v1/tags/{tag_id}/", ctx)

    def test_expense_category_id_in_export(self, driver, w, ctx):
        """expenses.csv must contain category_id as a raw numeric FK, not the category title."""
        r = api_post("/api/v1/categories/", ctx, json={"title": "ExportCatTitle"})
        assert r.status_code == 201
        cat_id = str(r.json()["id"])

        r = api_post("/api/v1/expenses/", ctx, json={
            "title": "CatIdFormatExpense", "type": "expense",
            "value": "1.00", "date_due": server_today(), "settled": True,
            "category_id": int(cat_id),
        })
        assert r.status_code == 201
        eid = r.json()["id"]

        try:
            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                expenses_csv = _read_csv(zf, "expenses.csv")

            assert cat_id in expenses_csv, "Category UID must appear in expenses.csv"
            assert "ExportCatTitle" not in expenses_csv, "Category title must NOT appear in expenses.csv"
        finally:
            api_delete(f"/api/v1/expenses/{eid}/", ctx)
            api_delete(f"/api/v1/categories/{cat_id}/", ctx)

    def test_buddies_expenses_no_category_tag_columns(self, driver, w, ctx):
        """direct-buddy-expenses.csv must not expose the expense owner's category_id or tag_ids."""
        owner_email = "export_owner_bcat@example.com"
        run_cmd("create_user", owner_email, "-p", "testpass123", *ai_test_api_key_args())
        try:
            participant_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"print(FeUser.objects.get(email='{ctx['email']}').pk)"
            ))
            _shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddyLink; "
                f"a = FeUser.objects.get(email='{owner_email}'); "
                f"b = FeUser.objects.get(pk={participant_pk}); "
                f"lo, hi = sorted([a, b], key=lambda u: u.pk); "
                f"BuddyLink.objects.get_or_create(user_a=lo, user_b=hi)"
            )
            expense_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from budget.expense_factory import create_expense; "
                f"owner = FeUser.objects.get(email='{owner_email}'); "
                f"exp = create_expense(title='BuddyCatTagExpense', type='expense', "
                f"  value='10.00', owning_feuser=owner, settled=True); "
                f"print(exp.pk)"
            ))
            _shell(
                f"from buddies.models import BuddySpending; "
                f"from budget.models import Expense; "
                f"from feusers.models import FeUser; "
                f"BuddySpending.objects.create("
                f"  expense=Expense.objects.get(pk={expense_pk}), "
                f"  participant_feuser=FeUser.objects.get(pk={participant_pk}), "
                f"  share_percent='50.000')"
            )

            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                buddies_csv = _read_csv(zf, "direct-buddy-expenses.csv")

            header = buddies_csv.splitlines()[0]
            assert "category_id" not in header, "category_id must not appear in direct-buddy-expenses.csv headers"
            assert "tag_ids" not in header, "tag_ids must not appear in direct-buddy-expenses.csv headers"
        finally:
            cleanup_user(owner_email)

    def test_expense_overlays_in_export(self, driver, w, ctx):
        """expense_overlays.csv must list category_id and tag_ids as raw IDs, not titles."""
        r = api_post("/api/v1/categories/", ctx, json={"title": "OverlayCat"})
        assert r.status_code == 201
        cat_id = r.json()["id"]

        r = api_post("/api/v1/tags/", ctx, json={"title": "OverlayTag"})
        assert r.status_code == 201
        tag_id = r.json()["id"]

        owner_email = "export_owner_overlay@example.com"
        run_cmd("create_user", owner_email, "-p", "testpass123", *ai_test_api_key_args())
        try:
            participant_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"print(FeUser.objects.get(email='{ctx['email']}').pk)"
            ))
            expense_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from budget.expense_factory import create_expense; "
                f"owner = FeUser.objects.get(email='{owner_email}'); "
                f"exp = create_expense(title='OverlayTestExpense', type='expense', "
                f"  value='20.00', owning_feuser=owner, settled=True); "
                f"print(exp.pk)"
            ))
            _shell(
                f"from buddies.models import BuddySpending; "
                f"from budget.models import Expense, ExpenseDataOverlay, Category, Tag; "
                f"from feusers.models import FeUser; "
                f"part = FeUser.objects.get(pk={participant_pk}); "
                f"exp = Expense.objects.get(pk={expense_pk}); "
                f"BuddySpending.objects.create(expense=exp, participant_feuser=part, share_percent='50.000'); "
                f"ov = ExpenseDataOverlay.objects.create(expense=exp, feuser=part, "
                f"  category=Category.objects.get(pk={cat_id})); "
                f"ov.tags.set([Tag.objects.get(pk={tag_id})])"
            )

            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                overlays_csv = _read_csv(zf, "expense_overlays.csv")

            assert "OverlayTestExpense" in overlays_csv, "Expense title missing from expense_overlays.csv"
            assert str(cat_id) in overlays_csv, "Category UID missing from expense_overlays.csv"
            assert str(tag_id) in overlays_csv, "Tag UID missing from expense_overlays.csv"
            assert "OverlayCat" not in overlays_csv, "Category title must not appear in expense_overlays.csv"
            assert "OverlayTag" not in overlays_csv, "Tag title must not appear in expense_overlays.csv"
        finally:
            cleanup_user(owner_email)
            api_delete(f"/api/v1/categories/{cat_id}/", ctx)
            api_delete(f"/api/v1/tags/{tag_id}/", ctx)

    def test_real_user_buddy_in_direct_buddies_csv(self, driver, w, ctx):
        """direct-buddies.csv must contain entries for confirmed buddy
        connections, even without any shared expense."""
        buddy_email = "export_buddy_real@example.com"
        run_cmd("create_user", buddy_email, "-p", "testpass123", *ai_test_api_key_args())
        try:
            link_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddyLink; "
                f"u1 = FeUser.objects.get(email='{ctx['email']}'); "
                f"u2 = FeUser.objects.get(email='{buddy_email}'); "
                f"lo, hi = sorted([u1, u2], key=lambda u: u.pk); "
                f"bl = BuddyLink.objects.create(user_a=lo, user_b=hi); "
                f"print(bl.pk)"
            ))

            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                csv_text = _read_csv(zf, "direct-buddies.csv")

            assert buddy_email in csv_text, "Buddy email missing from direct-buddies.csv"
        finally:
            _shell(f"from buddies.models import BuddyLink; BuddyLink.objects.filter(pk={link_pk}).delete()")
            cleanup_user(buddy_email)

    def test_member_project_appears_nested_in_export(self, driver, w, ctx):
        """Every project the feuser belongs to (admin or not) must get its own
        full export nested under projects/<uid>/: meta.csv, members.csv,
        expenses.csv, participation_matrix.csv, approval_matrix.csv,
        approval_matrix_timestamps.csv, pending_payer_confirmations.csv."""
        admin_email = "export_project_admin@example.com"
        run_cmd("create_user", admin_email, "-p", "testpass123", *ai_test_api_key_args())
        proj_pk = None
        try:
            proj_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import Project, ProjectMember; "
                f"admin = FeUser.objects.get(email='{admin_email}'); "
                f"member = FeUser.objects.get(email='{ctx['email']}'); "
                f"p = Project.objects.create(name='NestedExportProject', description='nested desc', admin_feuser=admin); "
                f"ProjectMember.objects.create(group=p, feuser=admin); "
                f"ProjectMember.objects.create(group=p, feuser=member); "
                f"print(p.pk)"
            ))

            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                names = zf.namelist()
                for expected in (
                    f"projects/{proj_pk}/meta.csv",
                    f"projects/{proj_pk}/members.csv",
                    f"projects/{proj_pk}/expenses.csv",
                    f"projects/{proj_pk}/participation_matrix.csv",
                    f"projects/{proj_pk}/approval_matrix.csv",
                    f"projects/{proj_pk}/approval_matrix_timestamps.csv",
                    f"projects/{proj_pk}/pending_payer_confirmations.csv",
                ):
                    assert expected in names, f"{expected} missing from nested project export"

                meta_csv = _read_csv(zf, f"projects/{proj_pk}/meta.csv")
                members_csv = _read_csv(zf, f"projects/{proj_pk}/members.csv")

            assert "NestedExportProject" in meta_csv, "Project name missing from nested meta.csv"
            assert admin_email in members_csv, "Admin email missing from nested members.csv"
            assert ctx["email"] in members_csv, "Member's own email missing from nested members.csv (not admin-only)"
        finally:
            if proj_pk:
                _shell(f"from buddies.models import Project; Project.objects.filter(pk={proj_pk}).delete()")
            cleanup_user(admin_email)

    def test_full_export_is_comprehensive_regardless_of_date(self, driver, w, ctx):
        """The full account export must remain all-encompassing: an old-dated
        project expense and an old-dated buddy expense must both appear, unlike
        the page-level project/buddy-summary exports which respect a selected
        date range."""
        admin_email = "export_old_data_admin@example.com"
        run_cmd("create_user", admin_email, "-p", "testpass123", *ai_test_api_key_args())
        proj_pk = None
        old_buddy_exp_id = None
        try:
            proj_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import Project, ProjectMember; "
                f"admin = FeUser.objects.get(email='{admin_email}'); "
                f"member = FeUser.objects.get(email='{ctx['email']}'); "
                f"p = Project.objects.create(name='OldDataProject', admin_feuser=admin); "
                f"ProjectMember.objects.create(group=p, feuser=admin); "
                f"ProjectMember.objects.create(group=p, feuser=member); "
                f"print(p.pk)"
            ))
            _shell(
                f"from budget.models import Expense; "
                f"from feusers.models import FeUser; "
                f"admin = FeUser.objects.get(email='{admin_email}'); "
                f"Expense.objects.create(owning_feuser=admin, title='OldProjectExpense', "
                f"  type='expense', value='15.00', date_due='2000-01-01', "
                f"  settled=True, buddy_approved=True, project_id={proj_pk})"
            )
            old_buddy_exp_id = int(_shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddyLink, BuddySpending; "
                f"from budget.expense_factory import create_expense; "
                f"admin = FeUser.objects.get(email='{admin_email}'); "
                f"member = FeUser.objects.get(email='{ctx['email']}'); "
                f"lo, hi = sorted([admin, member], key=lambda u: u.pk); "
                f"BuddyLink.objects.get_or_create(user_a=lo, user_b=hi); "
                f"exp = create_expense(title='OldBuddyExpense', type='expense', "
                f"  value='12.00', owning_feuser=admin, settled=True, date_due='2000-01-01'); "
                f"BuddySpending.objects.create(expense=exp, participant_feuser=member, share_percent='50.000'); "
                f"print(exp.pk)"
            ))

            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                nested_expenses_csv = _read_csv(zf, f"projects/{proj_pk}/expenses.csv")
                buddies_csv = _read_csv(zf, "direct-buddy-expenses.csv")

            assert "OldProjectExpense" in nested_expenses_csv, (
                "Old-dated project expense must still appear in the comprehensive account export"
            )
            assert "OldBuddyExpense" in buddies_csv, (
                "Old-dated buddy expense must still appear in the comprehensive account export"
            )
        finally:
            if old_buddy_exp_id:
                _shell(f"from budget.models import Expense; Expense.objects.filter(pk={old_buddy_exp_id}).delete()")
            if proj_pk:
                _shell(f"from buddies.models import Project; Project.objects.filter(pk={proj_pk}).delete()")
            cleanup_user(admin_email)

    def test_project_offline_member_in_nested_export(self, driver, w, ctx):
        """Offline (dummy) project members must appear in the nested members.csv."""
        ids = _shell(
            f"from feusers.models import FeUser; "
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"u = FeUser.objects.get(email='{ctx['email']}'); "
            f"p = Project.objects.create(name='ExportOfflineProject', admin_feuser=u); "
            f"ProjectMember.objects.create(group=p, feuser=u); "
            f"d = DummyUser.objects.create(owning_group=p, display_name='ExportOfflineMember'); "
            f"ProjectMember.objects.create(group=p, dummy=d); "
            f"print(p.pk, d.pk)"
        ).split()
        proj_pk, dummy_pk = int(ids[0]), int(ids[1])
        try:
            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                members_csv = _read_csv(zf, f"projects/{proj_pk}/members.csv")

            assert "ExportOfflineMember" in members_csv, "Offline member name missing from nested members.csv"
        finally:
            _shell(f"from buddies.models import Project; Project.objects.filter(pk={proj_pk}).delete()")

    def test_offline_buddy_in_direct_buddies_csv(self, driver, w, ctx):
        """direct-buddies.csv must list personally-owned offline buddies,
        even without any shared expense."""
        dummy_pk = int(_shell(
            f"from feusers.models import FeUser; "
            f"from buddies.models import DummyUser; "
            f"u = FeUser.objects.get(email='{ctx['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='ExportPersonalDummy'); "
            f"print(d.pk)"
        ))
        try:
            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                csv_text = _read_csv(zf, "direct-buddies.csv")

            assert "ExportPersonalDummy" in csv_text, "Offline buddy name missing from direct-buddies.csv"
        finally:
            _shell(f"from buddies.models import DummyUser; DummyUser.objects.filter(pk={dummy_pk}).delete()")

    def test_pending_project_invites_in_export(self, driver, w, ctx):
        """pending_project_invites.csv must list invites the user sent to join
        their own project, and invites addressed to them for someone else's
        project, each tagged with the right direction."""
        other_email = "export_project_invite_other@example.com"
        run_cmd("create_user", other_email, "-p", "testpass123", *ai_test_api_key_args())
        own_proj_pk = None
        other_proj_pk = None
        try:
            own_proj_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import Project, ProjectMember, ProjectInvite; "
                f"u = FeUser.objects.get(email='{ctx['email']}'); "
                f"p = Project.objects.create(name='InviteSenderProject', admin_feuser=u); "
                f"ProjectMember.objects.create(group=p, feuser=u); "
                f"ProjectInvite.objects.create(group=p, inviting_feuser=u, invitee_email='invitee_target@example.com'); "
                f"print(p.pk)"
            ))
            other_proj_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import Project, ProjectMember, ProjectInvite; "
                f"admin = FeUser.objects.get(email='{other_email}'); "
                f"p = Project.objects.create(name='InviteReceiverProject', admin_feuser=admin); "
                f"ProjectMember.objects.create(group=p, feuser=admin); "
                f"ProjectInvite.objects.create(group=p, inviting_feuser=admin, invitee_email='{ctx['email']}'); "
                f"print(p.pk)"
            ))

            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                csv_text = _read_csv(zf, "pending_project_invites.csv")

            lines = csv_text.splitlines()
            sent_row = next(l for l in lines if "invitee_target@example.com" in l)
            assert sent_row.startswith("sent,"), "Sent project invite must be tagged direction=sent"
            assert str(own_proj_pk) in sent_row, "Sent invite's project_id missing"

            received_row = next(l for l in lines if l.startswith("received,") and other_email in l)
            assert str(other_proj_pk) in received_row, "Received invite's project_id missing"
        finally:
            if own_proj_pk:
                _shell(f"from buddies.models import Project; Project.objects.filter(pk={own_proj_pk}).delete()")
            if other_proj_pk:
                _shell(f"from buddies.models import Project; Project.objects.filter(pk={other_proj_pk}).delete()")
            cleanup_user(other_email)

    def test_pending_buddy_invites_in_export(self, driver, w, ctx):
        """pending_buddy_invites.csv must list direct-buddy invites sent by
        and addressed to the user, each tagged with the right direction."""
        other_email = "export_buddy_invite_other@example.com"
        run_cmd("create_user", other_email, "-p", "testpass123", *ai_test_api_key_args())
        try:
            _shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddyInvite; "
                f"u = FeUser.objects.get(email='{ctx['email']}'); "
                f"BuddyInvite.objects.create(inviter=u, invitee_email='buddy_invitee_target@example.com')"
            )
            _shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddyInvite; "
                f"other = FeUser.objects.get(email='{other_email}'); "
                f"BuddyInvite.objects.create(inviter=other, invitee_email='{ctx['email']}')"
            )

            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                csv_text = _read_csv(zf, "pending_buddy_invites.csv")

            lines = csv_text.splitlines()
            sent_row = next(l for l in lines if "buddy_invitee_target@example.com" in l)
            assert sent_row.startswith("sent,"), "Sent buddy invite must be tagged direction=sent"

            assert any(l.startswith("received,") and other_email in l for l in lines), (
                "Received buddy invite missing from export"
            )
        finally:
            _shell(f"from buddies.models import BuddyInvite; BuddyInvite.objects.filter(invitee_email__in=['buddy_invitee_target@example.com', '{ctx['email']}']).delete()")
            cleanup_user(other_email)

    def test_pending_partnership_invites_in_export(self, driver, w, ctx):
        """pending_partnership_invites.csv must list catalog partnership
        invites sent by and addressed to the user, each tagged with the
        right direction."""
        other_email = "export_partnership_invite_other@example.com"
        run_cmd("create_user", other_email, "-p", "testpass123", *ai_test_api_key_args())
        try:
            _shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import CatalogPartnership, CatalogPartnershipMembership, CatalogPartnershipInvite; "
                f"u = FeUser.objects.get(email='{ctx['email']}'); "
                f"partnership = CatalogPartnership.objects.create(); "
                f"CatalogPartnershipMembership.objects.create(partnership=partnership, feuser=u, onboarding_complete=True); "
                f"CatalogPartnershipInvite.objects.create(partnership=partnership, inviter=u, invitee_email='partner_invitee_target@example.com')"
            )
            _shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import CatalogPartnership, CatalogPartnershipMembership, CatalogPartnershipInvite; "
                f"other = FeUser.objects.get(email='{other_email}'); "
                f"partnership = CatalogPartnership.objects.create(); "
                f"CatalogPartnershipMembership.objects.create(partnership=partnership, feuser=other, onboarding_complete=True); "
                f"CatalogPartnershipInvite.objects.create(partnership=partnership, inviter=other, invitee_email='{ctx['email']}')"
            )

            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                csv_text = _read_csv(zf, "pending_partnership_invites.csv")

            lines = csv_text.splitlines()
            sent_row = next(l for l in lines if "partner_invitee_target@example.com" in l)
            assert sent_row.startswith("sent,"), "Sent partnership invite must be tagged direction=sent"

            assert any(l.startswith("received,") and other_email in l for l in lines), (
                "Received partnership invite missing from export"
            )
        finally:
            _shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import CatalogPartnershipMembership; "
                f"CatalogPartnershipMembership.objects.filter(feuser__email__in=['{ctx['email']}', '{other_email}']).delete()"
            )
            cleanup_user(other_email)

    def test_pending_expense_approvals_in_export(self, driver, w, ctx):
        """pending_expense_approvals.csv must list an expense where ctx user
        was designated as the upfront payer by someone else and hasn't yet
        confirmed ("Did you pay for this?"), and must exclude an
        already-confirmed one."""
        other_email = "export_pending_confirm_other@example.com"
        run_cmd("create_user", other_email, "-p", "testpass123", *ai_test_api_key_args())
        pending_expense_pk = None
        confirmed_expense_pk = None
        try:
            ctx_pk = int(_get_pk(ctx["email"]))
            other_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"print(FeUser.objects.get(email='{other_email}').pk)"
            ))
            _shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddyLink; "
                f"a = FeUser.objects.get(pk={ctx_pk}); "
                f"b = FeUser.objects.get(pk={other_pk}); "
                f"lo, hi = sorted([a, b], key=lambda u: u.pk); "
                f"BuddyLink.objects.get_or_create(user_a=lo, user_b=hi)"
            )
            pending_expense_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddySpending; "
                f"from budget.expense_factory import create_expense; "
                f"payer = FeUser.objects.get(pk={ctx_pk}); "
                f"exp = create_expense(title='PendingPayerConfirmExpense', type='expense', "
                f"  value='20.00', owning_feuser=payer, settled=True, buddy_approved=False); "
                f"BuddySpending.objects.create(expense=exp, participant_feuser_id={other_pk}, share_percent='50.000'); "
                f"print(exp.pk)"
            ))
            confirmed_expense_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddySpending; "
                f"from budget.expense_factory import create_expense; "
                f"payer = FeUser.objects.get(pk={ctx_pk}); "
                f"exp = create_expense(title='AlreadyConfirmedExpense', type='expense', "
                f"  value='10.00', owning_feuser=payer, settled=True, buddy_approved=True); "
                f"BuddySpending.objects.create(expense=exp, participant_feuser_id={other_pk}, share_percent='50.000'); "
                f"print(exp.pk)"
            ))

            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                csv_text = _read_csv(zf, "pending_expense_approvals.csv")

            assert "PendingPayerConfirmExpense" in csv_text, "Unconfirmed upfront-payer expense missing from export"
            assert "AlreadyConfirmedExpense" not in csv_text, "Already-confirmed expense must not appear in export"
        finally:
            for pk in (pending_expense_pk, confirmed_expense_pk):
                if pk:
                    _shell(f"from budget.models import Expense; Expense.objects.filter(pk={pk}).delete()")
            cleanup_user(other_email)

    def test_pending_expense_approval_only_shown_to_payer(self, driver, w, ctx):
        """If ctx user creates an expense designating someone else as the
        upfront payer, the pending confirmation must appear only in that
        other person's export, never in ctx user's own export."""
        payer_email = "export_pending_confirm_payer@example.com"
        run_cmd("create_user", payer_email, "-p", "testpass123", *ai_test_api_key_args())
        expense_pk = None
        try:
            ctx_pk = int(_get_pk(ctx["email"]))
            payer_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"print(FeUser.objects.get(email='{payer_email}').pk)"
            ))
            _shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddyLink; "
                f"a = FeUser.objects.get(pk={ctx_pk}); "
                f"b = FeUser.objects.get(pk={payer_pk}); "
                f"lo, hi = sorted([a, b], key=lambda u: u.pk); "
                f"BuddyLink.objects.get_or_create(user_a=lo, user_b=hi)"
            )
            expense_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddySpending; "
                f"from budget.expense_factory import create_expense; "
                f"payer = FeUser.objects.get(pk={payer_pk}); "
                f"exp = create_expense(title='NotMyConfirmationExpense', type='expense', "
                f"  value='15.00', owning_feuser=payer, settled=True, buddy_approved=False); "
                f"BuddySpending.objects.create(expense=exp, participant_feuser_id={ctx_pk}, share_percent='50.000'); "
                f"print(exp.pk)"
            ))

            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                csv_text = _read_csv(zf, "pending_expense_approvals.csv")

            assert "NotMyConfirmationExpense" not in csv_text, (
                "An expense someone else must confirm as payer must not appear in ctx user's own export"
            )
        finally:
            if expense_pk:
                _shell(f"from budget.models import Expense; Expense.objects.filter(pk={expense_pk}).delete()")
            cleanup_user(payer_email)

    def test_project_pending_confirmation_only_in_nested_export(self, driver, w, ctx):
        """A project expense where ctx user was designated upfront payer and
        hasn't confirmed must appear in the nested
        projects/<uid>/pending_payer_confirmations.csv, but NOT in the
        root-level pending_expense_approvals.csv (that file is
        personal/non-project only, like direct-buddy-expenses.csv)."""
        admin_email = "export_pending_confirm_admin@example.com"
        run_cmd("create_user", admin_email, "-p", "testpass123", *ai_test_api_key_args())
        proj_pk = None
        expense_pk = None
        try:
            ctx_pk = int(_get_pk(ctx["email"]))
            proj_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import Project, ProjectMember; "
                f"admin = FeUser.objects.get(email='{admin_email}'); "
                f"member = FeUser.objects.get(pk={ctx_pk}); "
                f"p = Project.objects.create(name='PendingConfirmProject', admin_feuser=admin); "
                f"ProjectMember.objects.create(group=p, feuser=admin); "
                f"ProjectMember.objects.create(group=p, feuser=member); "
                f"print(p.pk)"
            ))
            expense_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from buddies.models import BuddySpending, Project; "
                f"from budget.expense_factory import create_expense; "
                f"payer = FeUser.objects.get(pk={ctx_pk}); "
                f"admin = FeUser.objects.get(email='{admin_email}'); "
                f"proj = Project.objects.get(pk={proj_pk}); "
                f"exp = create_expense(title='ProjectPendingConfirmExpense', type='expense', "
                f"  value='30.00', owning_feuser=payer, settled=True, buddy_approved=False, project=proj); "
                f"BuddySpending.objects.create(expense=exp, participant_feuser=admin, share_percent='50.000'); "
                f"print(exp.pk)"
            ))

            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                root_csv = _read_csv(zf, "pending_expense_approvals.csv")
                nested_csv = _read_csv(zf, f"projects/{proj_pk}/pending_payer_confirmations.csv")

            assert "ProjectPendingConfirmExpense" not in root_csv, (
                "Project expense pending confirmation must not appear in the root personal-only file"
            )
            assert "ProjectPendingConfirmExpense" in nested_csv, (
                "Project expense pending confirmation missing from the nested project export"
            )
        finally:
            if expense_pk:
                _shell(f"from budget.models import Expense; Expense.objects.filter(pk={expense_pk}).delete()")
            if proj_pk:
                _shell(f"from buddies.models import Project; Project.objects.filter(pk={proj_pk}).delete()")
            cleanup_user(admin_email)

    def test_export_requires_authentication(self, driver, w, ctx):
        resp = requests.get(_url("/account/export/"), timeout=10, allow_redirects=False)
        assert resp.status_code in (302, 403), (
            f"Unauthenticated export must redirect or deny, got {resp.status_code}"
        )
