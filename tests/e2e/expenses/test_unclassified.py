"""
Unclassified Expenses page.

Run with: pytest tests/e2e/expenses/test_unclassified.py -v | tee logfile.log

AI-dependent tests skip gracefully (like tests/e2e/express/test_express.py)
when no usable AI key is configured, rather than hard-failing on missing
infrastructure.
"""
import subprocess
import time

import pytest
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from helpers import DOCKER_WEB, _url, cleanup_user, session_cookies, setup_user


def _shell(code: str) -> str:
    r = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c", code],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, f"Shell failed:\n{r.stderr}"
    return r.stdout.strip()


def _create_expense(email, title, *, category=None, tag_titles=None, payee="", type="expense"):
    tag_titles = tag_titles or []
    code = (
        "from feusers.models import FeUser\n"
        "from budget.models import Category, Tag\n"
        "from budget.expense_factory import create_expense\n"
        "from decimal import Decimal\n"
        f"u = FeUser.objects.get(email={email!r})\n"
        "cat = None\n"
        f"if {category!r}:\n"
        f"    cat, _ = Category.objects.get_or_create(owning_feuser=u, title={category!r})\n"
        f"tags = [Tag.objects.get_or_create(owning_feuser=u, title=t)[0] for t in {tag_titles!r}]\n"
        f"e = create_expense(owning_feuser=u, title={title!r}, type={type!r}, "
        f"value=Decimal('9.99'), payee={payee!r}, category=cat, tags=tags)\n"
        "print(e.uid)\n"
    )
    return int(_shell(code))


def _create_foreign_expense(owner_email, participant_email, title, *, owner_category=None, owner_tag_titles=None):
    owner_tag_titles = owner_tag_titles or []
    code = (
        "from feusers.models import FeUser\n"
        "from budget.models import Category, Tag\n"
        "from budget.expense_factory import create_expense\n"
        "from decimal import Decimal\n"
        f"owner = FeUser.objects.get(email={owner_email!r})\n"
        f"participant = FeUser.objects.get(email={participant_email!r})\n"
        "cat = None\n"
        f"if {owner_category!r}:\n"
        f"    cat, _ = Category.objects.get_or_create(owning_feuser=owner, title={owner_category!r})\n"
        f"tags = [Tag.objects.get_or_create(owning_feuser=owner, title=t)[0] for t in {owner_tag_titles!r}]\n"
        f"e = create_expense(owning_feuser=owner, title={title!r}, type='expense', value=Decimal('40.00'), "
        "category=cat, tags=tags, "
        "buddy_spendings=[{'type': 'feuser', 'id': participant.pk, 'share_percent': Decimal('50')}])\n"
        "print(e.uid)\n"
    )
    return int(_shell(code))


def _overlay_count(email, expense_uid):
    return int(_shell(
        f"from feusers.models import FeUser\n"
        f"from budget.models import ExpenseDataOverlay\n"
        f"u = FeUser.objects.get(email={email!r})\n"
        f"print(ExpenseDataOverlay.objects.filter(expense_id={expense_uid}, feuser=u).count())"
    ))


def _overlay_values(email, expense_uid):
    out = _shell(
        f"from feusers.models import FeUser\n"
        f"from budget.models import ExpenseDataOverlay\n"
        f"u = FeUser.objects.get(email={email!r})\n"
        f"o = ExpenseDataOverlay.objects.get(expense_id={expense_uid}, feuser=u)\n"
        f"print(o.category.title if o.category else '', '|', ','.join(t.title for t in o.tags.all()))"
    )
    cat_part, _, tags_part = out.partition("|")
    return cat_part.strip(), [t for t in tags_part.strip().split(",") if t]


def _row(driver, uid):
    return driver.find_element(By.ID, f"unclassified-row-{uid}")


