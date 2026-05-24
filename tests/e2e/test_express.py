"""
AI Express Creation tests.

All tests skip gracefully when the AI trial key is not configured or
the trial budget is exhausted. No hard failures for missing infrastructure.
"""
import re
import subprocess
import time
import warnings
from pathlib import Path

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from helpers import (
    _url, api_get, api_post, api_delete, run_cmd, setup_user, cleanup_user,
)

DOCKER_WEB = "comaney-web-1"
AI_TIMEOUT = 120
ASSETS = Path(__file__).parent.parent / "tests" / "e2e" / "assets"

_CATEGORIES = [
    "Consumer Electronics",
    "Travel & Transport",
    "Snacks & Beverages",
    "Groceries & Supermarket",
    "Personal Care & Hygiene",
    "Cafes & Restaurants",
    "Entertainment & Events",
    "Home & Household",
]
_TAGS = [
    "Festival",
    "Public Transport",
    "Alcohol",
    "Supermarket",
    "Tech",
    "Health",
]


def _trial_status(driver):
    driver.get(_url("/budget/ai/express-creation/"))
    time.sleep(1)
    if "/profile" in driver.current_url:
        return False, "No API key configured"
    src = driver.page_source
    if "temporarily unavailable" in src:
        return False, "Trial key is disabled"
    if "Monthly AI limit reached" in src:
        return False, "Trial budget exhausted"
    if driver.find_elements(By.CSS_SELECTOR, ".trial-blocked"):
        return False, "Trial is blocked"
    return True, ""


def _trial_meter_value(driver):
    els = driver.find_elements(By.CSS_SELECTOR, ".trial-meter")
    if not els:
        return None
    m = re.match(r"([\d.]+)", els[0].text.strip())
    return float(m.group(1)) if m else None


def _parse(driver, description="", image_path=None, clear_image=False):
    if clear_image:
        driver.execute_script(
            "try { sessionStorage.removeItem('express_creation_img'); } catch(_) {}")
    driver.get(_url("/budget/ai/express-creation/"))
    if clear_image:
        driver.execute_script(
            "const w = document.getElementById('image-preview-wrap');"
            "if (w) w.style.display = 'none';"
            "const p = document.getElementById('image-placeholder');"
            "if (p) p.style.display = '';"
        )
    if description:
        time.sleep(1)
        ta = driver.find_element(By.CSS_SELECTOR, "textarea[name=description]")
        driver.execute_script("arguments[0].value = arguments[1];", ta, description)
    if image_path:
        inp = driver.find_element(By.ID, "img-file-input")
        driver.execute_script("arguments[0].style.display = 'block';", inp)
        inp.send_keys(str(image_path))
    driver.find_element(By.ID, "parse-btn").click()
    deadline = time.time() + AI_TIMEOUT
    while time.time() < deadline:
        els = driver.find_elements(By.CSS_SELECTOR, ".preview-card")
        if els:
            return els
        time.sleep(3)
    pytest.fail("AI response timed out: no .preview-card appeared")


