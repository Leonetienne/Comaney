"""
Client-side pagination on all three expense-list pages:
  /budget/expenses/      Alpine computed property (pagedExpenses)
  /buddies/summary/      window._attachPaginator on #buddy-direct-exp-container
  /projects/<id>/        window._attachPaginator on #proj-approved-section

PAGE_SIZE must match the hardcoded constant in each source file:
  build/js/expenses.js           pageSize: 10
  buddy_summary.html             _attachPaginator(…, 10)
  project_detail.html            _attachPaginator(…, 10)

If the production page size changes, update PAGE_SIZE here and the three
source files listed above.

No existing test modules need migration: all of them create fewer than
PAGE_SIZE expenses per user, so all items land on page 1.
"""
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from helpers import _url, setup_user, cleanup_user, api_post
from bhelpers import (
    _login_as,
    _create_buddy_link, _get_pk,
    _create_group, _add_group_member,
    _create_group_expense, _create_personal_expense_with_buddy,
)

PAGE_SIZE = 25
N_ITEMS   = PAGE_SIZE + 2   # 27 → 2 pages
YEAR      = 2024
DATE      = f"{YEAR}-06-15"
EXP_URL   = _url(f"/budget/expenses/?date_from={YEAR}-01-01&date_to={YEAR}-12-31")


# ── shared helpers ─────────────────────────────────────────────────────────────

def _wait_exp_list(driver, timeout=8):
    """Wait until Alpine's expense list has finished the XHR fetch."""
    WebDriverWait(driver, timeout).until(
        lambda d: not d.find_element(By.ID, "exp-list").get_attribute("data-search-loading")
    )


def _wait_bexp_cards(driver, container_id, timeout=6):
    """Wait until the XHR-injected container contains at least one card."""
    WebDriverWait(driver, timeout).until(
        lambda d: d.find_element(By.ID, container_id).find_elements(
            By.CSS_SELECTOR, ".bexp-breakdown-card"
        )
    )


def _pagination_navs(driver):
    return driver.find_elements(By.CSS_SELECTOR, ".exp-pagination")


def _info_text(driver):
    els = driver.find_elements(By.CSS_SELECTOR, ".exp-pagination__info")
    return els[0].text if els else ""


def _click_page(driver, number, nav_index=-1):
    """Click the numbered page button in the nav at nav_index (0=top, -1=bottom)."""
    navs = _pagination_navs(driver)
    assert navs, "No .exp-pagination nav found"
    btn = navs[nav_index].find_element(
        By.XPATH, f".//button[normalize-space(.)='{number}']"
    )
    driver.execute_script("arguments[0].click();", btn)
    time.sleep(1)


def _active_page(driver):
    """Return the number on the currently highlighted page button, or None."""
    btns = driver.find_elements(By.CSS_SELECTOR, ".exp-pagination .btn-primary")
    return int(btns[0].text.strip()) if btns else None


def _rendered_exp_titles(driver):
    """Titles of .exp-card elements in Alpine DOM (= current page only)."""
    return [el.text for el in driver.find_elements(By.CSS_SELECTOR, "#exp-list .exp-title")]


def _visible_bexp_titles(driver):
    """Titles of .bexp-breakdown-card elements not hidden by _attachPaginator."""
    return [
        c.find_element(By.CSS_SELECTOR, ".bexp-title").text
        for c in driver.find_elements(By.CSS_SELECTOR, ".bexp-breakdown-card")
        if c.value_of_css_property("display") != "none"
    ]


# ── /budget/expenses/ ─────────────────────────────────────────────────────────

