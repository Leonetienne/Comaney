"""Scheduled expense CRUD via browser."""
import re
import time

import pytest
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support import expected_conditions as EC

from helpers import (
    _url, fill, submit, wait_url, wait_text, server_today,
    api_get, api_post, api_delete,
    setup_user, cleanup_user,
)


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestScheduled:

    def test_create(self, driver, w, ctx):
        today = server_today()
        driver.get(_url("/budget/scheduled/new/"))
        fill(w, By.ID, "id_title", "E2E Scheduled")
        fill(w, By.ID, "id_value", "99.00")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("expense")
        fill(w, By.ID, "id_repeat_every_factor", "1")
        Select(driver.find_element(By.ID, "id_repeat_every_unit")).select_by_value("months")
        driver.execute_script(
            f"document.getElementById('id_repeat_base_date').value = '{today}';")
        submit(w)
        wait_url(w, "/budget/scheduled/")
        wait_text(driver, w, "E2E Scheduled")

    def test_edit(self, driver, w, ctx):
        link = w.until(EC.element_to_be_clickable(
            (By.XPATH, "//span[contains(text(),'E2E Scheduled')]"
                       "/ancestor::div[contains(@class,'exp-card')]"
                       "//a[contains(@href,'/edit/')]")))
        ctx["sched_uid"] = re.search(r'/scheduled/(\d+)/edit/', link.get_attribute("href")).group(1)
        link.click()
        fill(w, By.ID, "id_title", "E2E Scheduled Edited")
        submit(w)
        wait_url(w, "/budget/scheduled/")
        wait_text(driver, w, "E2E Scheduled Edited")

    def test_clone(self, driver, w, ctx):
        clone_btn = w.until(EC.element_to_be_clickable(
            (By.XPATH,
             f"//form[contains(@action,'/scheduled/{ctx['sched_uid']}/clone/')]//button")))
        clone_btn.click()
        wait_url(w, "/edit/")
        w.until(lambda d: "CLONE - E2E Scheduled Edited" in
                d.find_element(By.ID, "id_title").get_attribute("value"))
        ctx["clone_uid"] = re.search(r'/scheduled/(\d+)/edit/', driver.current_url).group(1)
        submit(w)
        wait_url(w, "/budget/scheduled/")

    def test_delete_clone(self, driver, w, ctx):
        delete_form = w.until(EC.presence_of_element_located(
            (By.XPATH, f"//form[contains(@action,'/scheduled/{ctx['clone_uid']}/delete/')]")))
        driver.execute_script("arguments[0].querySelector('button').click()", delete_form)
        w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok"))).click()
        wait_url(w, "/budget/scheduled/")
        wait_text(driver, w, "E2E Scheduled Edited")


class TestScheduledAllFields:

    def test_all_fields_round_trip(self, driver, w, ctx):
        today = server_today()
        driver.get(_url("/budget/scheduled/new/"))
        time.sleep(1)
        fill(w, By.ID, "id_title", "E2E Sched Full")
        fill(w, By.ID, "id_value", "123.45")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("income")
        fill(w, By.ID, "id_repeat_every_factor", "2")
        Select(driver.find_element(By.ID, "id_repeat_every_unit")).select_by_value("weeks")
        fill(w, By.ID, "id_payee", "Sched Payee")
        fill(w, By.ID, "id_note", "Sched note")
        driver.execute_script(
            f"document.getElementById('id_repeat_base_date').value = '{today}';"
            "document.getElementById('id_default_auto_settle_on_due_date').checked = true;"
        )
        submit(w)
        time.sleep(2)
        assert "E2E Sched Full" in driver.page_source
        # Find the edit link from the list and verify all fields round-trip
        link = driver.find_element(By.XPATH,
            "//span[contains(text(),'E2E Sched Full')]"
            "/ancestor::div[contains(@class,'exp-card')]"
            "//a[contains(@href,'/edit/')]"
        )
        sid = re.search(r"/scheduled/(\d+)/edit/", link.get_attribute("href")).group(1)
        driver.get(_url(f"/budget/scheduled/{sid}/edit/"))
        time.sleep(1)
        assert driver.find_element(By.ID, "id_title").get_attribute("value") == "E2E Sched Full"
        assert driver.find_element(By.ID, "id_value").get_attribute("value") == "123.45"
        assert driver.find_element(By.ID, "id_payee").get_attribute("value") == "Sched Payee"
        assert driver.find_element(By.ID, "id_note").get_attribute("value") == "Sched note"
        assert driver.find_element(By.ID, "id_default_auto_settle_on_due_date").is_selected()
        assert Select(driver.find_element(By.ID, "id_type")).first_selected_option.get_attribute("value") == "income"
        assert Select(driver.find_element(By.ID, "id_repeat_every_unit")).first_selected_option.get_attribute("value") == "weeks"
        api_delete(f"/api/v1/scheduled/{sid}/", ctx)


