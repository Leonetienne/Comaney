"""
Verify that adding, editing, and deleting a project expense updates
Project.last_mod on the associated project.
"""
import time
from datetime import date

import pytest
import requests

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _create_group, _create_group_expense


def _get_lastmod(group_id: int) -> str:
    return _shell(
        f"from buddies.models import Project; "
        f"p = Project.objects.get(pk={group_id}); "
        f"print(p.last_mod.isoformat())"
    )


def _session_for(user_ctx: dict) -> requests.Session:
    s = requests.Session()
    r = s.get(_url("/login/"))
    csrf = r.cookies.get("csrftoken", "")
    s.post(_url("/login/"), data={
        "email": user_ctx["email"],
        "password": user_ctx["password"],
        "csrfmiddlewaretoken": csrf,
    }, allow_redirects=True)
    return s


def _csrf(session: requests.Session) -> str:
    return session.cookies.get("csrftoken", "")


class TestDeleteExpenseUpdatesProjectLastmod:
    """Deleting a project expense via the budget delete view bumps Project.last_mod."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        user = setup_user(driver, w, first_name="LMDel", last_name="Tester")
        group_id = int(_create_group(user["email"], "LMDel Group"))
        yield {"user": user, "group_id": group_id}
        cleanup_user(user["email"])

    def test_delete_updates_lastmod(self, driver, w, ctx):
        group_id = ctx["group_id"]
        exp_uid = _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import Project; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{ctx['user']['email']}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"e = Expense.objects.create(owning_feuser=u, title='LMDel Expense', "
            f"  type='expense', value=Decimal('50.00'), settled=False, "
            f"  buddy_approved=True, project=g); "
            f"print(e.uid)"
        )
        time.sleep(1)
        before = _get_lastmod(group_id)

        s = _session_for(ctx["user"])
        s.post(
            _url(f"/budget/expenses/{int(exp_uid)}/delete/"),
            data={"csrfmiddlewaretoken": _csrf(s)},
            allow_redirects=True,
        )

        after = _get_lastmod(group_id)
        assert after > before, f"last_mod must increase after delete: before={before} after={after}"


class TestEditExpenseUnlinkUpdatesProjectLastmod:
    """Removing the buddy connection from a project expense updates the old project's last_mod."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        user = setup_user(driver, w, first_name="LMEdit", last_name="Tester")
        group_id = int(_create_group(user["email"], "LMEdit Group"))
        yield {"user": user, "group_id": group_id}
        cleanup_user(user["email"])

    def test_edit_unlink_updates_lastmod(self, driver, w, ctx):
        group_id = ctx["group_id"]
        today = date.today().isoformat()
        exp_uid = _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import Project; "
            f"from feusers.models import FeUser; from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{ctx['user']['email']}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"e = Expense.objects.create(owning_feuser=u, title='LMEdit Expense', "
            f"  type='expense', value=Decimal('40.00'), settled=False, "
            f"  buddy_approved=True, project=g); "
            f"print(e.uid)"
        )
        time.sleep(1)
        before = _get_lastmod(group_id)

        # POST the edit form without buddy_payment to strip the buddy/project link
        s = _session_for(ctx["user"])
        s.post(
            _url(f"/budget/expenses/{int(exp_uid)}/edit/"),
            data={
                "csrfmiddlewaretoken": _csrf(s),
                "title": "LMEdit Expense",
                "type": "expense",
                "value": "40.00",
                "date_due": today,
                "settled": "on",
                "notify": "on",
            },
            allow_redirects=True,
        )

        after = _get_lastmod(group_id)
        assert after > before, f"last_mod must increase after unlink: before={before} after={after}"


class TestAddExpenseUpdatesProjectLastmod:
    """Creating a project expense via the expense create view bumps Project.last_mod."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        user = setup_user(driver, w, first_name="LMAdd", last_name="Tester")
        group_id = int(_create_group(user["email"], "LMAdd Group"))
        yield {"user": user, "group_id": group_id}
        cleanup_user(user["email"])

    def test_add_expense_updates_lastmod(self, driver, w, ctx):
        group_id = ctx["group_id"]
        today = date.today().isoformat()
        time.sleep(1)
        before = _get_lastmod(group_id)

        # POST a new group expense (upfront_type=me, mode=group)
        s = _session_for(ctx["user"])
        s.post(
            _url("/budget/expenses/new/"),
            data={
                "csrfmiddlewaretoken": _csrf(s),
                "title": "LMAdd Expense",
                "type": "expense",
                "value": "30.00",
                "date_due": today,
                "settled": "on",
                "notify": "on",
                "buddy_payment": "1",
                "buddy_mode": "group",
                "buddy_upfront_type": "me",
                "project_id": str(group_id),
                "spendings_json": "[]",
            },
            allow_redirects=True,
        )

        after = _get_lastmod(group_id)
        assert after > before, f"last_mod must increase after add: before={before} after={after}"
