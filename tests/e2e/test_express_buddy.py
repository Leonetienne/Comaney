"""
Express Creation: buddy payment on preview cards.

Functional tests bypass the AI parse step by POSTing the confirm form directly
(action=confirm with a pre-built preview_json that includes buddy fields).

One class covers the UI integration (buddy section visible in rendered cards)
and skips gracefully when the AI trial is unavailable.
"""
import json
import subprocess
import time
import warnings

import pytest
import requests
from selenium.webdriver.common.by import By

from helpers import (
    _url, api_get, api_delete, setup_user, cleanup_user,
    session_cookies, fetch_email, mailpit_seen_ids,
)

DOCKER_WEB = "comaney-web-1"
AI_TIMEOUT = 120


def _shell(code: str) -> str:
    r = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c", code],
        capture_output=True, text=True, timeout=20,
    )
    assert r.returncode == 0, f"Shell failed:\n{r.stderr}"
    return r.stdout.strip()


def _set_fake_api_key(email: str) -> None:
    """Give the user a non-empty anthropic_api_key so the confirm action is reachable."""
    _shell(
        f"from feusers.models import FeUser; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"u.anthropic_api_key = 'sk-test-fake-key'; "
        f"u.save(update_fields=['anthropic_api_key'])"
    )


def _get_pk(email: str) -> int:
    return int(_shell(
        f"from feusers.models import FeUser; "
        f"print(FeUser.objects.get(email='{email}').pk)"
    ))


def _create_dummy(email: str, name: str = "Test Dummy") -> int:
    return int(_shell(
        f"from buddies.models import DummyUser; from feusers.models import FeUser; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"d = DummyUser.objects.create(owning_feuser=u, display_name='{name}'); "
        f"print(d.pk)"
    ))


def _create_buddy_link(email_a: str, email_b: str) -> None:
    _shell(
        f"from feusers.models import FeUser; from buddies.models import BuddyLink; "
        f"a = FeUser.objects.get(email='{email_a}'); "
        f"b = FeUser.objects.get(email='{email_b}'); "
        f"lo, hi = sorted([a, b], key=lambda u: u.pk); "
        f"BuddyLink.objects.get_or_create(user_a=lo, user_b=hi)"
    )


def _submit_confirm(driver, items: list, selected=None) -> requests.Response:
    """POST the express creation confirm form directly (no AI parse needed)."""
    cookies = session_cookies(driver)
    s = requests.Session()
    s.cookies.update(cookies)
    s.get(_url("/budget/ai/express-creation/"))
    # Use iteration to avoid CookieConflictError when Django sets a second
    # csrftoken cookie on top of the one seeded from the browser session.
    csrftoken = next((c.value for c in s.cookies if c.name == "csrftoken"), "")
    if selected is None:
        selected = list(range(len(items)))
    data = [
        ("csrfmiddlewaretoken", csrftoken),
        ("action", "confirm"),
        ("preview_json", json.dumps(items)),
    ] + [("selected", str(i)) for i in selected]
    return s.post(_url("/budget/ai/express-creation/"), data=data, allow_redirects=False)


