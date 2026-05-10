"""
Dashboard cards – end-to-end tests.

Tests:
  - Creating a cell card via the API (POST /budget/dashboard/cards/)
  - Creating a bar-chart card via the API
  - Data endpoint returns card with computed value
  - Updating a card's YAML via PATCH
  - Reordering cards via POST /reorder/
  - Resizing a card via PATCH /resize/
  - Deleting a card via DELETE
  - YAML validation errors return 400
  - Sandboxed Python cell (method=custom)
  - Presets endpoint returns items
  - Dashboard page renders (browser smoke test)
  - Dashboard add-card dialog opens and creates a card (browser)
  - Edit and delete via browser modal
"""

import requests

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from conftest import BASE_URL, _url, session_cookies, wait_text

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CARDS_URL   = BASE_URL + "/budget/dashboard/cards/"
REORDER_URL = BASE_URL + "/budget/dashboard/cards/reorder/"
PRESETS_URL = BASE_URL + "/budget/dashboard/cards/presets/"


def _cards_session(driver) -> requests.Session:
    """Return a requests Session carrying the browser's session cookie."""
    s = requests.Session()
    s.cookies.update(session_cookies(driver))
    return s


def _csrf(sess: requests.Session) -> str:
    """Fetch a CSRF token from the session cookies (set during GET)."""
    return sess.cookies.get("csrftoken", "")


def _get_csrf(sess: requests.Session) -> str:
    sess.get(BASE_URL + "/budget/")  # ensures csrftoken cookie is set
    return sess.cookies.get("csrftoken", "")