def _badge_count(driver) -> int:
    return driver.execute_script(
        "var link = document.querySelector('.sidebar a[href*=\"unclassified\"]');"
        "if (!link) return 0;"
        "var b = link.querySelector('.action-badge');"
        "return b ? parseInt(b.textContent, 10) : 0;"
    )


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestUnclassifiedExpensesList:

    def test_badge_and_list_show_correct_problems(self, driver, w, ctx):
        uid_cat = _create_expense(ctx["email"], "Missing cat only", tag_titles=["Alpha"])
        uid_tags = _create_expense(ctx["email"], "Missing tags only", category="Alpha Cat")
        uid_both = _create_expense(ctx["email"], "Missing both")
        uid_full = _create_expense(ctx["email"], "Fully classified", category="Alpha Cat", tag_titles=["Alpha"])

        driver.get(_url("/budget/"))
        time.sleep(1)
        assert _badge_count(driver) >= 3

        driver.get(_url("/budget/unclassified/"))
        time.sleep(1.5)

        assert "Category missing" in _row(driver, uid_cat).text
        assert "Tags missing" in _row(driver, uid_tags).text
        assert "Category and Tags missing" in _row(driver, uid_both).text
        assert len(driver.find_elements(By.ID, f"unclassified-row-{uid_full}")) == 0

    def test_savings_deposit_and_withdrawal_never_shown(self, driver, w, ctx):
        uid_dep = _create_expense(ctx["email"], "Savings deposit test", type="savings_dep")
        uid_wit = _create_expense(ctx["email"], "Savings withdrawal test", type="savings_wit")

        driver.get(_url("/budget/unclassified/"))
        time.sleep(1.5)

        assert len(driver.find_elements(By.ID, f"unclassified-row-{uid_dep}")) == 0
        assert len(driver.find_elements(By.ID, f"unclassified-row-{uid_wit}")) == 0

    def test_inline_category_select_and_save_removes_row(self, driver, w, ctx):
        _ensure_category(ctx, "Beta Cat")
        uid = _create_expense(ctx["email"], "Select category test", tag_titles=["Beta"])
        driver.get(_url("/budget/unclassified/"))
        time.sleep(1.5)

        row = _row(driver, uid)
        row.find_element(By.CSS_SELECTOR, "td[data-label='Category'] .unclassified-cell-view").click()
        time.sleep(0.5)

        select_el = row.find_element(By.CSS_SELECTOR, "select.unclassified-category-select")
        Select(select_el).select_by_visible_text("Beta Cat")
        time.sleep(0.5)

        save_btn = row.find_element(By.XPATH, ".//button[text()='Save']")
        assert save_btn.is_displayed()
        edit_btns = row.find_elements(By.XPATH, ".//button[text()='Edit']")
        assert not edit_btns or not edit_btns[0].is_displayed()
        save_btn.click()
        time.sleep(1.5)

        assert len(driver.find_elements(By.ID, f"unclassified-row-{uid}")) == 0

    def test_inline_tags_combobox_and_save_removes_row(self, driver, w, ctx):
        _ensure_tag(ctx, "Groceries")
        _ensure_tag(ctx, "Groceries Extra")
        uid = _create_expense(ctx["email"], "Tags combobox test", category="Gamma Cat")
        driver.get(_url("/budget/unclassified/"))
        time.sleep(1.5)

        row = _row(driver, uid)
        row.find_element(By.CSS_SELECTOR, "td[data-label='Tags'] .unclassified-cell-view").click()
        time.sleep(0.5)

        tag_input = row.find_element(By.CSS_SELECTOR, ".unclassified-tag-input")
        driver.execute_script(
            "arguments[0].value = arguments[1];"
            "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));",
            tag_input, "Grocer",
        )
        time.sleep(0.5)
        suggestion = row.find_element(
            By.XPATH, ".//div[contains(@class,'unclassified-tag-suggestion') and text()='Groceries']"
        )
        suggestion.click()
        time.sleep(0.3)

        pills = row.find_elements(By.CSS_SELECTOR, ".unclassified-tag-pill")
        assert len(pills) == 1

        # click outside to close the combobox
        driver.find_element(By.TAG_NAME, "h1").click()
        time.sleep(0.3)

        assert "Groceries" in row.find_element(By.CSS_SELECTOR, "td[data-label='Tags']").text

        save_btn = row.find_element(By.XPATH, ".//button[text()='Save']")
        save_btn.click()
        time.sleep(1.5)
        assert len(driver.find_elements(By.ID, f"unclassified-row-{uid}")) == 0

    def test_edit_hidden_while_dirty_and_revert_restores(self, driver, w, ctx):
        uid = _create_expense(ctx["email"], "Revert test", tag_titles=["Delta"])
        driver.get(_url("/budget/unclassified/"))
        time.sleep(1.5)

        row = _row(driver, uid)
        assert row.find_element(By.XPATH, ".//button[text()='Edit']").is_displayed()

        row.find_element(By.CSS_SELECTOR, "td[data-label='Category'] .unclassified-cell-view").click()
        time.sleep(0.3)
        select_el = row.find_element(By.CSS_SELECTOR, "select.unclassified-category-select")
        options = [o.text for o in Select(select_el).options if o.text.strip() and o.text != "—"]
        assert options, "expected at least one category option"
        Select(select_el).select_by_visible_text(options[0])
        time.sleep(0.3)

        assert not row.find_element(By.XPATH, ".//button[text()='Edit']").is_displayed()
        revert_btn = row.find_element(By.XPATH, ".//button[text()='Revert']")
        assert revert_btn.is_displayed()
        revert_btn.click()
        time.sleep(0.5)

        row = _row(driver, uid)
        assert row.find_element(By.XPATH, ".//button[text()='Edit']").is_displayed()
        assert "—" in row.find_element(By.CSS_SELECTOR, "td[data-label='Category']").text

    def test_foreign_expense_edit_routes_to_overlay_editor(self, driver, w, ctx):
        owner = setup_user(driver, w)
        try:
            uid = _create_foreign_expense(
                owner["email"], ctx["email"], "Foreign edit routing test",
                owner_category="Owner Cat", owner_tag_titles=["OwnerTag"],
            )
            _relogin(driver, w, ctx)
            driver.get(_url("/budget/unclassified/"))
            time.sleep(1.5)

            row = _row(driver, uid)
            assert "From " in row.text
            row.find_element(By.XPATH, ".//button[text()='Edit']").click()
            time.sleep(1)

            assert "edit-overlay" in driver.current_url
            assert "back=" in driver.current_url

            driver.find_element(By.CSS_SELECTOR, "a.btn-secondary").click()
            time.sleep(1)
            assert driver.current_url.rstrip("/").endswith("/budget/unclassified")
        finally:
            cleanup_user(owner["email"])

    def test_foreign_expense_with_no_overlay_creates_overlay_on_save(self, driver, w, ctx):
        owner = setup_user(driver, w)
        try:
            uid = _create_foreign_expense(
                owner["email"], ctx["email"], "On the fly overlay test",
                owner_category="Owner Cat 2", owner_tag_titles=["OwnerTag2"],
            )
            assert _overlay_count(ctx["email"], uid) == 0

            _relogin(driver, w, ctx)
            _ensure_tag(ctx, "MyOwnTag")
            driver.get(_url("/budget/unclassified/"))
            time.sleep(1.5)

            row = _row(driver, uid)
            row.find_element(By.CSS_SELECTOR, "td[data-label='Category'] .unclassified-cell-view").click()
            time.sleep(0.3)
            select_el = row.find_element(By.CSS_SELECTOR, "select.unclassified-category-select")
            options = [o.text for o in Select(select_el).options if o.text.strip() and o.text != "—"]
            Select(select_el).select_by_visible_text(options[0])
            time.sleep(0.3)

            row.find_element(By.CSS_SELECTOR, "td[data-label='Tags'] .unclassified-cell-view").click()
            time.sleep(0.3)
            tag_input = row.find_element(By.CSS_SELECTOR, ".unclassified-tag-input")
            driver.execute_script(
                "arguments[0].value = arguments[1];"
                "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));",
                tag_input, "MyOwnTag",
            )
            time.sleep(0.5)
            row.find_element(
                By.XPATH, ".//div[contains(@class,'unclassified-tag-suggestion') and text()='MyOwnTag']"
            ).click()
            time.sleep(0.3)
            driver.find_element(By.TAG_NAME, "h1").click()
            time.sleep(0.3)

            row.find_element(By.XPATH, ".//button[text()='Save']").click()
            time.sleep(1.5)

            assert len(driver.find_elements(By.ID, f"unclassified-row-{uid}")) == 0
            assert _overlay_count(ctx["email"], uid) == 1
            cat_title, tag_titles = _overlay_values(ctx["email"], uid)
            assert cat_title == options[0]
            assert tag_titles == ["MyOwnTag"]
        finally:
            cleanup_user(owner["email"])


