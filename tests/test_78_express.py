"""
Browser tests for Express Creation (AI-powered expense parsing).

REQUIREMENTS
  - AI_TRIAL_API_KEY must be set in the running container's environment.
  - The trial disabled flag file must NOT exist.
  - The test user must not have exceeded their trial budget.

If any of those conditions are not met the whole class emits a WARNING and
every test is skipped — no hard failures.

Assertions are intentionally lenient: tests only fail when the AI really
screws up (zero results, completely wrong types, wildly wrong totals).
"""
import re
import subprocess
import time
import warnings
from pathlib import Path

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from conftest import (
    _url,
    api_delete,
    api_get,
    api_post,
    run_cmd,
    DOCKER_WEB,
)

AI_TIMEOUT = 120  # seconds — AI calls can be slow

ASSETS = Path(__file__).parent / "assets"

# Curated category and tag lists designed to be unambiguous for the AI.
# The fixture wipes all existing cats/tags and installs exactly these,
# so the AI always picks from a clean, well-labelled catalog.
_CATEGORIES = [
    "Consumer Electronics",      # TV, phones, gadgets
    "Travel & Transport",        # trains, flights, taxis
    "Snacks & Beverages",        # drinks, snacks, candy
    "Groceries & Supermarket",   # supermarket runs, food shopping
    "Personal Care & Hygiene",   # toothpaste, soap, cleaning supplies
    "Cafes & Restaurants",       # coffee, croissants, eating out
    "Entertainment & Events",    # concerts, festivals, cinema
    "Home & Household",          # furniture, appliances, general home
]
_TAGS = [
    "Festival",       # outdoor events, Schanzenfest etc.
    "Public Transport",  # train, bus, subway
    "Alcohol",        # beer, wine, cocktails
    "Supermarket",    # Edeka, Rewe, Aldi etc.
    "Tech",           # electronics purchases
    "Health",         # pharmacy, personal care
]


# ── Page / card helpers ───────────────────────────────────────────────────────

def _trial_status(driver):
    """Navigate to express creation and return (ok, reason)."""
    driver.get(_url("/budget/ai/express-creation/"))
    time.sleep(1)

    if "/profile" in driver.current_url:
        return False, "No API key configured (redirected to profile)"

    src = driver.page_source
    if "temporarily unavailable" in src:
        return False, "Trial key is disabled (billing issue or missing key)"
    if "Monthly AI limit reached" in src:
        return False, "Trial budget exhausted for this month"

    if driver.find_elements(By.CSS_SELECTOR, ".trial-blocked"):
        return False, "Trial is blocked or disabled"

    return True, ""


def _trial_meter_value(driver):
    """Return the current spent-cents from the trial meter, or None."""
    els = driver.find_elements(By.CSS_SELECTOR, ".trial-meter")
    if not els:
        return None
    m = re.match(r"([\d.]+)", els[0].text.strip())
    return float(m.group(1)) if m else None


def _parse(driver, description="", image_path=None):
    """Submit the parse form and return the .preview-card elements."""
    driver.get(_url("/budget/ai/express-creation/"))

    if description:
        ta = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "textarea[name=description]"))
        )
        ta.clear()
        ta.send_keys(description)

    if image_path:
        inp = driver.find_element(By.ID, "img-file-input")
        driver.execute_script("arguments[0].style.display = 'block';", inp)
        inp.send_keys(str(image_path))

    driver.find_element(By.ID, "parse-btn").click()

    return WebDriverWait(driver, AI_TIMEOUT).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".preview-card"))
    )


def _card_type(card):
    return Select(card.find_element(By.CSS_SELECTOR, ".edit-type")).first_selected_option.get_attribute("value")


def _card_value(card):
    return float(card.find_element(By.CSS_SELECTOR, ".edit-value").get_attribute("value") or 0)


def _card_category_label(card):
    return Select(card.find_element(By.CSS_SELECTOR, ".edit-category")).first_selected_option.text


def _card_title(card):
    return card.find_element(By.CSS_SELECTOR, ".edit-title").get_property("value")


def _card_payee(card):
    return card.find_element(By.CSS_SELECTOR, ".edit-payee").get_property("value")


def _card_note(card):
    return card.find_element(By.CSS_SELECTOR, ".edit-note").get_property("value")


def _checked_tag_count(card):
    return len(card.find_elements(By.CSS_SELECTOR, ".edit-tag-cb:checked"))


