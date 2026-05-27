"""
Scheduled expense materialization integrity: occurrence-identity dedup
(scheduled_occurrence_date), the once-per-financial-year last_run gate, and
the Gate A/B recurrence-rule locking (repeat_every_factor/unit and
repeat_base_date/end_on require explicit confirmation to change).
"""
import re
import time
from datetime import date, timedelta

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select

from helpers import (
    _url, click, fill, submit,
    api_get, api_post, api_patch, api_delete, run_cmd, server_today,
    setup_user, cleanup_user,
)


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


def _create_scheduled(ctx, **kwargs):
    body = {"type": "expense", "value": "10.00",
            "repeat_every_factor": 1, "repeat_every_unit": "months"}
    body.update(kwargs)
    resp = api_post("/api/v1/scheduled/", ctx, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _expenses_for(ctx, title):
    resp = api_get("/api/v1/expenses/", ctx, params={"view": "year"})
    assert resp.status_code == 200
    return [e for e in resp.json()["expenses"] if e["title"] == title]


def _last_run(sid) -> str:
    out = run_cmd("shell", "-c",
        f"from budget.models import ScheduledExpense; "
        f"s = ScheduledExpense.objects.get(uid={sid}); print(s.last_run)")
    return out.strip()


def _reset_last_run(sid):
    run_cmd("shell", "-c",
        f"from budget.models import ScheduledExpense; "
        f"s = ScheduledExpense.objects.get(uid={sid}); "
        f"s.last_run = None; s.save(update_fields=['last_run'])")


class TestOccurrenceIdentityRegression:
    """Regression coverage for the original bug this feature fixes: hand-editing
    a generated expense's date_due used to cause a duplicate on the next pass."""

    def test_hand_edited_date_due_survives_regeneration(self, driver, w, ctx):
        today = server_today()
        sid = _create_scheduled(ctx, title="Integrity Regression",
                                repeat_base_date=today, end_on=today)
        hits = _expenses_for(ctx, "Integrity Regression")
        assert len(hits) == 1
        eid = hits[0]["id"]

        new_due = (date.fromisoformat(today) + timedelta(days=1)).isoformat()
        resp = api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"date_due": new_due})
        assert resp.status_code == 200

        # Force a regeneration pass for this schedule, as a Gate B edit would.
        _reset_last_run(sid)
        run_cmd("generate_scheduled_expenses", "--user", ctx["email"])

        hits_after = _expenses_for(ctx, "Integrity Regression")
        assert len(hits_after) == 1, "hand-edited date_due must not cause a duplicate on regeneration"
        assert hits_after[0]["id"] == eid

        api_delete(f"/api/v1/expenses/{eid}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid}/", ctx)


class TestLastRunGate:

    def test_second_run_same_year_is_noop(self, driver, w, ctx):
        today = server_today()
        sid = _create_scheduled(ctx, title="Integrity LastRun",
                                repeat_base_date=today, end_on=today)
        hits = _expenses_for(ctx, "Integrity LastRun")
        assert len(hits) == 1
        run1 = _last_run(sid)
        assert run1 != "None"

        run_cmd("generate_scheduled_expenses", "--user", ctx["email"])

        hits_after = _expenses_for(ctx, "Integrity LastRun")
        assert len(hits_after) == 1
        assert hits_after[0]["id"] == hits[0]["id"]
        assert _last_run(sid) == run1

        api_delete(f"/api/v1/expenses/{hits[0]['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid}/", ctx)