def _ensure_category(ctx, title) -> str:
    _shell(
        f"from feusers.models import FeUser\nfrom budget.models import Category\n"
        f"u = FeUser.objects.get(email={ctx['email']!r})\n"
        f"Category.objects.get_or_create(owning_feuser=u, title={title!r})"
    )
    return title


def _ensure_tag(ctx, title) -> str:
    _shell(
        f"from feusers.models import FeUser\nfrom budget.models import Tag\n"
        f"u = FeUser.objects.get(email={ctx['email']!r})\n"
        f"Tag.objects.get_or_create(owning_feuser=u, title={title!r})"
    )
    return title


def _relogin(driver, w, ctx):
    from helpers import browser_login
    driver.delete_all_cookies()
    driver.execute_script("sessionStorage.clear(); localStorage.clear();")
    browser_login(driver, w, ctx["email"], ctx["password"])


def _ai_gate_ok(driver) -> bool:
    driver.get(_url("/budget/unclassified/"))
    time.sleep(1)
    return "Let AI solve" in driver.page_source or "Let AI resolve all" in driver.page_source


class TestUnclassifiedExpensesAI:

    def test_ai_solve_updates_row_and_flips_to_retry(self, driver, w, ctx):
        if not _ai_gate_ok(driver):
            pytest.skip("AI not available for this account")

        uid = _create_expense(ctx["email"], "Netflix subscription", payee="Netflix")
        driver.get(_url("/budget/unclassified/"))
        time.sleep(1.5)

        row = _row(driver, uid)
        ai_btn = row.find_element(By.XPATH, ".//button[contains(text(),'Let AI solve')]")
        ai_btn.click()
        time.sleep(12)

        row = _row(driver, uid)
        cat_text = row.find_element(By.CSS_SELECTOR, "td[data-label='Category']").text
        assert cat_text.strip() not in ("", "—"), "AI did not fill in a category"
        assert row.find_elements(By.XPATH, ".//button[contains(text(),'Let AI retry')]")

        save_btn = row.find_element(By.XPATH, ".//button[text()='Save']")
        save_btn.click()
        time.sleep(1.5)
        assert len(driver.find_elements(By.ID, f"unclassified-row-{uid}")) == 0

    def test_ai_resolve_all_and_save_all(self, driver, w, ctx):
        if not _ai_gate_ok(driver):
            pytest.skip("AI not available for this account")

        uid_a = _create_expense(ctx["email"], "Spotify subscription", payee="Spotify")
        uid_b = _create_expense(ctx["email"], "Gas station fill-up", payee="Shell")
        driver.get(_url("/budget/unclassified/"))
        time.sleep(1.5)

        assert not driver.find_elements(By.XPATH, "//button[text()='Save all']") or \
            not driver.find_element(By.XPATH, "//button[text()='Save all']").is_displayed()

        driver.find_element(By.XPATH, "//button[contains(text(),'Let AI resolve all')]").click()
        time.sleep(25)

        save_all = driver.find_element(By.XPATH, "//button[text()='Save all']")
        assert save_all.is_displayed()
        save_all.click()
        time.sleep(2)

        assert len(driver.find_elements(By.ID, f"unclassified-row-{uid_a}")) == 0
        assert len(driver.find_elements(By.ID, f"unclassified-row-{uid_b}")) == 0

    def test_ai_solve_bills_trial_usage(self, driver, w, ctx):
        """The hard requirement: AI usage through this feature must count
        against the feuser's trial budget, exactly like every other AI
        feature. Force this account off its dedicated test key (if any) so
        it falls back to the shared trial key, mirroring how
        tests/e2e/express/test_express.py manipulates trial fields directly."""
        spent_before = _shell(
            f"from feusers.models import FeUser\n"
            f"u = FeUser.objects.get(email={ctx['email']!r})\n"
            f"u.anthropic_api_key = ''\n"
            f"u.save(update_fields=['anthropic_api_key'])\n"
            f"print(u.ai_trial_budget_spent)"
        )
        uid = _create_expense(ctx["email"], "Amazon order", payee="Amazon")

        cookies = session_cookies(driver)
        s = requests.Session()
        s.cookies.update(cookies)
        s.get(_url("/budget/unclassified/"))
        csrftoken = next((c.value for c in s.cookies if c.name == "csrftoken"), "")
        resp = s.post(
            _url(f"/budget/unclassified/{uid}/ai-solve/"),
            headers={"X-CSRFToken": csrftoken, "Referer": _url("/budget/unclassified/")},
        )
        if resp.status_code == 402:
            pytest.skip("Shared AI trial not available/exhausted in this environment")
        assert resp.status_code == 200, resp.text

        spent_after = _shell(
            f"from feusers.models import FeUser\n"
            f"u = FeUser.objects.get(email={ctx['email']!r})\n"
            f"print(u.ai_trial_budget_spent)"
        )
        assert float(spent_after) > float(spent_before), (
            f"ai_trial_budget_spent did not increase: before={spent_before} after={spent_after}"
        )