def _parse_await_outcome(driver, description):
    driver.get(_url("/budget/ai/express-creation/"))
    time.sleep(1)
    ta = driver.find_element(By.CSS_SELECTOR, "textarea[name=description]")
    driver.execute_script("arguments[0].value = arguments[1];", ta, description)
    driver.find_element(By.ID, "parse-btn").click()
    deadline = time.time() + AI_TIMEOUT
    while time.time() < deadline:
        if (driver.find_elements(By.CSS_SELECTOR, ".ai-refusal-modal")
                or driver.find_elements(By.CSS_SELECTOR, ".preview-card")):
            break
        time.sleep(3)
    return {
        "modal": driver.find_elements(By.CSS_SELECTOR, ".ai-refusal-modal"),
        "cards": driver.find_elements(By.CSS_SELECTOR, ".preview-card"),
    }


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


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestExpressCreation:

    @pytest.fixture(autouse=True, scope="class")
    def _setup_teardown(self, ctx):
        prior_cats = api_get("/api/v1/categories/", ctx).json().get("categories", [])
        for c in prior_cats:
            api_delete(f"/api/v1/categories/{c['id']}/", ctx)
        prior_tags = api_get("/api/v1/tags/", ctx).json().get("tags", [])
        for t in prior_tags:
            api_delete(f"/api/v1/tags/{t['id']}/", ctx)

        cat_ids = []
        for name in _CATEGORIES:
            r = api_post("/api/v1/categories/", ctx, json={"title": name})
            assert r.status_code == 201
            cat_ids.append(r.json()["id"])

        tag_ids = []
        for name in _TAGS:
            r = api_post("/api/v1/tags/", ctx, json={"title": name})
            assert r.status_code == 201
            tag_ids.append(r.json()["id"])

        yield

        for exp_id in ctx.get("express_created_expense_ids", []):
            api_delete(f"/api/v1/expenses/{exp_id}/", ctx)
        for uid in tag_ids:
            api_delete(f"/api/v1/tags/{uid}/", ctx)
        for uid in cat_ids:
            api_delete(f"/api/v1/categories/{uid}/", ctx)
        for c in prior_cats:
            api_post("/api/v1/categories/", ctx, json={"title": c["title"]})
        for t in prior_tags:
            api_post("/api/v1/tags/", ctx, json={"title": t["title"]})

    def test_trial_available(self, driver, w, ctx):
        ok, reason = _trial_status(driver)
        if not ok:
            warnings.warn(
                f"Express Creation trial not available: {reason}",
                UserWarning, stacklevel=2,
            )
            pytest.skip(reason)
        ctx["express_trial_ok"] = True

    def test_express_tv_purchase(self, driver, w, ctx):
        if not ctx.get("express_trial_ok"):
            pytest.skip("Trial not available")
        cards = _parse(driver, "I bought a new TV. 500 euros paid upfront, 1000 from savings.")
        assert len(cards) == 2, f"Expected 2 items, got {len(cards)}"
        values = [_card_value(c) for c in cards]
        types = [_card_type(c) for c in cards]
        total = sum(values)
        assert 1300 <= total <= 1700, f"Total {total} off from expected ~1500"
        assert "expense" in types
        assert any(t in {"savings_wit", "savings_dep"} for t in types)
        cat_labels = [_card_category_label(c) for c in cards]
        assert any("Electronics" in lbl for lbl in cat_labels)

    def test_express_schanzenfest(self, driver, w, ctx):
        if not ctx.get("express_trial_ok"):
            pytest.skip("Trial not available")
        cards = _parse(
            driver,
            "Went to attend the Schanzenfest, i spent 40€ on the train ticket and 15€ on drinks and snacks.",
        )
        assert cards, "AI produced zero items"
        total = sum(_card_value(c) for c in cards)
        assert 35 <= total <= 75, f"Total {total} off from expected ~55"
        cat_labels = [_card_category_label(c) for c in cards]
        assert any("Travel" in lbl for lbl in cat_labels)
        assert any("Snack" in lbl for lbl in cat_labels)
        total_tags = sum(_checked_tag_count(c) for c in cards)
        assert total_tags > 0

    def test_express_receipt(self, driver, w, ctx):
        if not ctx.get("express_trial_ok"):
            pytest.skip("Trial not available")
        receipt = ASSETS / "receipt.jpeg"
        if not receipt.exists():
            pytest.skip("receipt.jpeg asset not found")
        cards = _parse(driver, image_path=receipt)
        assert cards, "AI produced zero items from receipt"
        all_text = " ".join(_card_title(c) + " " + _card_note(c) for c in cards)
        all_payees = " ".join(_card_payee(c) for c in cards)
        cat_labels = [_card_category_label(c) for c in cards]
        for keyword in ("Cola", "Odol", "Klarsp"):
            assert keyword.lower() in all_text.lower(), f"'{keyword}' not in titles/notes: {all_text!r}"
        assert "edeka" in all_payees.lower()
        grocery_cats = {"Groceries", "Personal Care", "Health"}
        assert any(any(g in lbl for g in grocery_cats) for lbl in cat_labels)

    def test_express_edit_submit_verify(self, driver, w, ctx):
        if not ctx.get("express_trial_ok"):
            pytest.skip("Trial not available")
        driver.get(_url("/budget/ai/express-creation/"))
        time.sleep(0.5)
        spent_before = _trial_meter_value(driver)
        cards = _parse(driver, "Coffee 3.50€ and a croissant for 2€", clear_image=True)
        assert cards, "AI produced zero items"
        cost_els = driver.find_elements(By.CSS_SELECTOR, ".usage-pill .cost")
        if cost_els:
            cost_text = cost_els[0].text
            cost_val = float(re.search(r"([\d.]+)", cost_text).group(1))
            assert cost_val > 0
        first_card = cards[0]
        title_area = first_card.find_element(By.CSS_SELECTOR, ".edit-title")
        driver.execute_script("arguments[0].value = 'XExpressTestEdited';", title_area)
        driver.find_element(By.ID, "confirm-btn").click()
        time.sleep(5)
        assert driver.find_elements(By.CSS_SELECTOR, ".success-banner"), "No success banner appeared"
        all_expenses = api_get("/api/v1/expenses/", ctx).json().get("expenses", [])
        created = [e for e in all_expenses if "XExpressTestEdited" in e.get("title", "")]
        assert created, "Edited expense not found via API after submit"
        ctx["express_created_expense_ids"] = [e["id"] for e in created]
        spent_after = _trial_meter_value(driver)
        if spent_before is not None and spent_after is not None:
            assert spent_after > spent_before

    def test_trial_budget_enforcement(self, driver, w, ctx):
        if not ctx.get("express_trial_ok"):
            pytest.skip("Trial not available")

        def _shell(code, timeout=10):
            r = subprocess.run(
                ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c", code],
                capture_output=True, text=True, timeout=timeout,
            )
            assert r.returncode == 0, f"shell failed:\n{r.stderr}"
            return r.stdout.strip()

        # Use a tiny special_ai_trial_budget so we control the limit without
        # touching AI_TRIAL_USAGE_LIMIT or the user's actual spent value.
        # A 1-cent limit means the very first request will exhaust it.
        email = ctx["email"]
        TINY_LIMIT = 1  # cents

        def _set_special_limit(value):
            _shell(
                f"from feusers.models import FeUser; "
                f"u = FeUser.objects.get(email='{email}'); "
                f"u.special_ai_trial_budget = {value}; "
                f"u.save(update_fields=['special_ai_trial_budget'])"
            )

        def _clear_special_limit():
            _shell(
                f"from feusers.models import FeUser; "
                f"u = FeUser.objects.get(email='{email}'); "
                f"u.special_ai_trial_budget = None; "
                f"u.ai_trial_budget_spent = 0; "
                f"u.save(update_fields=['special_ai_trial_budget', 'ai_trial_budget_spent'])"
            )

        try:
            _set_special_limit(TINY_LIMIT)
            cards = _parse(driver, "Coffee 3€")
            assert cards, "First request should succeed"
            src = driver.page_source
            assert "trial budget is now used up" in src.lower()
            assert "Monthly AI limit reached" not in src
            all_exp = api_get("/api/v1/expenses/", ctx).json().get("expenses", [])
            for e in all_exp:
                if "coffee" in e.get("title", "").lower():
                    api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
            driver.get(_url("/budget/ai/express-creation/"))
            time.sleep(1)
            src = driver.page_source
            assert "Monthly AI limit reached" in src
            assert driver.find_elements(By.CSS_SELECTOR, ".trial-blocked")
        finally:
            _clear_special_limit()

    def test_express_refusal_on_non_financial_input(self, driver, w, ctx):
        if not ctx.get("express_trial_ok"):
            pytest.skip("Trial not available")
        outcome = _parse_await_outcome(driver, "poster vom hofverkauf")
        assert outcome["modal"], "Expected refusal modal for non-financial input"
        assert not outcome["cards"], f"Expected no preview cards, got {len(outcome['cards'])}"
        msg_el = outcome["modal"][0].find_elements(By.CSS_SELECTOR, ".ai-refusal-msg")
        assert msg_el, ".ai-refusal-modal present but no .ai-refusal-msg"
        assert msg_el[0].text.strip(), ".ai-refusal-msg is empty"