class TestGateA:
    """repeat_every_factor / repeat_every_unit are locked behind confirm_modify_schedule."""

    def test_unconfirmed_tampered_change_is_discarded(self, driver, w, ctx):
        today = server_today()
        sid = _create_scheduled(ctx, title="GateA Unconfirmed",
                                repeat_base_date=today, end_on=today)
        hits = _expenses_for(ctx, "GateA Unconfirmed")
        assert len(hits) == 1
        eid_before = hits[0]["id"]

        resp = api_patch(f"/api/v1/scheduled/{sid}/", ctx, json={
            "repeat_every_factor": 2, "repeat_every_unit": "weeks",
        })
        assert resp.status_code == 200
        assert resp.json()["repeat_every_factor"] == 1
        assert resp.json()["repeat_every_unit"] == "months"

        hits_after = _expenses_for(ctx, "GateA Unconfirmed")
        assert len(hits_after) == 1
        assert hits_after[0]["id"] == eid_before

        api_delete(f"/api/v1/expenses/{eid_before}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid}/", ctx)

    def test_confirmed_change_wipes_and_regenerates_including_settled(self, driver, w, ctx):
        today = server_today()
        sid = _create_scheduled(ctx, title="GateA Confirmed",
                                repeat_base_date=today, end_on=today)
        hits = _expenses_for(ctx, "GateA Confirmed")
        assert len(hits) == 1
        old_eid = hits[0]["id"]
        api_patch(f"/api/v1/expenses/{old_eid}/", ctx, json={"settled": True})

        resp = api_patch(f"/api/v1/scheduled/{sid}/", ctx, json={
            "repeat_every_factor": 2, "repeat_every_unit": "weeks",
            "confirm_modify_schedule": True,
        })
        assert resp.status_code == 200
        assert resp.json()["repeat_every_factor"] == 2
        assert resp.json()["repeat_every_unit"] == "weeks"

        # Wiped unconditionally, even though it was settled.
        assert api_get(f"/api/v1/expenses/{old_eid}/", ctx).status_code == 404

        hits_after = _expenses_for(ctx, "GateA Confirmed")
        assert len(hits_after) == 1
        assert hits_after[0]["id"] != old_eid
        assert hits_after[0]["date_due"] == today

        api_delete(f"/api/v1/expenses/{hits_after[0]['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid}/", ctx)

    def test_confirmed_but_unchanged_is_noop(self, driver, w, ctx):
        today = server_today()
        sid = _create_scheduled(ctx, title="GateA Noop",
                                repeat_base_date=today, end_on=today)
        hits = _expenses_for(ctx, "GateA Noop")
        assert len(hits) == 1
        eid_before = hits[0]["id"]

        resp = api_patch(f"/api/v1/scheduled/{sid}/", ctx, json={
            "repeat_every_factor": 1, "repeat_every_unit": "months",
            "confirm_modify_schedule": True,
        })
        assert resp.status_code == 200

        hits_after = _expenses_for(ctx, "GateA Noop")
        assert len(hits_after) == 1
        assert hits_after[0]["id"] == eid_before, "no-op guard must not delete/recreate the row"

        api_delete(f"/api/v1/expenses/{eid_before}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid}/", ctx)


class TestGateB:
    """repeat_base_date / end_on are locked behind confirm_modify_schedule_window."""

    def test_confirmed_shrink_deletes_out_of_window_including_settled(self, driver, w, ctx):
        today = date.fromisoformat(server_today())
        end5 = (today + timedelta(days=5)).isoformat()
        sid = _create_scheduled(ctx, title="GateB Shrink",
                                repeat_base_date=today.isoformat(),
                                repeat_every_factor=1, repeat_every_unit="days",
                                end_on=end5)
        hits = _expenses_for(ctx, "GateB Shrink")
        assert len(hits) == 6  # today .. today+5 inclusive

        stale = sorted(hits, key=lambda e: e["date_due"])[-1]  # today+5
        api_patch(f"/api/v1/expenses/{stale['id']}/", ctx, json={"settled": True})

        end2 = (today + timedelta(days=2)).isoformat()
        resp = api_patch(f"/api/v1/scheduled/{sid}/", ctx, json={
            "end_on": end2, "confirm_modify_schedule_window": True,
        })
        assert resp.status_code == 200
        assert resp.json()["end_on"] == end2

        hits_after = _expenses_for(ctx, "GateB Shrink")
        assert len(hits_after) == 3  # today, +1, +2
        remaining_ids = {e["id"] for e in hits_after}
        kept_ids = {e["id"] for e in hits if e["date_due"] <= end2}
        assert remaining_ids == kept_ids
        assert stale["id"] not in remaining_ids
        assert api_get(f"/api/v1/expenses/{stale['id']}/", ctx).status_code == 404

        for e in hits_after:
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid}/", ctx)

    def test_confirmed_grow_adds_new_without_duplicating(self, driver, w, ctx):
        today = date.fromisoformat(server_today())
        end2 = (today + timedelta(days=2)).isoformat()
        sid = _create_scheduled(ctx, title="GateB Grow",
                                repeat_base_date=today.isoformat(),
                                repeat_every_factor=1, repeat_every_unit="days",
                                end_on=end2)
        hits = _expenses_for(ctx, "GateB Grow")
        assert len(hits) == 3  # today, +1, +2
        original_ids = {e["id"] for e in hits}

        end5 = (today + timedelta(days=5)).isoformat()
        resp = api_patch(f"/api/v1/scheduled/{sid}/", ctx, json={
            "end_on": end5, "confirm_modify_schedule_window": True,
        })
        assert resp.status_code == 200

        hits_after = _expenses_for(ctx, "GateB Grow")
        assert len(hits_after) == 6
        after_ids = {e["id"] for e in hits_after}
        assert original_ids <= after_ids, "growing the window must not recreate existing occurrences"

        for e in hits_after:
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid}/", ctx)

    def test_unconfirmed_window_change_is_discarded(self, driver, w, ctx):
        today = date.fromisoformat(server_today())
        end2 = (today + timedelta(days=2)).isoformat()
        sid = _create_scheduled(ctx, title="GateB Unconfirmed",
                                repeat_base_date=today.isoformat(),
                                repeat_every_factor=1, repeat_every_unit="days",
                                end_on=end2)
        hits = _expenses_for(ctx, "GateB Unconfirmed")
        assert len(hits) == 3
        ids_before = {e["id"] for e in hits}

        end5 = (today + timedelta(days=5)).isoformat()
        resp = api_patch(f"/api/v1/scheduled/{sid}/", ctx, json={"end_on": end5})
        assert resp.status_code == 200
        assert resp.json()["end_on"] == end2

        hits_after = _expenses_for(ctx, "GateB Unconfirmed")
        assert {e["id"] for e in hits_after} == ids_before

        for e in hits_after:
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid}/", ctx)