class TestExpenseListPagination:
    """Alpine client-side pagination on the main expense list."""

    PREFIX = "PgExp"

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w)
        for i in range(N_ITEMS):
            r = api_post("/api/v1/expenses/", c, json={
                "title": f"{self.PREFIX} {i:02d}",
                "type": "expense",
                "value": "10.00",
                "date_due": DATE,
                "settled": False,
            })
            assert r.status_code == 201, r.text
        yield c
        cleanup_user(c["email"])

    def _load(self, driver):
        driver.get(EXP_URL)
        time.sleep(2)
        _wait_exp_list(driver)

    def test_nav_appears(self, driver, w, ctx):
        self._load(driver)
        navs = _pagination_navs(driver)
        visible = [n for n in navs if n.value_of_css_property("display") != "none"]
        assert len(visible) >= 2, "Expected top + bottom nav both visible with 27 items"

    def test_info_text_format(self, driver, w, ctx):
        info = _info_text(driver)
        assert "Page 1 of 2" in info, f"Got: {info!r}"
        assert f"{N_ITEMS} entries" in info, f"Got: {info!r}"

    def test_first_page_renders_exactly_page_size_items(self, driver, w, ctx):
        prefix_titles = [t for t in _rendered_exp_titles(driver) if self.PREFIX in t]
        assert len(prefix_titles) == PAGE_SIZE

    def test_navigate_to_page_2(self, driver, w, ctx):
        page1 = set(_rendered_exp_titles(driver))
        _click_page(driver, 2)
        page2 = set(_rendered_exp_titles(driver))
        assert not (page1 & page2), f"Pages share items: {page1 & page2}"
        assert len([t for t in page2 if self.PREFIX in t]) == N_ITEMS - PAGE_SIZE

    def test_active_button_on_page_2(self, driver, w, ctx):
        assert _active_page(driver) == 2

    def test_first_page_button_returns_to_page_1(self, driver, w, ctx):
        nav = _pagination_navs(driver)[-1]
        btn = nav.find_element(By.XPATH, ".//button[normalize-space(.)='|<']")
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(1)
        assert _active_page(driver) == 1

    def test_top_nav_has_top_modifier_class(self, driver, w, ctx):
        classes = [n.get_attribute("class") for n in _pagination_navs(driver)]
        assert any("exp-pagination--top" in c for c in classes), \
            "Missing exp-pagination--top on the top nav"

    def test_numbered_buttons_clamped_to_seven(self, driver, w, ctx):
        """Never show more than 7 number buttons; show min(7, totalPages)."""
        nav = _pagination_navs(driver)[-1]
        num_btns = [b for b in nav.find_elements(By.CSS_SELECTOR, "button")
                    if b.text.strip().isdigit()]
        expected = min(7, 2)   # only 2 total pages in this fixture
        assert len(num_btns) == expected, \
            f"Expected {expected} number buttons, got {len(num_btns)}"

    def test_search_resets_to_page_1(self, driver, w, ctx):
        _click_page(driver, 2)
        assert _active_page(driver) == 2
        el = driver.find_element(By.ID, "exp-search")
        driver.execute_script(
            "arguments[0].value=arguments[1];"
            "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));",
            el, self.PREFIX,   # returns all 27 items, but page resets to 1
        )
        _wait_exp_list(driver)
        time.sleep(1)
        assert _active_page(driver) == 1, "Searching must reset pagination to page 1"
        # Clear search
        driver.execute_script(
            "arguments[0].value='';"
            "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));",
            el,
        )
        _wait_exp_list(driver)
        time.sleep(1)

    def test_nav_hidden_with_fewer_than_page_size_items(self, driver, w, ctx):
        """A user with fewer items than PAGE_SIZE sees no pagination nav."""
        c2 = setup_user(None, None)
        try:
            r = api_post("/api/v1/expenses/", c2, json={
                "title": "Solo", "type": "expense",
                "value": "5.00", "date_due": DATE, "settled": False,
            })
            assert r.status_code == 201
            _login_as(driver, c2)
            driver.get(EXP_URL)
            time.sleep(2)
            _wait_exp_list(driver)
            for nav in driver.find_elements(By.CSS_SELECTOR, ".exp-pagination"):
                assert nav.value_of_css_property("display") == "none", \
                    "Pagination must be hidden when all items fit on one page"
        finally:
            cleanup_user(c2["email"])
            _login_as(driver, ctx)
            self._load(driver)

    def test_export_href_not_page_scoped(self, driver, w, ctx):
        """Export CSV link points to the server endpoint, not the current page."""
        link = driver.find_element(By.CSS_SELECTOR, ".expenses-export-link")
        href = link.get_attribute("href")
        assert "/budget/expenses/export" in href, f"Unexpected export href: {href}"
        assert "page=" not in href, "Export href must not contain a page parameter"


# ── /buddies/summary/ ─────────────────────────────────────────────────────────

