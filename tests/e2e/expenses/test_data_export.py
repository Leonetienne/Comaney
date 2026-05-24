"""
Account data export (ZIP):
- Returns application/zip
- Contains all expected CSV files
- Expense and category data appears in the correct CSV
- anthropic_api_key is masked (only last 4 chars visible)
- Unauthenticated request is redirected
- foreign_expenses.csv: expenses owned by others where user is participant (same scheme as expenses.csv)
- expense_participants.csv: BuddySpending rows for own expenses
- expense_overlays.csv: feuser's personal overlays on shared expenses
- administered_projects.csv + project_offline_members.csv for admin projects
- offline_buddies.csv for personally-owned offline buddies
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
    run_cmd,
)

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
            "expense_participants.csv",
            "scheduled_expenses.csv",
            "dashboard_cards.csv",
            "foreign_expenses.csv",
            "expense_overlays.csv",
            "real_user_buddies.csv",
            "project_memberships.csv",
            "administered_projects.csv",
            "project_offline_members.csv",
            "offline_buddies.csv",
        ):
            assert expected in names, f"{expected} missing from export ZIP"

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

    def test_foreign_expense_appears_in_export(self, driver, w, ctx):
        """Expense owned by another user where ctx user is a participant must appear in foreign_expenses.csv
        (same scheme as expenses.csv, with owning_feuser_email as extra column), and must NOT appear
        in own expenses.csv."""
        owner_email = "export_owner_foreign@example.com"
        run_cmd("create_user", owner_email, "-p", "testpass123")
        try:
            participant_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"print(FeUser.objects.get(email='{ctx['email']}').pk)"
            ))
            expense_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from budget.expense_factory import create_expense; "
                f"owner = FeUser.objects.get(email='{owner_email}'); "
                f"exp = create_expense(title='ForeignExportExpense', type='expense', "
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
                foreign_csv = _read_csv(zf, "foreign_expenses.csv")
                own_csv     = _read_csv(zf, "expenses.csv")

            assert "ForeignExportExpense" in foreign_csv, "Foreign expense title missing from foreign_expenses.csv"
            assert owner_email in foreign_csv, "Expense owner email missing from foreign_expenses.csv"
            assert "ForeignExportExpense" not in own_csv, "Foreign expense must not appear in expenses.csv"
        finally:
            cleanup_user(owner_email)

    def test_expense_participants_in_export(self, driver, w, ctx):
        """BuddySpending rows for own expenses must appear in expense_participants.csv."""
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
            f"from buddies.models import BuddySpending, DummyUser; "
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
                part_csv = _read_csv(zf, "expense_participants.csv")

            assert "ParticipantTestExpense" in part_csv, "Expense title missing from expense_participants.csv"
            assert "ExportParticipant" in part_csv, "Dummy participant name missing from expense_participants.csv"
            assert "33" in part_csv, "Share percent missing from expense_participants.csv"
        finally:
            _shell(
                f"from budget.models import Expense; Expense.objects.filter(pk={expense_pk}).delete()"
            )
            _shell(
                f"from buddies.models import DummyUser; DummyUser.objects.filter(pk={dummy_pk}).delete()"
            )

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

    def test_foreign_expenses_no_category_tag_columns(self, driver, w, ctx):
        """foreign_expenses.csv must not expose the expense owner's category_id or tag_ids."""
        owner_email = "export_owner_fcat@example.com"
        run_cmd("create_user", owner_email, "-p", "testpass123")
        try:
            participant_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"print(FeUser.objects.get(email='{ctx['email']}').pk)"
            ))
            expense_pk = int(_shell(
                f"from feusers.models import FeUser; "
                f"from budget.expense_factory import create_expense; "
                f"owner = FeUser.objects.get(email='{owner_email}'); "
                f"exp = create_expense(title='ForeignCatTagExpense', type='expense', "
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
                foreign_csv = _read_csv(zf, "foreign_expenses.csv")

            header = foreign_csv.splitlines()[0]
            assert "category_id" not in header, "category_id must not appear in foreign_expenses.csv headers"
            assert "tag_ids" not in header, "tag_ids must not appear in foreign_expenses.csv headers"
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
        run_cmd("create_user", owner_email, "-p", "testpass123")
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

    def test_real_user_buddies_in_export(self, driver, w, ctx):
        """real_user_buddies.csv must contain entries for confirmed buddy connections."""
        buddy_email = "export_buddy_real@example.com"
        run_cmd("create_user", buddy_email, "-p", "testpass123")
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
                csv_text = _read_csv(zf, "real_user_buddies.csv")

            assert buddy_email in csv_text, "Buddy email missing from real_user_buddies.csv"
        finally:
            _shell(f"from buddies.models import BuddyLink; BuddyLink.objects.filter(pk={link_pk}).delete()")
            cleanup_user(buddy_email)

    def test_project_memberships_in_export(self, driver, w, ctx):
        """project_memberships.csv must list projects the feuser is a member of."""
        proj_pk = int(_shell(
            f"from feusers.models import FeUser; "
            f"from buddies.models import Project, ProjectMember; "
            f"u = FeUser.objects.get(email='{ctx['email']}'); "
            f"p = Project.objects.create(name='ExportMemberProject', admin_feuser=u); "
            f"ProjectMember.objects.create(group=p, feuser=u); "
            f"print(p.pk)"
        ))
        try:
            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                csv_text = _read_csv(zf, "project_memberships.csv")

            assert "ExportMemberProject" in csv_text, "Project name missing from project_memberships.csv"
            assert "True" in csv_text, "is_admin=True missing for admin member in project_memberships.csv"
        finally:
            _shell(f"from buddies.models import Project; Project.objects.filter(pk={proj_pk}).delete()")

    def test_administered_project_in_export(self, driver, w, ctx):
        """administered_projects.csv must contain full project records for admin projects."""
        proj_pk = int(_shell(
            f"from feusers.models import FeUser; "
            f"from buddies.models import Project; "
            f"u = FeUser.objects.get(email='{ctx['email']}'); "
            f"p = Project.objects.create(name='ExportAdminProject', description='desc', admin_feuser=u); "
            f"print(p.pk)"
        ))
        try:
            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                csv_text = _read_csv(zf, "administered_projects.csv")

            assert "ExportAdminProject" in csv_text, "Project name missing from administered_projects.csv"
            assert "desc" in csv_text, "Project description missing from administered_projects.csv"
        finally:
            _shell(f"from buddies.models import Project; Project.objects.filter(pk={proj_pk}).delete()")

    def test_project_offline_members_in_export(self, driver, w, ctx):
        """project_offline_members.csv must list offline members of admin projects."""
        ids = _shell(
            f"from feusers.models import FeUser; "
            f"from buddies.models import Project, DummyUser; "
            f"u = FeUser.objects.get(email='{ctx['email']}'); "
            f"p = Project.objects.create(name='ExportOfflineProject', admin_feuser=u); "
            f"d = DummyUser.objects.create(owning_group=p, display_name='ExportOfflineMember'); "
            f"print(p.pk, d.pk)"
        ).split()
        proj_pk, dummy_pk = int(ids[0]), int(ids[1])
        try:
            time.sleep(1)
            resp = _get_export(driver)
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                csv_text = _read_csv(zf, "project_offline_members.csv")

            assert "ExportOfflineMember" in csv_text, "Offline member name missing from project_offline_members.csv"
            assert "ExportOfflineProject" in csv_text, "Project name missing from project_offline_members.csv"
        finally:
            _shell(f"from buddies.models import Project; Project.objects.filter(pk={proj_pk}).delete()")

    def test_offline_buddies_in_export(self, driver, w, ctx):
        """offline_buddies.csv must list personally-owned offline buddies."""
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
                csv_text = _read_csv(zf, "offline_buddies.csv")

            assert "ExportPersonalDummy" in csv_text, "Offline buddy name missing from offline_buddies.csv"
        finally:
            _shell(f"from buddies.models import DummyUser; DummyUser.objects.filter(pk={dummy_pk}).delete()")

    def test_export_requires_authentication(self, driver, w, ctx):
        resp = requests.get(_url("/account/export/"), timeout=10, allow_redirects=False)
        assert resp.status_code in (302, 403), (
            f"Unauthenticated export must redirect or deny, got {resp.status_code}"
        )