class TestAutoSettleOnCreate:

    def test_overdue_occurrences_created_settled(self, driver, w, ctx):
        today = date.fromisoformat(server_today())
        base = (today - timedelta(days=3)).isoformat()
        end = (today + timedelta(days=2)).isoformat()
        sid = _create_scheduled(ctx, title="Integrity AutoSettle",
                                repeat_base_date=base, repeat_every_factor=1,
                                repeat_every_unit="days", end_on=end,
                                default_auto_settle_on_due_date=True)
        hits = {e["date_due"]: e for e in _expenses_for(ctx, "Integrity AutoSettle")}
        assert len(hits) == 6

        for d, e in hits.items():
            expected_settled = d <= today.isoformat()
            assert e["settled"] is expected_settled, f"{d}: settled={e['settled']}, expected {expected_settled}"

        for e in hits.values():
            api_delete(f"/api/v1/expenses/{e['id']}/", ctx)
        api_delete(f"/api/v1/scheduled/{sid}/", ctx)


class TestLockedFieldsUI:

    def test_locked_fields_disabled_and_uncheck_reverts(self, driver, w, ctx):
        today = server_today()
        driver.get(_url("/budget/scheduled/new/"))
        time.sleep(1)
        fill(w, By.ID, "id_title", "Integrity UI Lock")
        fill(w, By.ID, "id_value", "20.00")
        Select(driver.find_element(By.ID, "id_type")).select_by_value("expense")
        fill(w, By.ID, "id_repeat_every_factor", "1")
        Select(driver.find_element(By.ID, "id_repeat_every_unit")).select_by_value("months")
        driver.execute_script(f"document.getElementById('id_repeat_base_date').value = '{today}';")
        submit(w)
        time.sleep(2)

        link = driver.find_element(By.XPATH,
            "//span[contains(text(),'Integrity UI Lock')]"
            "/ancestor::div[contains(@class,'exp-card')]"
            "//a[contains(@href,'/edit/')]"
        )
        sid = re.search(r"/scheduled/(\d+)/edit/", link.get_attribute("href")).group(1)
        driver.get(_url(f"/budget/scheduled/{sid}/edit/"))
        time.sleep(1)

        factor_el = driver.find_element(By.ID, "id_repeat_every_factor")
        assert factor_el.get_attribute("disabled")
        assert factor_el.get_attribute("value") == "1"

        # Check + cancel: field stays locked, checkbox reverts to unchecked
        click(w, By.ID, "id_confirm_modify_schedule")
        w.until(EC.element_to_be_clickable((By.ID, "cdialog-cancel"))).click()
        time.sleep(1)
        assert not driver.find_element(By.ID, "id_confirm_modify_schedule").is_selected()
        assert driver.find_element(By.ID, "id_repeat_every_factor").get_attribute("disabled")

        # Check + confirm: field unlocks
        click(w, By.ID, "id_confirm_modify_schedule")
        w.until(EC.element_to_be_clickable((By.ID, "cdialog-ok"))).click()
        time.sleep(1)
        assert not driver.find_element(By.ID, "id_repeat_every_factor").get_attribute("disabled")

        fill(w, By.ID, "id_repeat_every_factor", "9")
        assert driver.find_element(By.ID, "id_repeat_every_factor").get_attribute("value") == "9"

        # Unchecking reverts the in-progress edit back to the original value and re-disables
        click(w, By.ID, "id_confirm_modify_schedule")
        time.sleep(1)
        factor_el = driver.find_element(By.ID, "id_repeat_every_factor")
        assert factor_el.get_attribute("value") == "1"
        assert factor_el.get_attribute("disabled")

        api_delete(f"/api/v1/scheduled/{sid}/", ctx)