class TestBuddySummaryPagination:
    """window._attachPaginator on the direct-expense container at /buddies/summary/."""

    PREFIX = "PgBud"

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="PgA", last_name="Sum")
        b = setup_user(None, None, first_name="PgB", last_name="Sum")
        _create_buddy_link(a["email"], b["email"])
        a_pk = int(_get_pk(a["email"]))
        for i in range(N_ITEMS):
            _create_personal_expense_with_buddy(
                owner_email=b["email"],
                participant_pk=a_pk,
                title=f"{self.PREFIX} {i:02d}",
                value="20.00", share="50.0", approved=True,
            )
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def _load(self, driver):
        driver.get(_url("/buddies/summary/"))
        _wait_bexp_cards(driver, "buddy-direct-exp-container")
        time.sleep(1)   # let _attachPaginator run after XHR

    def test_nav_appears(self, driver, w, ctx):
        self._load(driver)
        navs = _pagination_navs(driver)
        assert navs, "Pagination nav must appear when items exceed PAGE_SIZE"

    def test_info_text_format(self, driver, w, ctx):
        info = _info_text(driver)
        assert "Page 1 of 2" in info, f"Got: {info!r}"
        assert f"{N_ITEMS} entries" in info, f"Got: {info!r}"

    def test_first_page_shows_page_size_items(self, driver, w, ctx):
        visible = [t for t in _visible_bexp_titles(driver) if self.PREFIX in t]
        assert len(visible) == PAGE_SIZE

    def test_navigate_to_page_2(self, driver, w, ctx):
        page1 = set(_visible_bexp_titles(driver))
        _click_page(driver, 2)
        page2 = set(_visible_bexp_titles(driver))
        assert page1 != page2, "Page 2 must show different items than page 1"
        assert len([t for t in page2 if self.PREFIX in t]) == N_ITEMS - PAGE_SIZE


# ── /projects/<id>/ ───────────────────────────────────────────────────────────


class TestProjectListPagination:
    """window._attachPaginator on the approved-expense section at /projects/<id>/."""

    PREFIX = "PgProj"

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="PgAdm", last_name="Proj")
        b = setup_user(None, None, first_name="PgMem", last_name="Proj")
        grp = int(_create_group(a["email"], "Pagination Test Project"))
        _add_group_member(grp, b["email"])
        for i in range(N_ITEMS):
            _create_group_expense(
                admin_email=a["email"],
                participant_email=b["email"],
                group_id=grp,
                title=f"{self.PREFIX} {i:02d}",
                value="30.00", share="50.0",
            )
        yield {"a": a, "b": b, "grp": grp}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def _load(self, driver, grp):
        driver.get(_url(f"/projects/{grp}/"))
        _wait_bexp_cards(driver, "proj-exp-list-container")
        time.sleep(1)   # let _attachPaginator run after XHR

    def test_nav_appears(self, driver, w, ctx):
        self._load(driver, ctx["grp"])
        navs = _pagination_navs(driver)
        assert navs, "Pagination nav must appear in the approved-expense section"

    def test_info_text_format(self, driver, w, ctx):
        info = _info_text(driver)
        assert "Page 1 of 2" in info, f"Got: {info!r}"
        assert f"{N_ITEMS} entries" in info, f"Got: {info!r}"

    def test_first_page_shows_page_size_items(self, driver, w, ctx):
        visible = [t for t in _visible_bexp_titles(driver) if self.PREFIX in t]
        assert len(visible) == PAGE_SIZE

    def test_navigate_to_page_2(self, driver, w, ctx):
        page1 = set(_visible_bexp_titles(driver))
        _click_page(driver, 2)
        page2 = set(_visible_bexp_titles(driver))
        assert page1 != page2, "Page 2 must show different items than page 1"
        assert len([t for t in page2 if self.PREFIX in t]) == N_ITEMS - PAGE_SIZE


# ── scroll_to: return-from-edit lands on the right page ───────────────────────

def _page2_dom_id_exp(driver):
    """DOM id of the first .exp-card in the Alpine DOM (caller must be on page 2)."""
    cards = driver.find_elements(By.CSS_SELECTOR, "#exp-list .exp-card")
    assert cards, "No .exp-card found"
    dom_id = cards[0].get_attribute("id")
    assert dom_id and dom_id.startswith("expense-"), f"Card has unexpected id: {dom_id!r}"
    return dom_id


def _page2_dom_id_bexp(driver):
    """DOM id of the first visible .bexp-breakdown-card (caller must be on page 2)."""
    visible = [
        c for c in driver.find_elements(By.CSS_SELECTOR, ".bexp-breakdown-card")
        if c.value_of_css_property("display") != "none"
    ]
    assert visible, "No visible .bexp-breakdown-card found"
    dom_id = visible[0].get_attribute("id")
    assert dom_id and dom_id.startswith("expense-"), f"Card has unexpected id: {dom_id!r}"
    return dom_id