def _base_item(**overrides) -> dict:
    base = {
        "title": "Express Buddy Test",
        "type": "expense",
        "value": "60.00",
        "payee": "",
        "note": "",
        "date_due": "",
        "category_uid": None,
        "tag_uids": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Page structure: BUDDY_EXPENSE_CONFIG injected when user has buddies
# ---------------------------------------------------------------------------

class TestExpressBuddyPageConfig:

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Config", last_name="Tester")
        _set_fake_api_key(c["email"])
        _create_dummy(c["email"], "Config Dummy")
        yield c
        cleanup_user(c["email"])

    def test_buddy_config_injected(self, driver, w, ctx):
        driver.get(_url("/budget/ai/express-creation/"))
        time.sleep(1)
        assert "BUDDY_EXPENSE_CONFIG" in driver.page_source, \
            "window.BUDDY_EXPENSE_CONFIG must be injected when user has buddies"

    def test_buddy_config_absent_without_buddies(self, driver, w, ctx):
        c2 = setup_user(None, None, first_name="No", last_name="Buddy")
        _set_fake_api_key(c2["email"])
        try:
            # Log in as user without buddies
            driver.delete_all_cookies()
            driver.execute_script("sessionStorage.clear(); localStorage.clear();")
            driver.get(_url("/login/"))
            time.sleep(1)
            email_el = driver.find_element(By.ID, "id_email")
            driver.execute_script("arguments[0].value = arguments[1];", email_el, c2["email"])
            pass_el = driver.find_element(By.ID, "id_password")
            driver.execute_script("arguments[0].value = arguments[1];", pass_el, c2["password"])
            driver.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
            time.sleep(2)
            driver.get(_url("/budget/ai/express-creation/"))
            time.sleep(1)
            assert "BUDDY_EXPENSE_CONFIG" not in driver.page_source, \
                "BUDDY_EXPENSE_CONFIG must not be injected when user has no buddies"
        finally:
            cleanup_user(c2["email"])
            # Log back in as original user
            driver.delete_all_cookies()
            driver.execute_script("sessionStorage.clear(); localStorage.clear();")
            driver.get(_url("/login/"))
            time.sleep(1)
            email_el = driver.find_element(By.ID, "id_email")
            driver.execute_script("arguments[0].value = arguments[1];", email_el, ctx["email"])
            pass_el = driver.find_element(By.ID, "id_password")
            driver.execute_script("arguments[0].value = arguments[1];", pass_el, ctx["password"])
            driver.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
            time.sleep(2)


# ---------------------------------------------------------------------------
# Confirm: me as upfront payer, dummy as participant
# ---------------------------------------------------------------------------

class TestExpressBuddyConfirmDummyParticipant:
    """Confirm an expense where I pay upfront and a dummy splits the cost.

    The expense must appear in the regular expense API and on the buddy summary.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Payer", last_name="Express")
        _set_fake_api_key(c["email"])
        dummy_id = _create_dummy(c["email"], "Express Dummy")
        me_pk = _get_pk(c["email"])
        c["dummy_id"] = dummy_id
        c["me_pk"] = me_pk
        yield c
        for exp in api_get("/api/v1/expenses/", c).json().get("expenses", []):
            if "ExpressDummyPart" in exp.get("title", ""):
                api_delete(f"/api/v1/expenses/{exp['id']}/", c)
        cleanup_user(c["email"])

    def test_confirm_with_dummy_participant(self, driver, w, ctx):
        item = _base_item(
            title="ExpressDummyPart",
            buddy_payment=True,
            buddy_mode="single",
            buddy_group_id=None,
            buddy_upfront_type="me",
            buddy_upfront_id=ctx["me_pk"],
            buddy_spendings=[{"type": "dummy", "id": ctx["dummy_id"], "share_percent": 50.0}],
        )
        resp = _submit_confirm(driver, [item])
        assert resp.status_code in (200, 302), f"Unexpected status: {resp.status_code}"

    def test_expense_in_api(self, driver, w, ctx):
        resp = api_get("/api/v1/expenses/", ctx, params={"q": "ExpressDummyPart"})
        assert resp.status_code == 200
        assert any(e["title"] == "ExpressDummyPart" for e in resp.json()["expenses"]), \
            "Expense must appear in the expense API (me is upfront payer)"

    def test_expense_on_buddy_summary_ui(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "ExpressDummyPart" in driver.page_source, \
            "Expense must appear on the buddy summary page"


# ---------------------------------------------------------------------------
# Confirm: dummy as upfront payer (is_dummy expense)
# ---------------------------------------------------------------------------

class TestExpressBuddyConfirmDummyPayer:
    """Confirm an expense where a dummy paid upfront.

    The expense must NOT appear in the regular expense API (is_dummy=True),
    but must be visible on the buddy summary.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="Borrower", last_name="Express")
        _set_fake_api_key(c["email"])
        dummy_id = _create_dummy(c["email"], "Express Lender")
        me_pk = _get_pk(c["email"])
        c["dummy_id"] = dummy_id
        c["me_pk"] = me_pk
        yield c
        cleanup_user(c["email"])

    def test_confirm_with_dummy_payer(self, driver, w, ctx):
        item = _base_item(
            title="ExpressDummyPayer",
            buddy_payment=True,
            buddy_mode="single",
            buddy_group_id=None,
            buddy_upfront_type="dummy",
            buddy_upfront_id=ctx["dummy_id"],
            buddy_spendings=[{"type": "feuser", "id": ctx["me_pk"], "share_percent": 50.0}],
        )
        resp = _submit_confirm(driver, [item])
        assert resp.status_code in (200, 302), f"Unexpected status: {resp.status_code}"

    def test_expense_not_in_api(self, driver, w, ctx):
        resp = api_get("/api/v1/expenses/", ctx, params={"q": "ExpressDummyPayer"})
        assert resp.status_code == 200
        assert not any(e["title"] == "ExpressDummyPayer" for e in resp.json()["expenses"]), \
            "Dummy-payer expense must not appear in the expense API (is_dummy=True)"

    def test_expense_on_buddy_summary_ui(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "ExpressDummyPayer" in driver.page_source, \
            "Dummy-payer expense must appear on the buddy summary page"


# ---------------------------------------------------------------------------
# Confirm: real feuser buddy as upfront payer (buddy_approved=False + email)
# ---------------------------------------------------------------------------

class TestExpressBuddyConfirmFeuserPayer:
    """Confirm an expense where a connected feuser paid upfront.

    The expense must be saved on the buddy's account with buddy_approved=False,
    and the buddy must receive an approval-request email.
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Asker", last_name="Express")
        b = setup_user(None, None, first_name="ApproverB", last_name="Express")
        _set_fake_api_key(a["email"])
        _create_buddy_link(a["email"], b["email"])
        b_pk = _get_pk(b["email"])
        a["b"] = b
        a["b_pk"] = b_pk
        a["me_pk"] = _get_pk(a["email"])
        yield a
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_confirm_with_feuser_payer(self, driver, w, ctx):
        ctx["seen_before"] = mailpit_seen_ids()
        item = _base_item(
            title="ExpressFeuserPayer",
            buddy_payment=True,
            buddy_mode="single",
            buddy_group_id=None,
            buddy_upfront_type="feuser",
            buddy_upfront_id=ctx["b_pk"],
            buddy_spendings=[{"type": "feuser", "id": ctx["me_pk"], "share_percent": 50.0}],
        )
        resp = _submit_confirm(driver, [item])
        assert resp.status_code in (200, 302), f"Unexpected status: {resp.status_code}"

    def test_expense_not_in_askers_api(self, driver, w, ctx):
        resp = api_get("/api/v1/expenses/", ctx, params={"q": "ExpressFeuserPayer"})
        assert resp.status_code == 200
        assert not any(e["title"] == "ExpressFeuserPayer" for e in resp.json()["expenses"]), \
            "Expense on buddy's account must not appear in the asker's expense API"

    def test_approval_email_sent_to_buddy(self, driver, w, ctx):
        body = fetch_email(
            ctx["b"]["email"],
            "needs your approval",
            ignore_ids=ctx.get("seen_before"),
        )
        assert "ExpressFeuserPayer" in body, \
            "Approval email must mention the expense title"

    def test_expense_on_askers_buddy_summary(self, driver, w, ctx):
        driver.get(_url("/buddies/summary/"))
        time.sleep(1)
        assert "ExpressFeuserPayer" in driver.page_source, \
            "Expense must appear on the asker's buddy summary (as participant)"


# ---------------------------------------------------------------------------
# UI: buddy section visible in preview cards (requires AI, skip if unavailable)
# ---------------------------------------------------------------------------

class TestExpressBuddyCardUI:
    """The buddy section HTML is rendered inside preview cards when the user has buddies."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w, first_name="UIBuddy", last_name="Express")
        _create_dummy(c["email"], "UI Card Dummy")
        yield c
        cleanup_user(c["email"])

    def test_trial_available(self, driver, w, ctx):
        driver.get(_url("/budget/ai/express-creation/"))
        time.sleep(1)
        if "/profile" in driver.current_url:
            pytest.skip("No API key configured")
        src = driver.page_source
        if "temporarily unavailable" in src or "Monthly AI limit reached" in src:
            pytest.skip("AI trial not available")
        ctx["ai_ok"] = True

    def test_buddy_section_present_in_cards(self, driver, w, ctx):
        if not ctx.get("ai_ok"):
            pytest.skip("AI not available")
        driver.get(_url("/budget/ai/express-creation/"))
        time.sleep(1)
        ta = driver.find_element(By.CSS_SELECTOR, "textarea[name=description]")
        ta.clear()
        ta.send_keys("Coffee 3.50 euros")
        driver.find_element(By.ID, "parse-btn").click()
        deadline = time.time() + AI_TIMEOUT
        while time.time() < deadline:
            if driver.find_elements(By.CSS_SELECTOR, ".preview-card"):
                break
            time.sleep(3)
        else:
            pytest.skip("AI timed out — skipping UI buddy test")
        cards = driver.find_elements(By.CSS_SELECTOR, ".preview-card")
        assert cards, "No preview cards rendered"
        first_card = cards[0]
        assert first_card.find_elements(By.CSS_SELECTOR, ".buddy-payment-cb"), \
            "buddy-payment-cb checkbox must be present inside each preview card"
        assert "This is a buddy payment" in first_card.text

    def test_toggle_shows_buddy_details(self, driver, w, ctx):
        if not ctx.get("ai_ok"):
            pytest.skip("AI not available")
        cards = driver.find_elements(By.CSS_SELECTOR, ".preview-card")
        if not cards:
            pytest.skip("No preview cards")
        cb = cards[0].find_element(By.CSS_SELECTOR, ".buddy-payment-cb")
        cb.click()
        time.sleep(0.5)
        details = cards[0].find_element(By.CSS_SELECTOR, ".pcard-buddy-details")
        assert details.is_displayed(), "Buddy details section must become visible after checking the checkbox"

    def test_payer_dropdown_populated(self, driver, w, ctx):
        if not ctx.get("ai_ok"):
            pytest.skip("AI not available")
        cards = driver.find_elements(By.CSS_SELECTOR, ".preview-card")
        if not cards:
            pytest.skip("No preview cards")
        sel = cards[0].find_element(By.CSS_SELECTOR, ".buddy-upfront-select")
        options = sel.find_elements(By.TAG_NAME, "option")
        assert len(options) >= 2, \
            "Payer dropdown must have at least 'Me' and one buddy option"
