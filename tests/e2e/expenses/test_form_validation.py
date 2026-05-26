"""
Server-side form and JSON endpoint validation tests.

Uses the browser session cookies to authenticate a requests.Session,
then posts directly to form and JSON endpoints to verify that invalid
input returns 200 (form re-render) or 400 (JSON error) rather than
a redirect.
"""
import re
import requests
import pytest

from helpers import BASE_URL, session_cookies, setup_user, cleanup_user
from bhelpers import _create_group, _shell

BUDDY_TYPE_CONFLICT_TEXT = "must be type"  # rendered HTML-escapes the quotes around "Expense"


LONG_128  = "x" * 129
LONG_1024 = "x" * 1025


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


def _session(driver):
    s = requests.Session()
    s.cookies.update(session_cookies(driver))
    if not s.cookies.get("csrftoken"):
        s.get(BASE_URL + "/budget/categories-tags/")
    return s


def _csrf(s):
    return s.cookies.get("csrftoken", "")


def _form_post(s, path, data):
    import re as _re
    csrf = _csrf(s)
    r = s.get(BASE_URL + path)
    m = _re.search(r'name="form_nonce"\s+value="([^"]+)"', r.text)
    nonce = m.group(1) if m else ""
    post_data = {"csrfmiddlewaretoken": csrf, **data}
    if nonce:
        post_data["form_nonce"] = nonce
    return s.post(
        BASE_URL + path,
        data=post_data,
        headers={"Referer": BASE_URL + "/"},
        allow_redirects=False,
    )


def _json_post(s, path, payload):
    csrf = _csrf(s)
    return s.post(
        BASE_URL + path,
        json=payload,
        headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
        allow_redirects=False,
    )


BASE_EXPENSE = {
    "title": "Val",
    "type": "expense",
    "value": "1.00",
    "date_due": "2026-01-01",
    "settled": "1",
    "notify": "1",
}

BASE_SCHEDULED = {
    "title": "Val",
    "type": "expense",
    "value": "1.00",
    "repeat_every_factor": "1",
    "repeat_every_unit": "months",
    "repeat_base_date": "2026-01-01",
    "notify": "1",
}

BASE_PROFILE = {
    "action": "profile",
    "first_name": "Test",
    "last_name": "Test",
    "currency": "€",
    "month_start_day": "1",
    "unspent_allowance_action": "do_nothing",
}


class TestCategoryTagJsonEndpoints:

    def test_category_create_title_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _json_post(s, "/budget/categories/create/", {"title": LONG_128})
        assert resp.status_code == 400

    def test_category_rename_title_too_long(self, driver, w, ctx):
        s = _session(driver)
        cat = _json_post(s, "/budget/categories/create/", {"title": "FVCat"}).json()
        resp = _json_post(s, f"/budget/categories/{cat['uid']}/rename/", {"title": LONG_128})
        assert resp.status_code == 400

    def test_tag_create_title_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _json_post(s, "/budget/tags/create/", {"title": LONG_128})
        assert resp.status_code == 400

    def test_tag_rename_title_too_long(self, driver, w, ctx):
        s = _session(driver)
        tag = _json_post(s, "/budget/tags/create/", {"title": "FVTag"}).json()
        resp = _json_post(s, f"/budget/tags/{tag['uid']}/rename/", {"title": LONG_128})
        assert resp.status_code == 400


class TestExpenseFormValidation:

    def test_title_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/expenses/new/", {**BASE_EXPENSE, "title": LONG_128})
        assert resp.status_code == 200

    def test_payee_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/expenses/new/", {**BASE_EXPENSE, "payee": LONG_128})
        assert resp.status_code == 200

    def test_note_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/expenses/new/", {**BASE_EXPENSE, "note": LONG_1024})
        assert resp.status_code == 200


def _expense_count(email: str) -> int:
    return int(_shell(
        f"from feusers.models import FeUser; from budget.models import Expense; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"print(Expense.objects.filter(owning_feuser=u).count())"
    ))


