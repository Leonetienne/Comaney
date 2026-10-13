"""
Partnership onboarding apply: the invitee's recurring expenses and expense
overlays keep their tags and category, remapped like their own expenses.
Requirement: req~partnership.wizard.apply~2 (specs/requirements/partnership.md).
Run with: pytest tests/e2e/partnerships/test_partnership_onboarding_records.py -v | tee logfile.log
"""
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as, _create_buddy_link, _get_pk, _create_personal_expense_with_buddy


def _create_invite_via_shell(inviter_email: str, invitee_email: str) -> str:
    return _shell(
        "from feusers.models import FeUser; "
        "from buddies.models import CatalogPartnership, CatalogPartnershipMembership, CatalogPartnershipInvite; "
        f"inviter = FeUser.objects.get(email='{inviter_email}'); "
        f"invitee = FeUser.objects.get(email='{invitee_email}'); "
        "p = CatalogPartnership.objects.create(); "
        "CatalogPartnershipMembership.objects.create(partnership=p, feuser=inviter, onboarding_complete=True); "
        "inv = CatalogPartnershipInvite.objects.create(partnership=p, inviter=inviter, invitee_email=invitee.email); "
        "print(inv.token)"
    )


def _add_catalog(email: str, tags: list[str], cats: list[str]) -> None:
    _shell(
        "from feusers.models import FeUser; from budget.models import Tag, Category; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"[Tag.objects.get_or_create(owning_feuser=u, title=t) for t in {tags!r}]; "
        f"[Category.objects.get_or_create(owning_feuser=u, title=c) for c in {cats!r}]"
    )


def _create_scheduled(email: str, tags: list[str], cat: str) -> str:
    return _shell(
        "from feusers.models import FeUser; from budget.models import ScheduledExpense, Tag, Category; "
        "from decimal import Decimal; import datetime; "
        f"u = FeUser.objects.get(email='{email}'); "
        "s = ScheduledExpense.objects.create(owning_feuser=u, title='Gym', type='expense', "
        "  value=Decimal('30.00'), repeat_base_date=datetime.date(2026, 1, 1), "
        "  repeat_every_factor=1, repeat_every_unit='months', "
        f"  category=Category.objects.get(owning_feuser=u, title='{cat}')); "
        f"s.tags.set(Tag.objects.filter(owning_feuser=u, title__in={tags!r})); "
        "print(s.pk)"
    )


def _create_own_expense(email: str, tags: list[str]) -> str:
    return _shell(
        "from feusers.models import FeUser; from budget.models import Expense, Tag; "
        "from decimal import Decimal; "
        f"u = FeUser.objects.get(email='{email}'); "
        "e = Expense.objects.create(owning_feuser=u, title='Own', type='expense', value=Decimal('5.00')); "
        f"e.tags.set(Tag.objects.filter(owning_feuser=u, title__in={tags!r})); "
        "print(e.pk)"
    )


def _create_overlay(email: str, expense_uid: str, tags: list[str], cat: str | None) -> None:
    cat_arg = f"Category.objects.get(owning_feuser=u, title='{cat}')" if cat else "None"
    _shell(
        "from feusers.models import FeUser; from budget.models import ExpenseDataOverlay, Tag, Category; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"o = ExpenseDataOverlay.objects.create(expense_id={expense_uid}, feuser=u, category={cat_arg}); "
        f"o.tags.set(Tag.objects.filter(owning_feuser=u, title__in={tags!r}))"
    )


def _labels(model: str, lookup: str, owner_email: str) -> tuple[str, list[str], bool]:
    """(category title, sorted tag titles, all labels owned by owner) of one record."""
    out = _shell(
        "from feusers.models import FeUser; "
        f"from budget.models import {model}; "
        f"u = FeUser.objects.get(email='{owner_email}'); "
        f"r = {model}.objects.get({lookup}); "
        "labels = list(r.tags.all()) + ([r.category] if r.category else []); "
        "print(r.category.title if r.category else '', '|', ','.join(sorted(t.title for t in r.tags.all())), "
        "      '|', all(l.owning_feuser_id == u.pk for l in labels))"
    )
    cat, tags, owned = (p.strip() for p in out.split("|"))
    return cat, [t for t in tags.split(",") if t], owned == "True"