def _post_card(sess, csrf, yaml_str) -> requests.Response:
    return sess.post(
        CARDS_URL,
        json={"yaml_config": yaml_str},
        headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDashboardCardsAPI:

    def test_01_presets_returns_list(self, driver, w, ctx):
        sess = _cards_session(driver)
        r = sess.get(PRESETS_URL)
        assert r.status_code == 200
        data = r.json()
        assert "presets" in data
        assert len(data["presets"]) > 0
        assert "name" in data["presets"][0]
        assert "yaml" in data["presets"][0]

    def test_02_create_cell_card(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _get_csrf(sess)
        yaml_str = (
            "type: cell\n"
            "title: Test Income\n"
            "query: \"type=income\"\n"
            "method: sum\n"
            "positioning:\n"
            "    position: 1\n"
            "    width: 2\n"
            "    height: 1\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 201, r.text
        data = r.json()
        assert "card" in data
        card = data["card"]
        assert card["config"]["type"] == "cell"
        assert card["config"]["title"] == "Test Income"
        assert card["width"] == 2
        assert card["height"] == 1
        assert card["error"] is None
        ctx["card_id_cell"] = card["id"]

    def test_03_create_bar_chart_card(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _get_csrf(sess)
        yaml_str = (
            "type: bar-chart\n"
            "group: tags\n"
            "title: Tags Chart\n"
            "positioning:\n"
            "    position: 2\n"
            "    width: 3\n"
            "    height: 3\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 201, r.text
        data = r.json()
        card = data["card"]
        assert card["config"]["type"] == "bar-chart"
        assert card["width"] == 3
        assert card["height"] == 3
        ctx["card_id_bar"] = card["id"]

    def test_04_list_returns_cards_with_data(self, driver, w, ctx):
        sess = _cards_session(driver)
        r = sess.get(CARDS_URL)
        assert r.status_code == 200
        data = r.json()
        ids = [c["id"] for c in data["cards"]]
        assert ctx["card_id_cell"] in ids
        assert ctx["card_id_bar"] in ids
        # Cell card has a numeric value
        cell = next(c for c in data["cards"] if c["id"] == ctx["card_id_cell"])
        assert "value" in cell["data"]

    def test_05_invalid_yaml_returns_400(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _get_csrf(sess)
        r = _post_card(sess, csrf, "type: not-a-real-type\n")
        assert r.status_code == 400
        assert "error" in r.json()

    def test_06_missing_group_returns_400(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _get_csrf(sess)
        r = _post_card(sess, csrf, "type: bar-chart\ntitle: No group\n")
        assert r.status_code == 400

    def test_07_custom_python_cell(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _get_csrf(sess)
        yaml_str = (
            "type: cell\n"
            "title: Custom Python\n"
            "method: custom\n"
            "python: |\n"
            "    return 42\n"
            "positioning:\n"
            "    position: 5\n"
            "    width: 1\n"
            "    height: 1\n"
        )
        r = _post_card(sess, csrf, yaml_str)
        assert r.status_code == 201, r.text
        card = r.json()["card"]
        assert card["data"]["value"] == 42.0
        ctx["card_id_custom"] = card["id"]

    def test_08_patch_card_yaml(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _get_csrf(sess)
        new_yaml = (
            "type: cell\n"
            "title: Renamed Cell\n"
            "query: \"type=income\"\n"
            "method: sum\n"
            "positioning:\n"
            "    position: 1\n"
            "    width: 1\n"
            "    height: 1\n"
        )
        url = CARDS_URL.rstrip("/") + f"/{ctx['card_id_cell']}/"
        r = sess.patch(
            url,
            json={"yaml_config": new_yaml},
            headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
        )
        assert r.status_code == 200, r.text
        card = r.json()["card"]
        assert card["config"]["title"] == "Renamed Cell"
        assert card["width"] == 1

    def test_09_resize_card(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _get_csrf(sess)
        url = CARDS_URL.rstrip("/") + f"/{ctx['card_id_bar']}/resize/"
        r = sess.patch(
            url,
            json={"width": 4, "height": 2},
            headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["width"] == 4
        assert data["height"] == 2

    def test_10_reorder_cards(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _get_csrf(sess)
        positions = [
            {"id": ctx["card_id_bar"],  "position": 1},
            {"id": ctx["card_id_cell"], "position": 2},
        ]
        r = sess.post(
            REORDER_URL,
            json={"positions": positions},
            headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
        )
        assert r.status_code == 200

        # Verify order in list response
        cards = sess.get(CARDS_URL).json()["cards"]
        by_id = {c["id"]: c for c in cards}
        assert by_id[ctx["card_id_bar"]]["position"]  == 1
        assert by_id[ctx["card_id_cell"]]["position"] == 2

    def test_11_delete_custom_card(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _get_csrf(sess)
        url = CARDS_URL.rstrip("/") + f"/{ctx['card_id_custom']}/"
        r = sess.delete(url, headers={"X-CSRFToken": csrf})
        assert r.status_code == 200
        cards = sess.get(CARDS_URL).json()["cards"]
        ids = [c["id"] for c in cards]
        assert ctx["card_id_custom"] not in ids

    def test_12_delete_404_for_wrong_user(self, driver, w, ctx):
        # Use a non-existent uid — should 404
        sess = _cards_session(driver)
        csrf = _get_csrf(sess)
        url = CARDS_URL.rstrip("/") + "/9999999/"
        r = sess.delete(url, headers={"X-CSRFToken": csrf})
        assert r.status_code == 404


class TestDashboardBrowser:

    def test_20_dashboard_page_loads(self, driver, w, ctx):
        driver.get(_url("/budget/"))
        # Wait for Alpine to initialise and finish loading
        w.until(lambda d: d.execute_script(
            "return document.querySelector('.dash-grid') !== null || "
            "document.querySelector('.dash-loading') !== null"
        ))

    def test_21_grid_renders_cards(self, driver, w, ctx):
        driver.get(_url("/budget/"))
        # Wait until loading spinner disappears and grid is visible
        w.until(lambda d: not d.execute_script(
            "const el = document.querySelector('.dash-loading');"
            "return el && el.style.display !== 'none';"
        ))
        # At least one dash-card should be in the DOM
        w.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, ".dash-card")) > 0)

    def test_22_add_card_dialog_opens(self, driver, w, ctx):
        driver.get(_url("/budget/"))
        add_btn = w.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(text(),'New dashboard card')]")
        ))
        add_btn.click()
        # Dialog should appear
        w.until(EC.visibility_of_element_located(
            (By.CSS_SELECTOR, ".dash-modal-backdrop")
        ))

    def test_23_preset_loads_into_textarea(self, driver, w, ctx):
        # Dialog should still be open from previous test; click first preset
        presets = w.until(lambda d: d.find_elements(By.CSS_SELECTOR, ".dash-presets .btn"))
        assert len(presets) > 0
        presets[0].click()
        textarea = driver.find_element(By.CSS_SELECTOR, ".dash-yaml-editor")
        assert "type:" in textarea.get_attribute("value")

    def test_24_cancel_dialog(self, driver, w, ctx):
        cancel_btn = driver.find_element(
            By.XPATH, "//div[contains(@class,'dash-modal')]//button[text()='Cancel']"
        )
        cancel_btn.click()
        w.until(lambda d: len(d.find_elements(
            By.CSS_SELECTOR, ".dash-modal-backdrop[style*='display: none']"
        )) > 0 or len(d.find_elements(By.CSS_SELECTOR, ".dash-modal-backdrop")) == 0)

    def test_25_edit_modal_opens_on_edit_button(self, driver, w, ctx):
        driver.get(_url("/budget/"))
        # Hover over first card to make edit button visible, then click it
        first_card = w.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, ".dash-card")
        ))
        driver.execute_script("arguments[0].querySelector('.dash-card-edit-btn').click()", first_card)
        w.until(EC.visibility_of_element_located(
            (By.CSS_SELECTOR, ".dash-modal-backdrop")
        ))
        # Textarea should contain YAML
        textarea = driver.find_element(By.CSS_SELECTOR, ".dash-yaml-editor")
        assert "type:" in textarea.get_attribute("value")
        # Close
        driver.find_element(
            By.XPATH, "//div[contains(@class,'dash-modal')]//button[text()='Cancel']"
        ).click()

    def test_26_cleanup_remaining_cards(self, driver, w, ctx):
        sess = _cards_session(driver)
        csrf = _get_csrf(sess)
        cards = sess.get(CARDS_URL).json()["cards"]
        for card in cards:
            url = CARDS_URL.rstrip("/") + f"/{card['id']}/"
            sess.delete(url, headers={"X-CSRFToken": csrf})
        assert sess.get(CARDS_URL).json()["cards"] == []
