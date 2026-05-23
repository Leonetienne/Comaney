"""
Query parser feature tests via the REST API expense list endpoint.

Uses GET /api/v1/expenses/?q=QUERY&view=year&year=2025 to verify
date comparisons (all three formats), the 'today' keyword, value
comparisons, the NOT operator, multi-constraint tag filters, and
the deactivated= flag.  No browser interaction required.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import (
    _url, fill,
    api_get, api_post, api_patch, api_delete,
    server_today, setup_user, cleanup_user, run_cmd,
)

YEAR = 2025
PAST_ISO   = "2025-03-01"
MID_ISO    = "2025-06-15"
FUTURE_ISO = "2025-09-01"


def _api_titles(ctx, q, year=2025):
    params = {"q": q, "view": "year", "year": year}
    resp = api_get("/api/v1/expenses/", ctx, params=params)
    return [e["title"] for e in resp.json()["expenses"]]


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)

    past = api_post("/api/v1/expenses/", c, json={
        "title": "QP Past", "type": "expense", "value": "10.00",
        "date_due": PAST_ISO, "settled": False,
    })
    assert past.status_code == 201
    c["qp_past"] = past.json()["id"]

    mid = api_post("/api/v1/expenses/", c, json={
        "title": "QP Mid", "type": "expense", "value": "20.00",
        "date_due": MID_ISO, "settled": False,
    })
    assert mid.status_code == 201
    c["qp_mid"] = mid.json()["id"]

    future = api_post("/api/v1/expenses/", c, json={
        "title": "QP Future", "type": "expense", "value": "30.00",
        "date_due": FUTURE_ISO, "settled": False,
    })
    assert future.status_code == 201
    c["qp_future"] = future.json()["id"]

    income = api_post("/api/v1/expenses/", c, json={
        "title": "QP Income", "type": "income", "value": "500.00",
        "date_due": MID_ISO, "settled": False,
    })
    assert income.status_code == 201
    c["qp_income"] = income.json()["id"]

    deact = api_post("/api/v1/expenses/", c, json={
        "title": "QP Deact", "type": "expense", "value": "99.00",
        "date_due": MID_ISO, "settled": False,
    })
    assert deact.status_code == 201
    c["qp_deact"] = deact.json()["id"]
    r = api_patch(f"/api/v1/expenses/{c['qp_deact']}/", c, json={"deactivated": True})
    assert r.status_code == 200

    yield c

    for key in ("qp_past", "qp_mid", "qp_future", "qp_income", "qp_deact"):
        if key in c:
            api_delete(f"/api/v1/expenses/{c[key]}/", c)
    cleanup_user(c["email"])


class TestDateFormats:

    # dd.mm.yyyy

    def test_dmy_gt(self, driver, w, ctx):
        t = _api_titles(ctx, "date>01.03.2025")
        assert "QP Mid" in t and "QP Future" in t and "QP Past" not in t

    def test_dmy_gte(self, driver, w, ctx):
        t = _api_titles(ctx, "date>=15.06.2025")
        assert "QP Mid" in t and "QP Future" in t and "QP Past" not in t

    def test_dmy_lt(self, driver, w, ctx):
        t = _api_titles(ctx, "date<01.09.2025")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" not in t

    def test_dmy_lte(self, driver, w, ctx):
        t = _api_titles(ctx, "date<=15.06.2025")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" not in t

    def test_dmy_eq(self, driver, w, ctx):
        t = _api_titles(ctx, "date=15.06.2025")
        assert "QP Mid" in t and "QP Past" not in t and "QP Future" not in t

    def test_dmy_eqeq(self, driver, w, ctx):
        t = _api_titles(ctx, "date==15.06.2025")
        assert "QP Mid" in t and "QP Past" not in t and "QP Future" not in t

    # mm/dd/yyyy

    def test_mdy_gt(self, driver, w, ctx):
        t = _api_titles(ctx, "date>03/01/2025")
        assert "QP Mid" in t and "QP Future" in t and "QP Past" not in t

    def test_mdy_gte(self, driver, w, ctx):
        t = _api_titles(ctx, "date>=06/15/2025")
        assert "QP Mid" in t and "QP Future" in t and "QP Past" not in t

    def test_mdy_lt(self, driver, w, ctx):
        t = _api_titles(ctx, "date<09/01/2025")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" not in t

    def test_mdy_lte(self, driver, w, ctx):
        t = _api_titles(ctx, "date<=06/15/2025")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" not in t

    def test_mdy_eq(self, driver, w, ctx):
        t = _api_titles(ctx, "date=06/15/2025")
        assert "QP Mid" in t and "QP Past" not in t and "QP Future" not in t

    def test_mdy_eqeq(self, driver, w, ctx):
        t = _api_titles(ctx, "date==06/15/2025")
        assert "QP Mid" in t and "QP Past" not in t and "QP Future" not in t

    # yyyy-mm-dd

    def test_iso_gt(self, driver, w, ctx):
        t = _api_titles(ctx, "date>2025-03-01")
        assert "QP Mid" in t and "QP Future" in t and "QP Past" not in t

    def test_iso_gte(self, driver, w, ctx):
        t = _api_titles(ctx, "date>=2025-06-15")
        assert "QP Mid" in t and "QP Future" in t and "QP Past" not in t

    def test_iso_lt(self, driver, w, ctx):
        t = _api_titles(ctx, "date<2025-09-01")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" not in t

    def test_iso_lte(self, driver, w, ctx):
        t = _api_titles(ctx, "date<=2025-06-15")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" not in t

    def test_iso_eq(self, driver, w, ctx):
        t = _api_titles(ctx, "date=2025-06-15")
        assert "QP Mid" in t and "QP Past" not in t and "QP Future" not in t

    def test_iso_eqeq(self, driver, w, ctx):
        t = _api_titles(ctx, "date==2025-06-15")
        assert "QP Mid" in t and "QP Past" not in t and "QP Future" not in t


class TestTodayKeyword:

    def test_setup_today(self, driver, w, ctx):
        today_iso = server_today()
        ctx["qp_today_iso"] = today_iso
        exp = api_post("/api/v1/expenses/", ctx, json={
            "title": "QP Today", "type": "expense", "value": "5.00",
            "date_due": today_iso, "settled": False,
        })
        assert exp.status_code == 201
        ctx["qp_today_dyn"] = exp.json()["id"]

    def _titles_today(self, ctx, q):
        resp = api_get("/api/v1/expenses/", ctx, params={"q": q, "view": "year"})
        return [e["title"] for e in resp.json()["expenses"]]

    def test_today_eq(self, driver, w, ctx):
        t = self._titles_today(ctx, "date=today")
        assert "QP Today" in t

    def test_today_eqeq(self, driver, w, ctx):
        t = self._titles_today(ctx, "date==today")
        assert "QP Today" in t

    def test_today_gt(self, driver, w, ctx):
        t = self._titles_today(ctx, "date>today")
        assert "QP Today" not in t

    def test_today_lt(self, driver, w, ctx):
        t = self._titles_today(ctx, "date<today")
        assert "QP Today" not in t

    def test_today_gte(self, driver, w, ctx):
        t = self._titles_today(ctx, "date>=today")
        assert "QP Today" in t

    def test_today_lte(self, driver, w, ctx):
        t = self._titles_today(ctx, "date<=today")
        assert "QP Today" in t

    def test_cleanup_today(self, driver, w, ctx):
        if "qp_today_dyn" in ctx:
            api_delete(f"/api/v1/expenses/{ctx.pop('qp_today_dyn')}/", ctx)
        ctx.pop("qp_today_iso", None)


class TestValueComparisons:

    def test_value_exclusive_range(self, driver, w, ctx):
        t = _api_titles(ctx, "value>10 value<30")
        assert "QP Mid" in t and "QP Past" not in t and "QP Future" not in t

    def test_value_inclusive_range(self, driver, w, ctx):
        t = _api_titles(ctx, "value>=10 value<=20")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" not in t

    def test_value_not_range(self, driver, w, ctx):
        t = _api_titles(ctx, "value>=10 !value>=30")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" not in t


class TestNotOperator:

    def test_not_term(self, driver, w, ctx):
        t = _api_titles(ctx, "type=expense !(QP Past)")
        assert "QP Mid" in t and "QP Future" in t and "QP Past" not in t

    def test_not_filter(self, driver, w, ctx):
        t = _api_titles(ctx, "!type=income")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" in t
        assert "QP Income" not in t

    def test_not_group(self, driver, w, ctx):
        t = _api_titles(ctx, "!(type=income)")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" in t
        assert "QP Income" not in t

    def test_not_group_with_or(self, driver, w, ctx):
        t = _api_titles(ctx, "type=expense !(QP Past || QP Future)")
        assert "QP Mid" in t
        assert "QP Past" not in t and "QP Future" not in t


class TestMultipleConstraints:

    def test_setup_tags(self, driver, w, ctx):
        ta = api_post("/api/v1/tags/", ctx, json={"title": "qptaga"})
        assert ta.status_code == 201
        ctx["qp_tag_a"] = ta.json()["id"]

        tb = api_post("/api/v1/tags/", ctx, json={"title": "qptagb"})
        assert tb.status_code == 201
        ctx["qp_tag_b"] = tb.json()["id"]

        only_a = api_post("/api/v1/expenses/", ctx, json={
            "title": "QP TagA", "type": "expense", "value": "1.00",
            "date_due": MID_ISO, "tag_ids": [ctx["qp_tag_a"]],
        })
        assert only_a.status_code == 201
        ctx["qp_only_a"] = only_a.json()["id"]

        only_b = api_post("/api/v1/expenses/", ctx, json={
            "title": "QP TagB", "type": "expense", "value": "2.00",
            "date_due": MID_ISO, "tag_ids": [ctx["qp_tag_b"]],
        })
        assert only_b.status_code == 201
        ctx["qp_only_b"] = only_b.json()["id"]

        both = api_post("/api/v1/expenses/", ctx, json={
            "title": "QP TagBoth", "type": "expense", "value": "3.00",
            "date_due": MID_ISO, "tag_ids": [ctx["qp_tag_a"], ctx["qp_tag_b"]],
        })
        assert both.status_code == 201
        ctx["qp_both"] = both.json()["id"]

    def test_tag_and(self, driver, w, ctx):
        t = _api_titles(ctx, "tag=qptaga tag=qptagb")
        assert "QP TagBoth" in t
        assert "QP TagA" not in t and "QP TagB" not in t

    def test_tag_not(self, driver, w, ctx):
        t = _api_titles(ctx, "tag=qptaga !tag=qptagb")
        assert "QP TagA" in t
        assert "QP TagBoth" not in t and "QP TagB" not in t

    def test_cleanup_tags(self, driver, w, ctx):
        for key in ("qp_only_a", "qp_only_b", "qp_both"):
            if key in ctx:
                api_delete(f"/api/v1/expenses/{ctx.pop(key)}/", ctx)
        for key in ("qp_tag_a", "qp_tag_b"):
            if key in ctx:
                api_delete(f"/api/v1/tags/{ctx.pop(key)}/", ctx)


class TestDeactivated:

    def test_deactivated_yes(self, driver, w, ctx):
        t = _api_titles(ctx, "deactivated=yes")
        assert "QP Deact" in t
        assert "QP Past" not in t and "QP Mid" not in t and "QP Future" not in t

    def test_deactivated_no(self, driver, w, ctx):
        t = _api_titles(ctx, "deactivated=no")
        assert "QP Past" in t and "QP Mid" in t and "QP Future" in t
        assert "QP Deact" not in t


class TestRecurring:

    def test_setup(self, driver, w, ctx):
        today = server_today()
        ctx["qp_recurring_year"] = today[:4]

        r = api_post("/api/v1/expenses/", ctx, json={
            "title": "QP NotRecurring", "type": "expense", "value": "15.00",
            "date_due": today,
        })
        assert r.status_code == 201
        ctx["qp_not_recurring"] = r.json()["id"]

        r = api_post("/api/v1/scheduled/", ctx, json={
            "title": "QP Recurring", "type": "expense", "value": "25.00",
            "repeat_base_date": today, "repeat_every_factor": 1, "repeat_every_unit": "months",
        })
        assert r.status_code == 201
        ctx["qp_recurring_source_id"] = r.json()["id"]

        run_cmd("generate_scheduled_expenses")

    def _titles(self, ctx, q):
        year = ctx["qp_recurring_year"]
        resp = api_get("/api/v1/expenses/", ctx, params={"q": q, "view": "year", "year": year})
        return [e["title"] for e in resp.json()["expenses"]]

    def test_recurring_yes_includes_recurring(self, driver, w, ctx):
        t = self._titles(ctx, "recurring=yes")
        assert "QP Recurring" in t

    def test_recurring_yes_excludes_non_recurring(self, driver, w, ctx):
        t = self._titles(ctx, "recurring=yes")
        assert "QP NotRecurring" not in t

    def test_recurring_no_includes_non_recurring(self, driver, w, ctx):
        t = self._titles(ctx, "recurring=no")
        assert "QP NotRecurring" in t

    def test_recurring_no_excludes_recurring(self, driver, w, ctx):
        t = self._titles(ctx, "recurring=no")
        assert "QP Recurring" not in t

    def test_cleanup(self, driver, w, ctx):
        year = ctx.get("qp_recurring_year")
        if year:
            resp = api_get("/api/v1/expenses/", ctx, params={"q": "QP Recurring", "view": "year", "year": year})
            for e in resp.json()["expenses"]:
                api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        if "qp_not_recurring" in ctx:
            api_delete(f"/api/v1/expenses/{ctx.pop('qp_not_recurring')}/", ctx)
        if "qp_recurring_source_id" in ctx:
            api_delete(f"/api/v1/scheduled/{ctx.pop('qp_recurring_source_id')}/", ctx)
        ctx.pop("qp_recurring_year", None)


class TestWeekKeywords:

    def _titles(self, ctx, q):
        resp = api_get("/api/v1/expenses/", ctx, params={"q": q, "view": "year"})
        return [e["title"] for e in resp.json()["expenses"]]

    def test_setup_week(self, driver, w, ctx):
        today_iso = server_today()
        exp = api_post("/api/v1/expenses/", ctx, json={
            "title": "QP ThisWeek", "type": "expense", "value": "9.00",
            "date_due": today_iso, "settled": False,
        })
        assert exp.status_code == 201
        ctx["qp_this_week"] = exp.json()["id"]

    def test_cur_week_start_lte_today(self, driver, w, ctx):
        # cur_week_start is Monday; today >= Monday, so date>=cur_week_start must include today
        t = self._titles(ctx, "date>=cur_week_start")
        assert "QP ThisWeek" in t

    def test_cur_week_end_gte_today(self, driver, w, ctx):
        # cur_week_end is Sunday; today <= Sunday, so date<=cur_week_end must include today
        t = self._titles(ctx, "date<=cur_week_end")
        assert "QP ThisWeek" in t

    def test_cur_week_range_includes_today(self, driver, w, ctx):
        t = self._titles(ctx, "date>=cur_week_start date<=cur_week_end")
        assert "QP ThisWeek" in t

    def test_cur_week_range_excludes_past(self, driver, w, ctx):
        # PAST_ISO = 2025-03-01 which is well outside any current week
        t = self._titles(ctx, "date>=cur_week_start date<=cur_week_end")
        assert "QP Past" not in t

    def test_cur_week_start_excludes_before_week(self, driver, w, ctx):
        # date<cur_week_start must NOT include today (today is within the week)
        t = self._titles(ctx, "date<cur_week_start")
        assert "QP ThisWeek" not in t

    def test_cur_week_end_excludes_after_week(self, driver, w, ctx):
        # date>cur_week_end must NOT include today
        t = self._titles(ctx, "date>cur_week_end")
        assert "QP ThisWeek" not in t

    def test_cleanup_week(self, driver, w, ctx):
        if "qp_this_week" in ctx:
            api_delete(f"/api/v1/expenses/{ctx.pop('qp_this_week')}/", ctx)


def _exp_url():
    return _url("/budget/expenses/")


def _search_val(driver):
    return driver.find_element(By.ID, "exp-search").get_attribute("value")


def _checkbox_checked(driver):
    return driver.find_element(By.ID, "exp-hide-recurring").is_selected()


def _set_search(driver, value):
    el = driver.find_element(By.ID, "exp-search")
    driver.execute_script(
        "var e = arguments[0]; e.value = arguments[1];"
        "e.dispatchEvent(new Event('input', {bubbles:true}));",
        el, value,
    )
    time.sleep(0.3)


def _click_checkbox(driver):
    driver.find_element(By.ID, "exp-hide-recurring").click()
    time.sleep(0.3)


class TestRecurringCheckbox:

    def test_check_adds_filter(self, driver, w, ctx):
        driver.get(_exp_url())
        time.sleep(0.5)
        _set_search(driver, "")
        _click_checkbox(driver)
        assert "recurring=no" in _search_val(driver)
        assert _checkbox_checked(driver)

    def test_uncheck_removes_filter(self, driver, w, ctx):
        driver.get(_exp_url())
        time.sleep(0.5)
        _set_search(driver, "")
        _click_checkbox(driver)   # check
        _click_checkbox(driver)   # uncheck
        assert "recurring=" not in _search_val(driver)
        assert not _checkbox_checked(driver)

    def test_manual_no_checks_checkbox(self, driver, w, ctx):
        driver.get(_exp_url())
        time.sleep(0.5)
        _set_search(driver, "recurring=no")
        assert _checkbox_checked(driver)

    def test_manual_yes_unchecks_checkbox(self, driver, w, ctx):
        driver.get(_exp_url())
        time.sleep(0.5)
        _set_search(driver, "recurring=yes")
        assert not _checkbox_checked(driver)

    def test_manual_remove_unchecks_checkbox(self, driver, w, ctx):
        driver.get(_exp_url())
        time.sleep(0.5)
        _set_search(driver, "recurring=no")
        _set_search(driver, "")
        assert not _checkbox_checked(driver)

    def test_check_with_existing_query_no_leading_space(self, driver, w, ctx):
        driver.get(_exp_url())
        time.sleep(0.5)
        _set_search(driver, "coffee")
        _click_checkbox(driver)
        val = _search_val(driver)
        assert "coffee recurring=no" == val

    def test_uncheck_with_existing_query_leaves_rest(self, driver, w, ctx):
        driver.get(_exp_url())
        time.sleep(0.5)
        _set_search(driver, "coffee recurring=no")
        _click_checkbox(driver)   # uncheck
        assert _search_val(driver) == "coffee"

    def test_manual_no_with_existing_query_checks_checkbox(self, driver, w, ctx):
        driver.get(_exp_url())
        time.sleep(0.5)
        _set_search(driver, "coffee recurring=no")
        assert _checkbox_checked(driver)

    def test_manual_yes_with_existing_query_unchecks_checkbox(self, driver, w, ctx):
        driver.get(_exp_url())
        time.sleep(0.5)
        _set_search(driver, "coffee recurring=yes")
        assert not _checkbox_checked(driver)


def _shell(code: str) -> str:
    return run_cmd("shell", "-c", code)


class TestBuddyFilter:

    def test_setup(self, driver, w, ctx):
        today = server_today()
        year, month, day = today.split("-")
        ctx["qp_buddy_year"] = year

        # Regular non-buddy expense for contrast
        r = api_post("/api/v1/expenses/", ctx, json={
            "title": "QP NoBuddy", "type": "expense", "value": "10.00",
            "date_due": today,
        })
        assert r.status_code == 201
        ctx["qp_no_buddy_uid"] = r.json()["id"]

        # Group with two dummies: one is a participant, one is just a member
        group_pk = _shell(
            f"from buddies.services import ProjectService; "
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{ctx['email']}'); "
            f"g = ProjectService.create_group(u, 'QPBuddyGroup'); "
            f"print(g.pk)"
        )
        ctx["qp_buddy_group_pk"] = group_pk.strip()

        expense_pk = _shell(
            f"from budget.models import Expense; "
            f"from buddies.models import Project, ProjectMember, BuddySpending, DummyUser; "
            f"from feusers.models import FeUser; "
            f"from decimal import Decimal; import datetime; "
            f"u = FeUser.objects.get(email='{ctx['email']}'); "
            f"g = Project.objects.get(pk={group_pk.strip()}); "
            f"participant = DummyUser.objects.create(owning_group=g, display_name='QPParticipant'); "
            f"ProjectMember.objects.get_or_create(group=g, dummy=participant); "
            f"member_only = DummyUser.objects.create(owning_group=g, display_name='QPMemberOnly'); "
            f"ProjectMember.objects.get_or_create(group=g, dummy=member_only); "
            f"e = Expense.objects.create(owning_feuser=u, title='QP BuddyExpense', "
            f"  type='expense', value=Decimal('50.00'), settled=False, "
            f"  buddy_approved=True, project=g, "
            f"  date_due=datetime.date({int(year)}, {int(month)}, {int(day)})); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=participant, "
            f"  share_percent=Decimal('50.0')); "
            f"print(e.pk)"
        )
        ctx["qp_buddy_expense_pk"] = expense_pk.strip()

    def _titles(self, ctx, q):
        resp = api_get("/api/v1/expenses/", ctx, params={
            "q": q, "view": "year", "year": ctx["qp_buddy_year"],
        })
        return [e["title"] for e in resp.json()["expenses"]]

    def test_buddy_yes_includes_buddy_expense(self, driver, w, ctx):
        assert "QP BuddyExpense" in self._titles(ctx, "shared=yes")

    def test_buddy_yes_excludes_non_buddy(self, driver, w, ctx):
        assert "QP NoBuddy" not in self._titles(ctx, "shared=yes")

    def test_buddy_no_includes_non_buddy(self, driver, w, ctx):
        assert "QP NoBuddy" in self._titles(ctx, "shared=no")

    def test_buddy_no_excludes_buddy_expense(self, driver, w, ctx):
        assert "QP BuddyExpense" not in self._titles(ctx, "shared=no")

    def test_buddy_group_name_match(self, driver, w, ctx):
        assert "QP BuddyExpense" in self._titles(ctx, "QPBuddyGroup")

    def test_buddy_participant_name_match(self, driver, w, ctx):
        assert "QP BuddyExpense" in self._titles(ctx, "QPParticipant")

    def test_buddy_group_member_only_name_match(self, driver, w, ctx):
        # QPMemberOnly is in the group but not a BuddySpending participant
        assert "QP BuddyExpense" in self._titles(ctx, "QPMemberOnly")

    def test_buddy_name_excludes_non_buddy(self, driver, w, ctx):
        assert "QP NoBuddy" not in self._titles(ctx, "QPBuddyGroup")

    def test_freetext_participant_name(self, driver, w, ctx):
        assert "QP BuddyExpense" in self._titles(ctx, "QPParticipant")

    def test_freetext_group_name(self, driver, w, ctx):
        assert "QP BuddyExpense" in self._titles(ctx, "QPBuddyGroup")

    def test_freetext_does_not_bleed_into_non_buddy(self, driver, w, ctx):
        assert "QP NoBuddy" not in self._titles(ctx, "QPBuddyGroup")

    def test_cleanup(self, driver, w, ctx):
        if "qp_no_buddy_uid" in ctx:
            api_delete(f"/api/v1/expenses/{ctx.pop('qp_no_buddy_uid')}/", ctx)
        if "qp_buddy_expense_pk" in ctx:
            _shell(
                f"from budget.models import Expense; "
                f"Expense.objects.filter(pk={ctx.pop('qp_buddy_expense_pk')}).delete()"
            )
        if "qp_buddy_group_pk" in ctx:
            _shell(
                f"from buddies.models import Project; "
                f"Project.objects.filter(pk={ctx.pop('qp_buddy_group_pk')}).delete()"
            )
        ctx.pop("qp_buddy_year", None)
