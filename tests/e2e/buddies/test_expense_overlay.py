"""
Tests for participant expense data overlays.

Participants in a buddy expense can set their own category/tags via the
lite editor (edit-overlay). Owners use the full editor; the overlay editor
is only for non-owner participants.

[O1] Direct buddy: participant sees Edit (lite) button, owner does not.
[O2] Group expense: participant sees Edit (lite) button, owner does not.
[O3] Lite editor loads and saves category/tag selection.
[O4] Clearing the overlay (empty submit) deletes it from DB.
[O5] Overlay edit button absent for settlements.
[O6] Lite editor shows the owner's original category, tags, and note.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import (
    _shell, _login_as, _create_buddy_link, _get_pk,
    _create_group, _add_group_member, _create_group_expense,
    _create_personal_expense_with_buddy,
)


def _create_category(email: str, title: str) -> str:
    return _shell(
        f"from feusers.models import FeUser; from budget.models import Category; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"c, _ = Category.objects.get_or_create(owning_feuser=u, title='{title}'); "
        f"print(c.pk)"
    )


def _create_tag(email: str, title: str) -> str:
    return _shell(
        f"from feusers.models import FeUser; from budget.models import Tag; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"t, _ = Tag.objects.get_or_create(owning_feuser=u, title='{title}'); "
        f"print(t.pk)"
    )


def _overlay_exists(expense_pk: int, email: str) -> bool:
    result = _shell(
        f"from feusers.models import FeUser; from budget.models import ExpenseDataOverlay; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"print(ExpenseDataOverlay.objects.filter(expense_id={expense_pk}, feuser=u).exists())"
    )
    return result.strip() == "True"


# ===========================================================================
# O1: Direct buddy -- participant sees Edit lite, owner does not
# ===========================================================================

class TestDirectBuddyOverlayButton:
    """[O1] Participant sees data-edit='lite' button; owner sees data-edit='full' only."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        owner = setup_user(driver, w, first_name="Olive", last_name="Owner")
        part = setup_user(None, None, first_name="Pete", last_name="Part")
        _create_buddy_link(owner["email"], part["email"])
        part_pk = int(_get_pk(part["email"]))
        exp_pk = int(_create_personal_expense_with_buddy(
            owner["email"], part_pk, title="Olive Direct Exp",
        ))
        yield {"owner": owner, "part": part, "exp_pk": exp_pk}
        cleanup_user(owner["email"])
        cleanup_user(part["email"])

    def test_participant_sees_lite_button(self, driver, w, ctx):
        _login_as(driver, ctx["part"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit-overlay/" in driver.page_source, \
            "[O1] Participant must see edit-overlay link"

    def test_participant_does_not_see_full_button(self, driver, w, ctx):
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" not in driver.page_source, \
            "[O1] Participant must not see full edit link for owner's expense"

    def test_owner_sees_full_button_not_lite(self, driver, w, ctx):
        _login_as(driver, ctx["owner"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit/" in driver.page_source, \
            "[O1] Owner must see full edit link"
        assert f"/budget/expenses/{ctx['exp_pk']}/edit-overlay/" not in driver.page_source, \
            "[O1] Owner must not see edit-overlay link"


# ===========================================================================
# O2: Group expense -- participant sees Edit lite, owner does not
# ===========================================================================

class TestGroupExpenseOverlayButton:
    """[O2] In group view: participant sees data-edit='lite', owner sees data-edit='full'."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Greta", last_name="GrpAdmin")
        member = setup_user(None, None, first_name="Max", last_name="GrpMember")
        gid = int(_create_group(admin["email"], "Overlay Test Group"))
        _add_group_member(gid, member["email"])
        exp_pk = int(_create_group_expense(
            admin["email"], member["email"], gid, title="Group Overlay Exp",
        ))
        yield {"admin": admin, "member": member, "gid": gid, "exp_pk": exp_pk}
        cleanup_user(admin["email"])
        cleanup_user(member["email"])

    def test_participant_sees_lite_button(self, driver, w, ctx):
        _login_as(driver, ctx["member"])
        driver.get(_url(f"/projects/{ctx['gid']}/"))
        time.sleep(2)
        links = driver.find_elements(By.CSS_SELECTOR, f"a[data-edit='lite']")
        matching = [l for l in links if str(ctx["exp_pk"]) in (l.get_attribute("href") or "")]
        assert matching, "[O2] Member must see edit-lite button for group expense"

    def test_owner_sees_full_not_lite(self, driver, w, ctx):
        _login_as(driver, ctx["admin"])
        driver.get(_url(f"/projects/{ctx['gid']}/"))
        time.sleep(2)
        lite = driver.find_elements(By.CSS_SELECTOR, f"a[data-edit='lite']")
        matching_lite = [l for l in lite if str(ctx["exp_pk"]) in (l.get_attribute("href") or "")]
        assert not matching_lite, "[O2] Owner must not see edit-lite button for their own expense"
        full = driver.find_elements(By.CSS_SELECTOR, f"a[data-edit='full']")
        matching_full = [l for l in full if str(ctx["exp_pk"]) in (l.get_attribute("href") or "")]
        assert matching_full, "[O2] Owner must see full edit button"


# ===========================================================================
# O3: Lite editor loads and saves overlay
# ===========================================================================

class TestOverlayEditorSave:
    """[O3] Lite editor: participant can set category/tags; overlay is created in DB."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        owner = setup_user(driver, w, first_name="Sara", last_name="OvOwner")
        part = setup_user(None, None, first_name="Bob", last_name="OvPart")
        _create_buddy_link(owner["email"], part["email"])
        part_pk = int(_get_pk(part["email"]))
        exp_pk = int(_create_personal_expense_with_buddy(
            owner["email"], part_pk, title="Overlay Save Exp",
        ))
        cat_pk = int(_create_category(part["email"], "OvCat"))
        tag_pk = int(_create_tag(part["email"], "OvTag"))
        yield {
            "owner": owner, "part": part,
            "exp_pk": exp_pk, "cat_pk": cat_pk, "tag_pk": tag_pk,
        }
        cleanup_user(owner["email"])
        cleanup_user(part["email"])

    def test_edit_overlay_page_loads(self, driver, w, ctx):
        _login_as(driver, ctx["part"])
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit-overlay/"))
        time.sleep(1)
        assert "edit-overlay" in driver.current_url, \
            "[O3] Lite editor must load for participant"
        assert "My tags" in driver.page_source or "category" in driver.page_source.lower(), \
            "[O3] Lite editor must show category/tags form"

    def test_save_overlay_creates_db_entry(self, driver, w, ctx):
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit-overlay/"))
        time.sleep(1)
        # Select the category
        driver.execute_script(
            f"document.getElementById('id_category').value = '{ctx['cat_pk']}';"
        )
        # Check the tag checkbox
        tag_pk = ctx["tag_pk"]
        driver.execute_script(
            f"var cb = document.querySelector('input[value=\"{tag_pk}\"]'); "
            f"if(cb) cb.checked = true;"
        )
        driver.find_element(By.CSS_SELECTOR, ".form-wrap button[type=submit]").click()
        time.sleep(1)
        assert _overlay_exists(ctx["exp_pk"], ctx["part"]["email"]), \
            "[O3] Overlay must exist in DB after saving"

    def test_owner_cannot_access_overlay_editor(self, driver, w, ctx):
        _login_as(driver, ctx["owner"])
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit-overlay/"))
        time.sleep(1)
        assert driver.find_elements(By.CSS_SELECTOR, ".form-wrap button[type=submit]") == [], \
            "[O3] Owner must not see the overlay form (404)"


# ===========================================================================
# O4: Empty submit deletes overlay
# ===========================================================================

class TestOverlayClear:
    """[O4] Submitting with no category and no tags removes the overlay from DB."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        owner = setup_user(driver, w, first_name="Clara", last_name="ClrOwner")
        part = setup_user(None, None, first_name="Dan", last_name="ClrPart")
        _create_buddy_link(owner["email"], part["email"])
        part_pk = int(_get_pk(part["email"]))
        exp_pk = int(_create_personal_expense_with_buddy(
            owner["email"], part_pk, title="Clear Overlay Exp",
        ))
        cat_pk = int(_create_category(part["email"], "ClrCat"))
        # Pre-create an overlay via shell
        _shell(
            f"from feusers.models import FeUser; from budget.models import ExpenseDataOverlay, Category; "
            f"u = FeUser.objects.get(email='{part['email']}'); "
            f"c = Category.objects.get(pk={cat_pk}); "
            f"ExpenseDataOverlay.objects.create(expense_id={exp_pk}, feuser=u, category=c)"
        )
        yield {"owner": owner, "part": part, "exp_pk": exp_pk}
        cleanup_user(owner["email"])
        cleanup_user(part["email"])

    def test_overlay_exists_before_clear(self, ctx):
        assert _overlay_exists(ctx["exp_pk"], ctx["part"]["email"]), \
            "[O4] Overlay must exist before clearing"

    def test_empty_submit_removes_overlay(self, driver, w, ctx):
        _login_as(driver, ctx["part"])
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit-overlay/"))
        time.sleep(1)
        # Deselect category (set to empty)
        driver.execute_script("document.getElementById('id_category').value = '';")
        # Uncheck all tag checkboxes
        driver.execute_script(
            "document.querySelectorAll('#id_tags input[type=checkbox]')"
            ".forEach(cb => cb.checked = false);"
        )
        driver.find_element(By.CSS_SELECTOR, ".form-wrap button[type=submit]").click()
        time.sleep(1)
        assert not _overlay_exists(ctx["exp_pk"], ctx["part"]["email"]), \
            "[O4] Overlay must be deleted when saved empty"


# ===========================================================================
# O5: No overlay edit button on settlements
# ===========================================================================

class TestNoOverlayOnSettlements:
    """[O5] Settlements do not get an edit-lite button for participants."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        debtor = setup_user(driver, w, first_name="Seth", last_name="Debtor")
        creditor = setup_user(None, None, first_name="Seth", last_name="Creditor")
        _create_buddy_link(debtor["email"], creditor["email"])
        creditor_pk = int(_get_pk(creditor["email"]))
        # Create a settlement expense (debtor owes creditor)
        exp_pk = _shell(
            f"from feusers.models import FeUser; from budget.models import Expense; "
            f"from buddies.models import BuddySpending; from decimal import Decimal; "
            f"d = FeUser.objects.get(email='{debtor['email']}'); "
            f"c = FeUser.objects.get(pk={creditor_pk}); "
            f"e = Expense.objects.create(owning_feuser=d, title='Settlement O5', "
            f"  type='expense', value=Decimal('40.00'), settled=True, "
            f"  is_buddies_settlement=True, buddy_approved=False); "
            f"BuddySpending.objects.create(expense=e, participant_feuser=c, "
            f"  share_percent=Decimal('100')); "
            f"print(e.pk)"
        )
        yield {"debtor": debtor, "creditor": creditor, "exp_pk": int(exp_pk)}
        cleanup_user(debtor["email"])
        cleanup_user(creditor["email"])

    def test_no_edit_lite_button_for_settlement_creditor(self, driver, w, ctx):
        _login_as(driver, ctx["creditor"])
        driver.get(_url("/buddies/summary/"))
        time.sleep(2)
        assert f"/budget/expenses/{ctx['exp_pk']}/edit-overlay/" not in driver.page_source, \
            "[O5] Settlement creditor must not see edit-overlay button"


# ===========================================================================
# O6: Lite editor shows owner's original category, tags, and note
# ===========================================================================

class TestOverlayShowsOriginalValues:
    """[O6] The lite editor displays the expense owner's original category, tags, and note."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        owner = setup_user(driver, w, first_name="Orig", last_name="Owner")
        part  = setup_user(None, None, first_name="Orig", last_name="Part")
        _create_buddy_link(owner["email"], part["email"])
        part_pk = int(_get_pk(part["email"]))
        cat_pk = int(_create_category(owner["email"], "OrigCatElectronics"))
        tag_pk = int(_create_tag(owner["email"], "OrigTagWork"))
        exp_pk = int(_shell(
            f"from feusers.models import FeUser; from budget.models import Expense, Category, Tag; "
            f"from buddies.models import BuddySpending; from decimal import Decimal; "
            f"o = FeUser.objects.get(email='{owner['email']}'); "
            f"cat = Category.objects.get(pk={cat_pk}); "
            f"tag = Tag.objects.get(pk={tag_pk}); "
            f"e = Expense.objects.create(owning_feuser=o, title='O6 Orig Exp', "
            f"  type='expense', value=Decimal('60.00'), settled=False, "
            f"  note='Original owner note.', category=cat); "
            f"e.tags.set([tag]); "
            f"BuddySpending.objects.create(expense=e, participant_feuser_id={part_pk}, "
            f"  share_percent=Decimal('50')); "
            f"print(e.pk)"
        ))
        yield {"owner": owner, "part": part, "exp_pk": exp_pk}
        cleanup_user(owner["email"])
        cleanup_user(part["email"])

    def test_original_category_shown(self, driver, w, ctx):
        _login_as(driver, ctx["part"])
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit-overlay/"))
        time.sleep(1)
        assert "OrigCatElectronics" in driver.page_source, \
            "[O6] Lite editor must show the owner's original category"

    def test_original_tag_shown(self, driver, w, ctx):
        assert "OrigTagWork" in driver.page_source, \
            "[O6] Lite editor must show the owner's original tag"

    def test_original_note_shown(self, driver, w, ctx):
        assert "Original owner note." in driver.page_source, \
            "[O6] Lite editor must show the owner's original note"