class TestExpenseListScrollTo:
    """Returning from edit with ?scroll_to=<id> opens the right Alpine page."""

    PREFIX = "PgExpA"

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        c = setup_user(driver, w)
        for i in range(N_ITEMS):
            r = api_post("/api/v1/expenses/", c, json={
                "title": f"{self.PREFIX} {i:02d}",
                "type": "expense",
                "value": "10.00",
                "date_due": DATE,
                "settled": False,
            })
            assert r.status_code == 201, r.text
        yield c
        cleanup_user(c["email"])

    def test_scroll_to_opens_correct_page(self, driver, w, ctx):
        # Load page 2 to learn a page-2 item's DOM id and uid
        driver.get(EXP_URL)
        time.sleep(2)
        _wait_exp_list(driver)
        _click_page(driver, 2)
        dom_id = _page2_dom_id_exp(driver)
        uid = dom_id[len("expense-"):]

        # Simulate returning from edit: fresh load with ?scroll_to=<uid>
        driver.get(EXP_URL + "&scroll_to=" + uid)
        time.sleep(2)
        _wait_exp_list(driver)
        time.sleep(1)

        assert _active_page(driver) == 2, \
            f"?scroll_to={uid} must cause Alpine to open page 2"
        card = driver.find_element(By.ID, dom_id)
        assert card.is_displayed(), "Target card must be visible after scroll_to jump"


class TestBuddySummaryScrollTo:
    """_attachPaginator scroll_to jump on /buddies/summary/."""

    PREFIX = "PgBudA"

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="PgHA", last_name="Sum")
        b = setup_user(None, None, first_name="PgHB", last_name="Sum")
        _create_buddy_link(a["email"], b["email"])
        a_pk = int(_get_pk(a["email"]))
        for i in range(N_ITEMS):
            _create_personal_expense_with_buddy(
                owner_email=b["email"],
                participant_pk=a_pk,
                title=f"{self.PREFIX} {i:02d}",
                value="20.00", share="50.0", approved=True,
            )
        yield {"a": a, "b": b}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_scroll_to_opens_correct_page(self, driver, w, ctx):
        summary_url = _url("/buddies/summary/")

        # Load page 2 to learn a page-2 item's DOM id and uid
        driver.get(summary_url)
        _wait_bexp_cards(driver, "buddy-direct-exp-container")
        time.sleep(1)
        _click_page(driver, 2)
        dom_id = _page2_dom_id_bexp(driver)
        uid = dom_id[len("expense-"):]

        # Simulate returning from edit: fresh load with ?scroll_to=<uid>
        driver.get(summary_url + "?scroll_to=" + uid)
        _wait_bexp_cards(driver, "buddy-direct-exp-container")
        time.sleep(2)   # _attachPaginator + scroll_to jump

        assert _active_page(driver) == 2, \
            f"?scroll_to={uid} must cause _attachPaginator to open page 2"
        card = driver.find_element(By.ID, dom_id)
        assert card.value_of_css_property("display") != "none", \
            "Target card must not be hidden after scroll_to jump"


class TestProjectScrollTo:
    """_attachPaginator scroll_to jump on /projects/<id>/."""

    PREFIX = "PgProjA"

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="PgHAdm", last_name="Proj")
        b = setup_user(None, None, first_name="PgHMem", last_name="Proj")
        grp = int(_create_group(a["email"], "Hash Anchor Test Project"))
        _add_group_member(grp, b["email"])
        for i in range(N_ITEMS):
            _create_group_expense(
                admin_email=a["email"],
                participant_email=b["email"],
                group_id=grp,
                title=f"{self.PREFIX} {i:02d}",
                value="30.00", share="50.0",
            )
        yield {"a": a, "b": b, "grp": grp}
        cleanup_user(a["email"])
        cleanup_user(b["email"])

    def test_scroll_to_opens_correct_page(self, driver, w, ctx):
        project_url = _url(f"/projects/{ctx['grp']}/")

        # Load page 2 to learn a page-2 item's DOM id and uid
        driver.get(project_url)
        _wait_bexp_cards(driver, "proj-exp-list-container")
        time.sleep(1)
        _click_page(driver, 2)
        dom_id = _page2_dom_id_bexp(driver)
        uid = dom_id[len("expense-"):]

        # Simulate returning from edit: fresh load with ?scroll_to=<uid>
        driver.get(project_url + "?scroll_to=" + uid)
        _wait_bexp_cards(driver, "proj-exp-list-container")
        time.sleep(2)   # _attachPaginator + scroll_to jump

        assert _active_page(driver) == 2, \
            f"?scroll_to={uid} must cause _attachPaginator to open page 2"
        card = driver.find_element(By.ID, dom_id)
        assert card.value_of_css_property("display") != "none", \
            "Target card must not be hidden after scroll_to jump"