def _scheduled_count(email: str) -> int:
    return int(_shell(
        f"from feusers.models import FeUser; from budget.models import ScheduledExpense; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"print(ScheduledExpense.objects.filter(owning_feuser=u).count())"
    ))


BASE_PROJECT_BUDDY_FIELDS = {
    "buddy_payment": "1",
    "buddy_mode": "group",
    "buddy_spendings_json": "[]",
}


class TestProjectExpenseTypeValidation:
    """Project expenses must stay type=EXPENSE: income/savings would invert
    the shared debt calculation (see analysis on the project's income handling)."""

    @pytest.fixture(scope="class")
    def project_id(self, driver, w, ctx):
        return int(_create_group(ctx["email"], "Type Validation Project"))

    def test_income_is_rejected(self, driver, w, ctx, project_id):
        s = _session(driver)
        before = _expense_count(ctx["email"])
        resp = _form_post(s, "/budget/expenses/new/", {
            **BASE_EXPENSE, **BASE_PROJECT_BUDDY_FIELDS,
            "type": "income", "project_id": str(project_id),
        })
        assert resp.status_code == 200, "Form must re-render, not redirect, when rejected"
        assert _expense_count(ctx["email"]) == before, "No expense must be created"
        assert BUDDY_TYPE_CONFLICT_TEXT in resp.text, "A clear error must explain the rejection"
        assert re.search(rf"existingGroupId:\s*{project_id}\b", resp.text), (
            "The project selection must be preserved on the re-rendered form, not silently cleared"
        )
        assert "initAssign = 'project';" in resp.text, (
            "The Project assignment tab must still be marked active on re-render"
        )

    def test_savings_deposit_is_rejected(self, driver, w, ctx, project_id):
        s = _session(driver)
        before = _expense_count(ctx["email"])
        resp = _form_post(s, "/budget/expenses/new/", {
            **BASE_EXPENSE, **BASE_PROJECT_BUDDY_FIELDS,
            "type": "savings_dep", "project_id": str(project_id),
        })
        assert resp.status_code == 200
        assert _expense_count(ctx["email"]) == before

    def test_expense_is_accepted(self, driver, w, ctx, project_id):
        s = _session(driver)
        before = _expense_count(ctx["email"])
        resp = _form_post(s, "/budget/expenses/new/", {
            **BASE_EXPENSE, **BASE_PROJECT_BUDDY_FIELDS,
            "type": "expense", "project_id": str(project_id),
        })
        assert resp.status_code == 302, "Valid project expense must redirect on success"
        assert _expense_count(ctx["email"]) == before + 1


class TestProjectExpenseEditTypeValidation:
    """Editing an existing project expense to a non-expense type must be
    rejected the same way creation is, with the assignment preserved on screen
    and the underlying record left untouched."""

    @pytest.fixture(scope="class")
    def project_id(self, driver, w, ctx):
        return int(_create_group(ctx["email"], "Edit Type Validation Project"))

    @pytest.fixture(scope="class")
    def expense_uid(self, driver, w, ctx, project_id):
        s = _session(driver)
        resp = _form_post(s, "/budget/expenses/new/", {
            **BASE_EXPENSE, **BASE_PROJECT_BUDDY_FIELDS,
            "type": "expense", "project_id": str(project_id), "title": "EditTypeValExpense",
        })
        assert resp.status_code == 302, "Setup: valid project expense must be created"
        return int(_shell(
            f"from feusers.models import FeUser; from budget.models import Expense; "
            f"u = FeUser.objects.get(email='{ctx['email']}'); "
            f"print(Expense.objects.get(owning_feuser=u, title='EditTypeValExpense').uid)"
        ))

    def test_edit_to_income_is_rejected(self, driver, w, ctx, project_id, expense_uid):
        s = _session(driver)
        resp = _form_post(s, f"/budget/expenses/{expense_uid}/edit/", {
            **BASE_EXPENSE, **BASE_PROJECT_BUDDY_FIELDS,
            "type": "income", "project_id": str(project_id), "title": "EditTypeValExpense",
        })
        assert resp.status_code == 200, "Edit must re-render, not redirect, when rejected"
        assert BUDDY_TYPE_CONFLICT_TEXT in resp.text, "A clear error must explain the rejection"
        assert re.search(rf"existingGroupId:\s*{project_id}\b", resp.text), (
            "The project assignment must still show as selected on the re-rendered edit form"
        )
        state = _shell(
            f"from budget.models import Expense; "
            f"e = Expense.objects.get(uid={expense_uid}); "
            f"print(e.type + '|' + str(e.project_id))"
        )
        assert state == f"expense|{project_id}", f"Underlying record must be left unchanged, got {state!r}"