class TestOnboardingRemapsRecurringAndOverlays:
    """B maps booze_pm -> drinks_pm, drops junk_pm, maps snacks_pm -> food_pm and applies."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(None, None, first_name="Gina", last_name="Remap")
        b = setup_user(driver, w, first_name="Hank", last_name="Remap")
        _create_buddy_link(a["email"], b["email"])
        _add_catalog(a["email"], ["drinks_pm", "coffee_pm"], ["food_pm"])
        _add_catalog(b["email"], ["booze_pm", "coffee_pm", "junk_pm"], ["snacks_pm"])

        scheduled = _create_scheduled(b["email"], ["booze_pm", "coffee_pm", "junk_pm"], "snacks_pm")
        own = _create_own_expense(b["email"], ["booze_pm"])
        b_pk = int(_get_pk(b["email"]))
        shared = _create_personal_expense_with_buddy(a["email"], b_pk, title="Shared dinner")
        _create_overlay(b["email"], shared, ["booze_pm", "coffee_pm"], "snacks_pm")
        dropped_only = _create_personal_expense_with_buddy(a["email"], b_pk, title="Shared junk")
        _create_overlay(b["email"], dropped_only, ["junk_pm"], None)

        token = _create_invite_via_shell(a["email"], b["email"])
        yield {"a": a, "b": b, "token": token, "scheduled": scheduled, "own": own,
               "shared": shared, "dropped_only": dropped_only}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_complete_wizard(self, driver, w, ctx):
        _login_as(driver, ctx["b"])
        driver.get(_url(f"/buddies/partnership/accept/{ctx['token']}/"))
        time.sleep(1.5)
        driver.find_element(By.ID, "step1-next").click()
        time.sleep(0.8)

        Select(driver.find_element(
            By.CSS_SELECTOR, "#step-2 select.wizard-map-select[data-source='booze_pm']"
        )).select_by_value("drinks_pm")
        driver.find_element(
            By.CSS_SELECTOR, "#step-2 .wizard-map-drop input[data-source='junk_pm']"
        ).click()
        time.sleep(0.3)
        driver.find_element(By.ID, "step2-next").click()
        time.sleep(0.8)

        Select(driver.find_element(
            By.CSS_SELECTOR, "#step-3 select.wizard-map-select[data-source='snacks_pm']"
        )).select_by_value("food_pm")
        time.sleep(0.3)
        driver.find_element(By.ID, "step3-next").click()
        time.sleep(0.8)

        driver.find_element(By.ID, "step4-apply").click()
        time.sleep(3)
        assert "/budget/categories" in driver.current_url

    def test_own_expense_remapped(self, driver, w, ctx):
        cat, tags, owned = _labels("Expense", f"pk={ctx['own']}", ctx["b"]["email"])
        assert tags == ["drinks_pm"]
        assert owned

    def test_recurring_expense_remapped(self, driver, w, ctx):
        cat, tags, owned = _labels("ScheduledExpense", f"pk={ctx['scheduled']}", ctx["b"]["email"])
        assert cat == "food_pm"
        assert tags == ["coffee_pm", "drinks_pm"]
        assert owned, "Recurring expense labels must belong to the invitee's new catalog"

    def test_overlay_remapped(self, driver, w, ctx):
        b_pk = _get_pk(ctx["b"]["email"])
        cat, tags, owned = _labels(
            "ExpenseDataOverlay", f"expense_id={ctx['shared']}, feuser_id={b_pk}", ctx["b"]["email"],
        )
        assert cat == "food_pm"
        assert tags == ["coffee_pm", "drinks_pm"]
        assert owned, "Overlay labels must belong to the invitee's new catalog"

    def test_overlay_left_empty_is_deleted(self, driver, w, ctx):
        b_pk = _get_pk(ctx["b"]["email"])
        count = _shell(
            "from budget.models import ExpenseDataOverlay; "
            f"print(ExpenseDataOverlay.objects.filter(expense_id={ctx['dropped_only']}, feuser_id={b_pk}).count())"
        )
        assert count == "0", "An overlay whose only tag was dropped must not remain stored empty"
