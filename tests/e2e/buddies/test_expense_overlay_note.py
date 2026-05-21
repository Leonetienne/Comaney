"""
Tests for overlay note field semantics.

overlay.note == None  ->  participant inherits expense.note (fall-through)
overlay.note == text  ->  participant has their own note

[N1] Saving a note in the lite editor stores it on the overlay (not null).
[N2] Submitting an empty note stores None (not empty string).
[N3] After clearing the note field, overlay.note is None; if category/tags
     also empty the overlay is deleted entirely.
[N4] Overlay with only a note (no category/tags) is kept (not treated as empty).
[N5] upsert_overlay: whitespace-only note is stored as None.
"""
import pytest

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as, _create_buddy_link, _get_pk


# ---------------------------------------------------------------------------
# Shell helpers
# ---------------------------------------------------------------------------

def _mk_category(email: str, title: str) -> int:
    return int(_shell(
        f"from feusers.models import FeUser; from budget.models import Category; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"c, _ = Category.objects.get_or_create(owning_feuser=u, title='{title}'); print(c.pk)"
    ))


def _overlay_note(expense_pk: int, email: str) -> str | None:
    """Return overlay.note as string, or '__NULL__' when None."""
    raw = _shell(
        f"from feusers.models import FeUser; from budget.models import ExpenseDataOverlay; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"o = ExpenseDataOverlay.objects.filter(expense_id={expense_pk}, feuser=u).first(); "
        f"print('__NULL__' if o is None or o.note is None else repr(o.note))"
    )
    if raw == "__NULL__":
        return None
    return raw.strip("'\"")


def _overlay_exists(expense_pk: int, email: str) -> bool:
    return _shell(
        f"from feusers.models import FeUser; from budget.models import ExpenseDataOverlay; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"print(ExpenseDataOverlay.objects.filter(expense_id={expense_pk}, feuser=u).exists())"
    ).strip() == "True"


def _create_buddy_expense(owner_email: str, participant_pk: int, title: str = "Note Exp") -> int:
    return int(_shell(
        f"from feusers.models import FeUser; from budget.models import Expense; "
        f"from buddies.models import BuddySpending; from decimal import Decimal; "
        f"o = FeUser.objects.get(email='{owner_email}'); "
        f"e = Expense.objects.create(owning_feuser=o, title='{title}', "
        f"  type='expense', value='50.00', settled=False, "
        f"  note='Original expense note.'); "
        f"BuddySpending.objects.create(expense=e, participant_feuser_id={participant_pk}, "
        f"  share_percent=Decimal('50')); print(e.pk)"
    ))


# ===========================================================================
# N1: Saving a note stores it on the overlay
# ===========================================================================

class TestOverlayNoteStored:
    """[N1] A note submitted via the lite editor is persisted on the overlay."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        owner = setup_user(driver, w, first_name="NoteOwn", last_name="A")
        part  = setup_user(None, None, first_name="NotePart", last_name="A")
        _create_buddy_link(owner["email"], part["email"])
        part_pk = int(_get_pk(part["email"]))
        cat_pk  = _mk_category(part["email"], "NoteTestCat")
        exp_pk  = _create_buddy_expense(owner["email"], part_pk, "N1 Expense")
        yield {"owner": owner, "part": part, "exp_pk": exp_pk, "cat_pk": cat_pk}
        cleanup_user(owner["email"])
        cleanup_user(part["email"])

    def test_note_saved_via_form(self, driver, w, ctx):
        _login_as(driver, ctx["part"])
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit-overlay/"))
        import time; time.sleep(1)
        driver.execute_script(
            f"document.getElementById('id_category').value = '{ctx['cat_pk']}';"
        )
        driver.execute_script(
            "document.getElementById('id_note').value = 'My personal note.';"
        )
        from selenium.webdriver.common.by import By
        driver.find_element(By.CSS_SELECTOR, ".form-wrap button[type=submit]").click()
        time.sleep(1)
        assert _overlay_note(ctx["exp_pk"], ctx["part"]["email"]) == "My personal note.", \
            "[N1] Note must be stored on overlay after form submit"

    def test_overlay_note_is_not_null(self, ctx):
        note = _overlay_note(ctx["exp_pk"], ctx["part"]["email"])
        assert note is not None, "[N1] Overlay note must not be None when text was saved"


# ===========================================================================
# N2: Empty note is stored as None
# ===========================================================================

class TestEmptyNoteIsNull:
    """[N2] Submitting with an empty note field results in overlay.note == None."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        owner = setup_user(driver, w, first_name="NullNote", last_name="Own")
        part  = setup_user(None, None, first_name="NullNote", last_name="Part")
        _create_buddy_link(owner["email"], part["email"])
        part_pk = int(_get_pk(part["email"]))
        cat_pk  = _mk_category(part["email"], "NullNoteCat")
        exp_pk  = _create_buddy_expense(owner["email"], part_pk, "N2 Expense")
        # Pre-create overlay with a note
        _shell(
            f"from feusers.models import FeUser; from budget.models import ExpenseDataOverlay, Category; "
            f"u = FeUser.objects.get(email='{part['email']}'); "
            f"c = Category.objects.get(pk={cat_pk}); "
            f"ExpenseDataOverlay.objects.create(expense_id={exp_pk}, feuser=u, "
            f"  category=c, note='Will be cleared')"
        )
        yield {"owner": owner, "part": part, "exp_pk": exp_pk, "cat_pk": cat_pk}
        cleanup_user(owner["email"])
        cleanup_user(part["email"])

    def test_empty_note_submit_stores_none(self, driver, w, ctx):
        _login_as(driver, ctx["part"])
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit-overlay/"))
        import time; time.sleep(1)
        from selenium.webdriver.common.by import By
        # Keep category, clear note
        driver.execute_script(
            f"document.getElementById('id_category').value = '{ctx['cat_pk']}';"
        )
        driver.execute_script("document.getElementById('id_note').value = '';")
        driver.find_element(By.CSS_SELECTOR, ".form-wrap button[type=submit]").click()
        time.sleep(1)
        assert _overlay_note(ctx["exp_pk"], ctx["part"]["email"]) is None, \
            "[N2] Submitting empty note must store None on overlay"

    def test_overlay_still_exists_when_category_set(self, ctx):
        assert _overlay_exists(ctx["exp_pk"], ctx["part"]["email"]), \
            "[N2] Overlay must not be deleted when category is still set"