# ── Test class ────────────────────────────────────────────────────────────────

class TestExpressCreation:

    @pytest.fixture(autouse=True, scope="class")
    def _setup_teardown(self, ctx):
        """
        Wipe ALL existing categories and tags so the AI gets a clean, curated
        catalog with unambiguous names.  After the tests, remove the curated
        catalog and restore the originals so later tests (teardown) still work.
        """
        # -- save and nuke existing cats & tags --
        prior_cats = api_get("/api/v1/categories/", ctx).json().get("categories", [])
        for c in prior_cats:
            api_delete(f"/api/v1/categories/{c['id']}/", ctx)

        prior_tags = api_get("/api/v1/tags/", ctx).json().get("tags", [])
        for t in prior_tags:
            api_delete(f"/api/v1/tags/{t['id']}/", ctx)

        # -- create curated catalog --
        cat_ids = []
        for name in _CATEGORIES:
            r = api_post("/api/v1/categories/", ctx, json={"title": name})
            assert r.status_code == 201, f"Could not create category {name!r}: {r.text}"
            cat_ids.append(r.json()["id"])

        tag_ids = []
        for name in _TAGS:
            r = api_post("/api/v1/tags/", ctx, json={"title": name})
            assert r.status_code == 201, f"Could not create tag {name!r}: {r.text}"
            tag_ids.append(r.json()["id"])

        yield

        # -- cleanup expenses created during submit test --
        for exp_id in ctx.get("express_created_expense_ids", []):
            api_delete(f"/api/v1/expenses/{exp_id}/", ctx)

        # -- remove the curated catalog --
        for uid in tag_ids:
            api_delete(f"/api/v1/tags/{uid}/", ctx)
        for uid in cat_ids:
            api_delete(f"/api/v1/categories/{uid}/", ctx)

        # -- restore originals so teardown tests still find their items --
        # ctx["category_uid"] / ctx["tag_uid"] are strings (from dataset.uid in JS),
        # while API ids are ints — compare as strings to avoid the type mismatch.
        for c in prior_cats:
            r = api_post("/api/v1/categories/", ctx, json={"title": c["title"]})
            if r.status_code == 201:
                if str(c["id"]) == str(ctx.get("category_uid", "")):
                    ctx["category_uid"] = str(r.json()["id"])
        for t in prior_tags:
            r = api_post("/api/v1/tags/", ctx, json={"title": t["title"]})
            if r.status_code == 201:
                if str(t["id"]) == str(ctx.get("tag_uid", "")):
                    ctx["tag_uid"] = str(r.json()["id"])

    # ── 1. Trial availability ─────────────────────────────────────────────────

    def test_78_trial_available(self, driver, w, ctx):
        """Warn and skip the whole suite if the AI trial is not operational."""
        ok, reason = _trial_status(driver)
        if not ok:
            warnings.warn(
                f"Express Creation trial not available — skipping all express tests. Reason: {reason}",
                UserWarning,
                stacklevel=2,
            )
            pytest.skip(reason)
        ctx["express_trial_ok"] = True

    # ── 2. TV purchase ────────────────────────────────────────────────────────

    def test_79_express_tv_purchase(self, driver, w, ctx):
        """
        'I bought a new TV for 1500€. 500 paid upfront, 1000 from savings.'

        The description is unambiguous — it must produce exactly two items:
          - one expense (net TV cost: 500€)
          - one savings withdrawal (1000€)
        Both should carry the Electronics category.
        Total value is allowed ±200 to absorb any rounding.
        """
        if not ctx.get("express_trial_ok"):
            pytest.skip("Trial not available")

        cards = _parse(
            driver,
            "I bought a new TV. 500 euros paid upfront, 1000 from savings.",
        )
        assert len(cards) == 2, (
            f"Expected exactly 2 items (expense + savings withdrawal), got {len(cards)}"
        )

        values = [_card_value(c) for c in cards]
        types  = [_card_type(c)  for c in cards]

        total = sum(values)
        assert 1300 <= total <= 1700, (
            f"Total value {total} is wildly off from expected ~1500"
        )

        savings_types = {"savings_wit", "savings_dep"}
        assert "expense" in types, f"No expense item; types={types}"
        assert any(t in savings_types for t in types), \
            f"No savings item; types={types}"

        cat_labels = [_card_category_label(c) for c in cards]
        assert any("Electronics" in lbl for lbl in cat_labels), \
            f"Electronics category not assigned to any item; categories={cat_labels}"

    # ── 3. Schanzenfest ───────────────────────────────────────────────────────

    def test_80_express_schanzenfest(self, driver, w, ctx):
        """
        'Went to attend the Schanzenfest, i spent 40€ on the train and 15€
        on drinks and snacks.'

        Leniency: AI may produce 2-3 items or merge them. We only check:
          - at least 1 item produced
          - total ≈ 55 € (allow ±20)
          - at least one Travel & Holidays item and one Snacks item
          - at least one tag set across all cards
        """
        if not ctx.get("express_trial_ok"):
            pytest.skip("Trial not available")

        cards = _parse(
            driver,
            "Went to attend the Schanzenfest, i spent 40€ on the train ticket and 15€ on drinks and snacks.",
        )
        assert cards, "AI produced zero items"

        total = sum(_card_value(c) for c in cards)
        assert 35 <= total <= 75, (
            f"Total value {total} is wildly off from expected ~55 — check AI output"
        )

        cat_labels = [_card_category_label(c) for c in cards]
        assert any("Travel" in lbl for lbl in cat_labels), \
            f"Expected a Travel & Holidays item; categories={cat_labels}"
        assert any("Snack" in lbl for lbl in cat_labels), \
            f"Expected a Snacks item; categories={cat_labels}"

        total_tags = sum(_checked_tag_count(c) for c in cards)
        assert total_tags > 0, "Expected at least one tag to be set"

    # ── 4. Receipt image ──────────────────────────────────────────────────────

    def test_81_express_receipt(self, driver, w, ctx):
        """
        Submit receipt.jpeg with no text description.

        The AI sometimes groups all items under a single 'Groceries' card and
        moves product details into the note — so we search title OR note for
        each keyword.

        Checks:
          - at least 1 item produced
          - 'Cola', 'Odol', 'Klarsp' appear somewhere in titles or notes
          - payee mentions 'Edeka'
          - at least one Groceries / Personal Care / Health category
        """
        if not ctx.get("express_trial_ok"):
            pytest.skip("Trial not available")

        receipt = ASSETS / "receipt.jpeg"
        cards = _parse(driver, image_path=receipt)
        assert cards, "AI produced zero items from the receipt image"

        # Combine titles + notes for keyword search
        all_text = " ".join(_card_title(c) + " " + _card_note(c) for c in cards)
        all_payees = " ".join(_card_payee(c) for c in cards)
        cat_labels = [_card_category_label(c) for c in cards]

        for keyword in ("Cola", "Odol", "Klarsp"):
            assert keyword.lower() in all_text.lower(), \
                f"'{keyword}' not found in titles or notes: {all_text!r}"

        assert "edeka" in all_payees.lower(), \
            f"'Edeka Stiegler' not found in payees: {all_payees!r}"

        grocery_cats = {"Groceries", "Personal Care", "Health & Pharmacy"}
        matched = any(any(g in lbl for g in grocery_cats) for lbl in cat_labels)
        assert matched, f"No grocery/care category assigned; categories={cat_labels}"

    # ── 5. Edit preview + submit + verify via API + usage counter ─────────────

    def test_82_express_edit_submit_verify(self, driver, w, ctx):
        """
        Parse a short description, edit the first item's title, submit all
        items, then:
          - verify the usage pill shows a non-zero API cost
          - verify the trial meter is higher after the call than before
          - verify the edited expense exists via API
        """
        if not ctx.get("express_trial_ok"):
            pytest.skip("Trial not available")

        driver.get(_url("/budget/ai/express-creation/"))
        time.sleep(0.5)
        spent_before = _trial_meter_value(driver)

        cards = _parse(driver, "Coffee 3.50€ and a croissant for 2€")
        assert cards, "AI produced zero items"

        # Usage pill should appear right after parse
        cost_els = driver.find_elements(By.CSS_SELECTOR, ".usage-pill .cost")
        if cost_els:
            cost_text = cost_els[0].text  # "API cost: 0.5 ¢"
            cost_val = float(re.search(r"([\d.]+)", cost_text).group(1))
            assert cost_val > 0, f"Usage cost should be non-zero; got '{cost_text}'"

        # Edit the first card's title so we can find it in the API later
        first_card = cards[0]
        title_area = first_card.find_element(By.CSS_SELECTOR, ".edit-title")
        driver.execute_script("arguments[0].value = '';", title_area)
        title_area.send_keys("XExpressTestEdited")

        # Submit
        driver.find_element(By.ID, "confirm-btn").click()
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".success-banner"))
        )

        # Verify via API — the edited expense must exist
        all_expenses = api_get("/api/v1/expenses/", ctx).json().get("expenses", [])
        created = [e for e in all_expenses if "XExpressTestEdited" in e.get("title", "")]
        assert created, "Edited expense 'XExpressTestEdited' not found via API after submit"

        # Store ALL express-created IDs for cleanup (title prefix or exact)
        ctx["express_created_expense_ids"] = [
            e["id"] for e in all_expenses
            if "XExpressTest" in e.get("title", "")
            or "croissant" in e.get("title", "").lower()
            or ("coffee" in e.get("title", "").lower() and e.get("title", "") != "XExpressTestEdited")
        ]
        # Make sure the edited one is in there too
        for e in created:
            if e["id"] not in ctx["express_created_expense_ids"]:
                ctx["express_created_expense_ids"].append(e["id"])

        # Trial meter must have gone up (only checkable if we could read it before)
        spent_after = _trial_meter_value(driver)
        if spent_before is not None and spent_after is not None:
            assert spent_after > spent_before, (
                f"Trial meter should have increased after a parse call; "
                f"before={spent_before}, after={spent_after}"
            )

    # ── 6. Trial budget enforcement ───────────────────────────────────────────

    def test_83_trial_budget_enforcement(self, driver, w, ctx):
        """
        Set the user's trial spend to (limit - 0.1 ¢), then:
          - First request:  succeeds, preview appears, "budget used up" warning shown.
          - Second request: blocked before processing, block screen shown.
        The user's original spend is restored in the finally block.
        """
        if not ctx.get("express_trial_ok"):
            pytest.skip("Trial not available")

        def _shell(code, timeout=10):
            r = subprocess.run(
                ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c", code],
                capture_output=True, text=True, timeout=timeout,
            )
            assert r.returncode == 0, f"shell command failed:\n{r.stderr}"
            return r.stdout.strip()

        limit_raw = _shell("from django.conf import settings; print(settings.AI_TRIAL_USAGE_LIMIT)")
        trial_limit = float(limit_raw)
        if trial_limit <= 0:
            pytest.skip("AI_TRIAL_USAGE_LIMIT not configured")

        near_limit = trial_limit - 0.1
        email = ctx["email"]

        def _set_spent(value):
            _shell(
                f"from feusers.models import FeUser; "
                f"u = FeUser.objects.get(email='{email}'); "
                f"u.ai_trial_budget_spent = {value}; "
                f"u.save(update_fields=['ai_trial_budget_spent'])"
            )

        def _get_spent():
            return float(_shell(
                f"from feusers.models import FeUser; "
                f"print(FeUser.objects.get(email='{email}').ai_trial_budget_spent)"
            ))

        original_spent = _get_spent()

        try:
            # ── First request: budget almost full ────────────────────────────
            _set_spent(near_limit)

            cards = _parse(driver, "Coffee 3€")
            assert cards, "First request should succeed and return preview items"

            src = driver.page_source
            assert "trial budget is now used up" in src.lower(), (
                "Expected 'budget used up' warning after last allowed request"
            )
            assert "Monthly AI limit reached" not in src, (
                "Block screen must NOT appear on the request that exhausts the budget"
            )

            # Cleanup any expenses that might have been auto-submitted
            all_exp = api_get("/api/v1/expenses/", ctx).json().get("expenses", [])
            for e in all_exp:
                if "coffee" in e.get("title", "").lower():
                    api_delete(f"/api/v1/expenses/{e['id']}/", ctx)

            # ── Second request: budget now exhausted ─────────────────────────
            driver.get(_url("/budget/ai/express-creation/"))
            time.sleep(1)

            src = driver.page_source
            assert "Monthly AI limit reached" in src, (
                "Block screen must appear when budget is already exhausted"
            )
            assert driver.find_elements(By.CSS_SELECTOR, ".trial-blocked"), (
                "Expected .trial-blocked element on the block screen"
            )

        finally:
            _set_spent(original_spent)