class TestScheduledDoubleSubmitGuard:
    """Verify that posting a consumed nonce does not create a duplicate scheduled expense."""

    def test_back_resubmit_creates_only_one_scheduled(self, ctx):
        import re as _re

        s = requests.Session()
        today = server_today()
        title = "E2E NoDupScheduled"

        # --- authenticate ---
        r = s.get(_url("/login/"))
        assert r.status_code == 200
        csrf = s.cookies.get("csrftoken", "")
        r = s.post(_url("/login/"), data={
            "csrfmiddlewaretoken": csrf,
            "email": ctx["email"],
            "password": ctx["password"],
        }, allow_redirects=True)
        assert "/budget/" in r.url, f"Login did not redirect to /budget/; landed at {r.url}"

        # --- load the form and capture the one-time nonce ---
        r = s.get(_url("/budget/scheduled/new/"))
        assert r.status_code == 200
        m = _re.search(r'name="form_nonce"\s+value="([^"]+)"', r.text)
        assert m, "form_nonce hidden input not found in scheduled form HTML"
        stale_nonce = m.group(1)
        csrf = s.cookies.get("csrftoken", csrf)

        post_data = {
            "csrfmiddlewaretoken": csrf,
            "form_nonce": stale_nonce,
            "title": title,
            "value": "5.00",
            "type": "expense",
            "repeat_every_factor": "1",
            "repeat_every_unit": "months",
            "repeat_base_date": today,
        }

        # --- first POST: creates the scheduled expense and consumes the nonce ---
        r = s.post(_url("/budget/scheduled/new/"), data=post_data, allow_redirects=False)
        assert r.status_code in (301, 302), f"First POST returned {r.status_code}"

        # --- second POST: replay the consumed nonce (back + resubmit) ---
        post_data["title"] = title + " DUPE"
        r = s.post(_url("/budget/scheduled/new/"), data=post_data, allow_redirects=False)
        assert r.status_code in (301, 302), f"Second POST returned {r.status_code}"

        # --- assert only one scheduled expense was created ---
        resp = api_get("/api/v1/scheduled/", ctx)
        assert resp.status_code == 200
        all_scheduled = resp.json()["scheduled"]
        dupes = [e for e in all_scheduled if "DUPE" in e["title"]]
        assert dupes == [], f"Duplicate scheduled expense was created: {dupes}"
        originals = [e for e in all_scheduled if e["title"] == title]
        assert len(originals) == 1, f"Expected 1 original, found {len(originals)}"
        api_delete(f"/api/v1/scheduled/{originals[0]['id']}/", ctx)