# ===========================================================================
# N3: Clearing note + no category/tags deletes the overlay
# ===========================================================================

class TestClearNoteDeletesOverlayWhenAllEmpty:
    """[N3] When note, category, and tags are all empty, overlay is deleted."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        owner = setup_user(driver, w, first_name="DelOv", last_name="Own")
        part  = setup_user(None, None, first_name="DelOv", last_name="Part")
        _create_buddy_link(owner["email"], part["email"])
        part_pk = int(_get_pk(part["email"]))
        exp_pk  = _create_buddy_expense(owner["email"], part_pk, "N3 Expense")
        # Overlay with only a note (no category, no tags)
        _shell(
            f"from feusers.models import FeUser; from budget.models import ExpenseDataOverlay; "
            f"u = FeUser.objects.get(email='{part['email']}'); "
            f"ExpenseDataOverlay.objects.create(expense_id={exp_pk}, feuser=u, note='Solo note')"
        )
        yield {"owner": owner, "part": part, "exp_pk": exp_pk}
        cleanup_user(owner["email"])
        cleanup_user(part["email"])

    def test_overlay_exists_before_clear(self, ctx):
        assert _overlay_exists(ctx["exp_pk"], ctx["part"]["email"]), \
            "[N3] Overlay with only a note must exist before clearing"

    def test_empty_submit_deletes_overlay(self, driver, w, ctx):
        _login_as(driver, ctx["part"])
        driver.get(_url(f"/budget/expenses/{ctx['exp_pk']}/edit-overlay/"))
        import time; time.sleep(1)
        from selenium.webdriver.common.by import By
        driver.execute_script("document.getElementById('id_note').value = '';")
        driver.execute_script("document.getElementById('id_category').value = '';")
        driver.execute_script(
            "document.querySelectorAll('#id_tags input[type=checkbox]')"
            ".forEach(cb => cb.checked = false);"
        )
        driver.find_element(By.CSS_SELECTOR, ".form-wrap button[type=submit]").click()
        time.sleep(1)
        assert not _overlay_exists(ctx["exp_pk"], ctx["part"]["email"]), \
            "[N3] Overlay must be deleted when note, category, and tags are all empty"


# ===========================================================================
# N4: Overlay with only a note is kept (not treated as empty)
# ===========================================================================

class TestOverlayWithOnlyNoteKept:
    """[N4] An overlay that has only a note and no category/tags is not deleted."""

    def test_overlay_note_only_is_kept(self):
        result = _shell(
            "from budget.services import upsert_overlay; "
            "from budget.models import Expense, ExpenseDataOverlay; "
            "from feusers.models import FeUser; "
            "from decimal import Decimal; "
            "u = FeUser.objects.first(); "
            "e = Expense.objects.create(owning_feuser=u, title='N4 tmp', "
            "  type='expense', value=Decimal('10'), settled=True); "
            "o = upsert_overlay(e, u, None, [], note='Only a note'); "
            "print('kept' if o is not None else 'deleted'); "
            "e.delete()"
        )
        assert result == "kept", \
            "[N4] upsert_overlay must keep overlay when it has only a note"


# ===========================================================================
# N5: Whitespace-only note is stored as None
# ===========================================================================

class TestWhitespaceNoteIsNull:
    """[N5] upsert_overlay treats whitespace-only note as None."""

    def test_whitespace_note_stored_as_none(self):
        result = _shell(
            "from budget.services import upsert_overlay; "
            "from budget.models import Expense, ExpenseDataOverlay, Category; "
            "from feusers.models import FeUser; "
            "from decimal import Decimal; "
            "u = FeUser.objects.first(); "
            "cat, _ = Category.objects.get_or_create(owning_feuser=u, title='_N5Cat'); "
            "e = Expense.objects.create(owning_feuser=u, title='N5 tmp', "
            "  type='expense', value=Decimal('10'), settled=True); "
            "o = upsert_overlay(e, u, cat, [], note='   '); "
            "print('null' if o.note is None else 'not_null'); "
            "e.delete()"
        )
        assert result == "null", \
            "[N5] Whitespace-only note must be stored as None"