class TestScheduledFormValidation:

    def test_title_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/scheduled/new/", {**BASE_SCHEDULED, "title": LONG_128})
        assert resp.status_code == 200

    def test_payee_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/scheduled/new/", {**BASE_SCHEDULED, "payee": LONG_128})
        assert resp.status_code == 200

    def test_note_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/budget/scheduled/new/", {**BASE_SCHEDULED, "note": LONG_1024})
        assert resp.status_code == 200

    def test_repeat_factor_missing(self, driver, w, ctx):
        s = _session(driver)
        data = {k: v for k, v in BASE_SCHEDULED.items() if k != "repeat_every_factor"}
        resp = _form_post(s, "/budget/scheduled/new/", data)
        assert resp.status_code == 200

    def test_repeat_unit_missing(self, driver, w, ctx):
        s = _session(driver)
        data = {k: v for k, v in BASE_SCHEDULED.items() if k != "repeat_every_unit"}
        resp = _form_post(s, "/budget/scheduled/new/", data)
        assert resp.status_code == 200


class TestScheduledProjectTypeValidation:
    """Same EXPENSE-only rule applies to scheduled (recurring) project expenses,
    since _parse_buddy_post is shared between the expense and scheduled forms."""

    @pytest.fixture(scope="class")
    def project_id(self, driver, w, ctx):
        return int(_create_group(ctx["email"], "Scheduled Type Validation Project"))

    def test_income_is_rejected(self, driver, w, ctx, project_id):
        s = _session(driver)
        before = _scheduled_count(ctx["email"])
        resp = _form_post(s, "/budget/scheduled/new/", {
            **BASE_SCHEDULED, **BASE_PROJECT_BUDDY_FIELDS,
            "type": "income", "project_id": str(project_id),
        })
        assert resp.status_code == 200
        assert _scheduled_count(ctx["email"]) == before

    def test_expense_is_accepted(self, driver, w, ctx, project_id):
        s = _session(driver)
        before = _scheduled_count(ctx["email"])
        resp = _form_post(s, "/budget/scheduled/new/", {
            **BASE_SCHEDULED, **BASE_PROJECT_BUDDY_FIELDS,
            "type": "expense", "project_id": str(project_id),
        })
        assert resp.status_code == 302
        assert _scheduled_count(ctx["email"]) == before + 1


class TestProfileFormValidation:

    def test_first_name_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/profile/", {**BASE_PROFILE, "first_name": LONG_128})
        assert resp.status_code == 200

    def test_last_name_too_long(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/profile/", {**BASE_PROFILE, "last_name": LONG_128})
        assert resp.status_code == 200

    def test_month_start_day_out_of_range(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/profile/", {**BASE_PROFILE, "month_start_day": "99"})
        assert resp.status_code == 200

    def test_invalid_allowance_action(self, driver, w, ctx):
        s = _session(driver)
        resp = _form_post(s, "/profile/", {**BASE_PROFILE, "unspent_allowance_action": "invalid_action"})
        assert resp.status_code == 200