class TestScheduledImmediateGeneration:
    """Creating or editing a scheduled expense must generate expenses immediately,
    without waiting for the next cron run."""

    def test_create_generates_expenses_immediately(self, ctx):
        """Saving a new scheduled expense triggers generate_scheduled_expenses for
        this user right away; expenses appear in the API without running run_cmd."""
        today = server_today()
        title = "E2E ImmGen Create"

        sid = api_post("/api/v1/scheduled/", ctx, json={
            "title": title,
            "type": "expense",
            "value": "42.00",
            "repeat_every_factor": 1,
            "repeat_every_unit": "months",
            "repeat_base_date": today,
        }).json()["id"]

        resp = api_get("/api/v1/expenses/", ctx)
        assert resp.status_code == 200
        hits = [e for e in resp.json()["expenses"] if e["title"] == title]
        assert len(hits) >= 1, "Expected at least one generated expense immediately after saving scheduled"

        for e in hits:
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid}/", ctx)

    def test_create_via_gui_generates_expenses_immediately(self, driver, w, ctx):
        """Saving a new scheduled expense via the browser form generates expenses immediately."""
        today = server_today()
        title = "E2E ImmGen GUI Create"

        driver.get(_url("/budget/scheduled/new/"))
        fill(w, By.ID, "id_title", title)
        fill(w, By.ID, "id_value", "15.00")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("expense")
        fill(w, By.ID, "id_repeat_every_factor", "1")
        Select(driver.find_element(By.ID, "id_repeat_every_unit")).select_by_value("months")
        driver.execute_script(f"document.getElementById('id_repeat_base_date').value = '{today}';")
        submit(w)
        wait_url(w, "/budget/scheduled/")

        resp = api_get("/api/v1/expenses/", ctx)
        assert resp.status_code == 200
        hits = [e for e in resp.json()["expenses"] if e["title"] == title]
        assert len(hits) >= 1, "Expected at least one generated expense immediately after saving via GUI"

        for e in hits:
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        all_sched = api_get("/api/v1/scheduled/", ctx).json()["scheduled"]
        for s in [s for s in all_sched if s["title"] == title]:
            api_delete(f"/api/v1/scheduled/{s['id']}/", ctx)

    def test_edit_generates_new_expenses_immediately(self, ctx):
        """Editing a scheduled expense (e.g. changing the base date) triggers
        generation immediately; the new occurrence appears without running run_cmd."""
        today = server_today()
        title = "E2E ImmGen Edit"

        # Create with a far-future base date so no expenses are generated yet
        sid = api_post("/api/v1/scheduled/", ctx, json={
            "title": title,
            "type": "expense",
            "value": "7.00",
            "repeat_every_factor": 1,
            "repeat_every_unit": "years",
            "repeat_base_date": "2099-01-01",
        }).json()["id"]

        hits_before = [e for e in api_get("/api/v1/expenses/", ctx).json()["expenses"]
                       if e["title"] == title]
        assert hits_before == [], "Should be no expenses before edit"

        # Edit: move base date to today so it falls inside the current financial year
        s = requests.Session()
        r = s.get(_url("/login/"))
        csrf = s.cookies.get("csrftoken", "")
        s.post(_url("/login/"), data={
            "csrfmiddlewaretoken": csrf,
            "email": ctx["email"],
            "password": ctx["password"],
        }, allow_redirects=True)

        r = s.get(_url(f"/budget/scheduled/{sid}/edit/"))
        csrf = s.cookies.get("csrftoken", csrf)
        m = re.search(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', r.text)
        if m:
            csrf = m.group(1)

        s.post(_url(f"/budget/scheduled/{sid}/edit/"), data={
            "csrfmiddlewaretoken": csrf,
            "title": title,
            "type": "expense",
            "value": "7.00",
            "repeat_every_factor": "1",
            "repeat_every_unit": "years",
            "repeat_base_date": today,
        }, allow_redirects=False)

        hits_after = [e for e in api_get("/api/v1/expenses/", ctx).json()["expenses"]
                      if e["title"] == title]
        assert len(hits_after) >= 1, "Expected at least one generated expense immediately after editing scheduled"

        for e in hits_after:
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid}/", ctx)
