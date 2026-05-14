"""
Notification system tests.

Covers:
- Initial notification class set on create (far, soon, tomorrow, today, late, settled)
- Due-date notification cron sends email and advances class
- Duplicate suppression on second cron run
- Settled notification sent when expense is settled via edit
- Email action links: settle-via-email, mute expense, mute all
- Respects email_notifications=False on the account
"""
import re
import time
from datetime import date, timedelta

import requests
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select as SeleniumSelect

from helpers import (
    BASE_URL, _url, fill, submit, api_get, api_post, api_patch, api_delete,
    extract_link, fetch_email, mailpit_seen_ids, run_cmd, server_today,
    setup_user, cleanup_user, session_cookies,
)

_today     = date.fromisoformat(server_today())
TODAY      = _today.isoformat()
YESTERDAY  = (_today - timedelta(days=1)).isoformat()
TOMORROW   = (_today + timedelta(days=1)).isoformat()
IN_3_DAYS  = (_today + timedelta(days=3)).isoformat()
IN_10_DAYS = (_today + timedelta(days=10)).isoformat()


def _mk(ctx, title, date_due, notify=True, settled=False, **kwargs):
    resp = api_post("/api/v1/expenses/", ctx, json={
        "title": title, "type": "expense", "value": "42.00",
        "date_due": date_due, "settled": settled, "notify": notify, **kwargs,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


def _get(ctx, eid):
    return api_get(f"/api/v1/expenses/{eid}/", ctx).json()


def _run_notify():
    return run_cmd("send_expense_notifications")


def _auth_session(driver) -> requests.Session:
    s = requests.Session()
    s.cookies.update(session_cookies(driver))
    return s



@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestInitialClass:

    def test_far_future_empty(self, driver, w, ctx):
        e = _mk(ctx, "NC Far", IN_10_DAYS)
        assert e["last_notification_class_sent"] == ""
        api_delete(f"/api/v1/expenses/{e['id']}/", ctx)

    def test_soon_class(self, driver, w, ctx):
        e = _mk(ctx, "NC Soon", IN_3_DAYS)
        assert e["last_notification_class_sent"] == "soon"
        api_delete(f"/api/v1/expenses/{e['id']}/", ctx)

    def test_tomorrow_class(self, driver, w, ctx):
        e = _mk(ctx, "NC Tomorrow", TOMORROW)
        assert e["last_notification_class_sent"] == "tomorrow"
        api_delete(f"/api/v1/expenses/{e['id']}/", ctx)

    def test_today_class(self, driver, w, ctx):
        e = _mk(ctx, "NC Today", TODAY)
        assert e["last_notification_class_sent"] == "today"
        api_delete(f"/api/v1/expenses/{e['id']}/", ctx)

    def test_late_class(self, driver, w, ctx):
        e = _mk(ctx, "NC Late", YESTERDAY)
        assert e["last_notification_class_sent"] == "late"
        api_delete(f"/api/v1/expenses/{e['id']}/", ctx)

    def test_settled_class(self, driver, w, ctx):
        e = _mk(ctx, "NC Settled", YESTERDAY, settled=True)
        assert e["last_notification_class_sent"] == "settled"
        api_delete(f"/api/v1/expenses/{e['id']}/", ctx)

    def test_edit_updates_class(self, driver, w, ctx):
        """Editing due date via web form updates last_notification_class_sent."""
        e = _mk(ctx, "NC Edit", IN_10_DAYS)
        eid = e["id"]
        assert e["last_notification_class_sent"] == ""
        driver.get(_url(f"/budget/expenses/{eid}/edit/"))
        time.sleep(1)
        driver.execute_script(f"document.getElementById('id_date_due').value = '{TOMORROW}';")
        submit(w)
        time.sleep(2)
        assert _get(ctx, eid)["last_notification_class_sent"] == "tomorrow"
        api_delete(f"/api/v1/expenses/{eid}/", ctx)


class TestCronNotifications:

    def test_soon_email_sent(self, driver, w, ctx):
        """Expense at class '' with due_date in 3 days: cron sends email, class advances to 'soon'."""
        e = _mk(ctx, "Cron Soon", IN_10_DAYS)
        eid = e["id"]
        # Patch due date without resetting class (API patch does not change class)
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"date_due": IN_3_DAYS})
        assert _get(ctx, eid)["last_notification_class_sent"] == ""
        seen = mailpit_seen_ids()
        _run_notify()
        time.sleep(1)
        assert _get(ctx, eid)["last_notification_class_sent"] == "soon"
        fetch_email(ctx["email"], "Payment due in", timeout=30, ignore_ids=seen)
        ctx["cron_soon_eid"] = eid

    def test_no_duplicate_on_second_run(self, driver, w, ctx):
        seen = mailpit_seen_ids()
        _run_notify()
        time.sleep(1)
        assert _get(ctx, ctx["cron_soon_eid"])["last_notification_class_sent"] == "soon"
        new_msgs = {
            m["ID"] for m in
            requests.get("http://localhost:8030/api/v1/messages", timeout=5)
            .json().get("messages", [])
        }
        assert not (new_msgs - seen), "Second cron run must not send a duplicate email"
        api_delete(f"/api/v1/expenses/{ctx.pop('cron_soon_eid')}/", ctx)


class TestSettledNotification:

    def test_settled_via_edit_sends_email(self, driver, w, ctx):
        """Editing an unsettled expense to settled=True sends a settled notification."""
        e = _mk(ctx, "Settled Edit", IN_3_DAYS)
        eid = e["id"]
        seen = mailpit_seen_ids()
        driver.get(_url(f"/budget/expenses/{eid}/edit/"))
        time.sleep(1)
        cb = driver.find_element(By.ID, "id_settled")
        if not cb.is_selected():
            cb.click()
            time.sleep(0.1)
        submit(w)
        time.sleep(2)
        fetch_email(ctx["email"], "settled", timeout=30, ignore_ids=seen)
        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_no_notification_when_disabled(self, driver, w, ctx):
        """email_notifications=False: cron sends no email."""
        api_patch("/api/v1/account/", ctx, json={"email_notifications": False})
        e = _mk(ctx, "NoNotify", IN_10_DAYS)
        eid = e["id"]
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"date_due": IN_3_DAYS})
        seen = mailpit_seen_ids()
        _run_notify()
        time.sleep(2)
        new_msgs = {
            m["ID"] for m in
            requests.get("http://localhost:8030/api/v1/messages", timeout=5)
            .json().get("messages", [])
        }
        assert not (new_msgs - seen), "No notification expected when email_notifications=False"
        api_delete(f"/api/v1/expenses/{eid}/", ctx)
        api_patch("/api/v1/account/", ctx, json={"email_notifications": True})


class TestEmailActions:

    def _trigger_soon_email(self, ctx, title):
        """Create expense at class '', patch to IN_3_DAYS, run cron. Returns (eid, email_body)."""
        e = _mk(ctx, title, IN_10_DAYS)
        eid = e["id"]
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"date_due": IN_3_DAYS})
        seen = mailpit_seen_ids()
        _run_notify()
        time.sleep(1)
        body = fetch_email(ctx["email"], "Payment due in", timeout=30, ignore_ids=seen)
        return eid, body

    def _find_link(self, body, keyword):
        # Extract from href attributes first (HTML emails), fall back to bare URLs.
        candidates = re.findall(r'href=["\']?(https?://[^"\'>\s]+)', body)
        if not candidates:
            candidates = [raw.rstrip('.,)"\'>')
                          for raw in re.findall(r'https?://\S+', body)]
        for url in candidates:
            if keyword in url:
                return re.sub(r'https?://[^/]+', BASE_URL, url)
        return None

    def test_settle_via_email_link(self, driver, w, ctx):
        """Clicking the settle-via-email link settles the expense."""
        eid, body = self._trigger_soon_email(ctx, "SettleLink")
        settle_link = self._find_link(body, "settle-via-email")
        if settle_link:
            s = _auth_session(driver)
            s.get(settle_link, timeout=10, allow_redirects=True)
            time.sleep(1)
            assert _get(ctx, eid)["settled"] is True
        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_mute_expense_link(self, driver, w, ctx):
        """Muting an expense via the email link sets notify=False."""
        eid, body = self._trigger_soon_email(ctx, "MuteTest")
        mute_link = self._find_link(body, "mute-notifications")
        if mute_link:
            s = _auth_session(driver)
            csrf = next((c.value for c in s.cookies if c.name == "csrftoken"), "")
            s.post(mute_link, data={"csrfmiddlewaretoken": csrf},
                   headers={"Referer": BASE_URL + "/"})
            time.sleep(1)
            assert _get(ctx, eid)["notify"] is False
        api_delete(f"/api/v1/expenses/{eid}/", ctx)


class TestEditClassBack:

    def test_edit_moves_class_back_when_date_pushed_far(self, driver, w, ctx):
        """Editing due date to far future resets last_notification_class_sent to ''."""
        e = _mk(ctx, "NC EditBack", TOMORROW)
        eid = e["id"]
        assert e["last_notification_class_sent"] == "tomorrow"
        driver.get(_url(f"/budget/expenses/{eid}/edit/"))
        time.sleep(1)
        driver.execute_script(f"document.getElementById('id_date_due').value = '{IN_10_DAYS}';")
        submit(w)
        time.sleep(2)
        assert _get(ctx, eid)["last_notification_class_sent"] == ""
        api_delete(f"/api/v1/expenses/{eid}/", ctx)


class TestCronSequence:

    def test_tomorrow_notification_fires(self, driver, w, ctx):
        """When class is 'soon' and due date becomes tomorrow, cron sends 'tomorrow'."""
        e = _mk(ctx, "CronSeq Soon", IN_10_DAYS)
        eid = e["id"]
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"date_due": IN_3_DAYS})
        assert _get(ctx, eid)["last_notification_class_sent"] == ""
        seen = mailpit_seen_ids()
        _run_notify()
        time.sleep(1)
        assert _get(ctx, eid)["last_notification_class_sent"] == "soon"
        fetch_email(ctx["email"], "Payment due in", timeout=30, ignore_ids=seen)

        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"date_due": TOMORROW})
        seen2 = mailpit_seen_ids()
        _run_notify()
        time.sleep(1)
        assert _get(ctx, eid)["last_notification_class_sent"] == "tomorrow"
        fetch_email(ctx["email"], "Payment due tomorrow", timeout=30, ignore_ids=seen2)
        ctx["cron_seq_eid"] = eid

    def test_today_notification_fires(self, driver, w, ctx):
        """When class is 'tomorrow' and due date reaches today, cron sends 'today'."""
        eid = ctx["cron_seq_eid"]
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"date_due": TODAY})
        seen = mailpit_seen_ids()
        _run_notify()
        time.sleep(1)
        assert _get(ctx, eid)["last_notification_class_sent"] == "today"
        fetch_email(ctx["email"], "Payment due today", timeout=30, ignore_ids=seen)

    def test_late_notification_fires(self, driver, w, ctx):
        """When class is 'today' and due date passes, cron sends 'late'."""
        eid = ctx["cron_seq_eid"]
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"date_due": YESTERDAY})
        seen = mailpit_seen_ids()
        _run_notify()
        time.sleep(1)
        assert _get(ctx, eid)["last_notification_class_sent"] == "late"
        fetch_email(ctx["email"], "Payment overdue", timeout=30, ignore_ids=seen)
        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_no_notification_when_expense_muted(self, driver, w, ctx):
        """Expense with notify=False receives no notification from cron."""
        e = _mk(ctx, "MutedExpense", IN_10_DAYS, notify=False)
        eid = e["id"]
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"date_due": IN_3_DAYS})
        _run_notify()
        time.sleep(1)
        assert _get(ctx, eid)["last_notification_class_sent"] == ""
        api_delete(f"/api/v1/expenses/{eid}/", ctx)


class TestSettledNotifications:

    def test_settled_on_auto_settle(self, driver, w, ctx):
        """auto_settle_expenses sends 'settled' notification."""
        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "AutoSettle Notify", "type": "expense", "value": "5.00",
            "date_due": YESTERDAY, "settled": False,
            "auto_settle_on_due_date": True, "notify": True,
        })
        assert resp.status_code == 201
        eid = resp.json()["id"]
        seen = mailpit_seen_ids()
        run_cmd("auto_settle_expenses")
        time.sleep(1)
        exp = _get(ctx, eid)
        assert exp["settled"] is True
        assert exp["last_notification_class_sent"] == "settled"
        fetch_email(ctx["email"], "Payment marked as paid", timeout=30, ignore_ids=seen)
        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_no_settled_notification_on_create_already_settled(self, driver, w, ctx):
        """Creating an expense with settled=True does NOT send a settled email."""
        msgs_before = requests.get("http://localhost:8030/api/v1/messages", timeout=5).json().get("messages", [])
        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "CreateSettled NoNotify", "type": "expense", "value": "1.00",
            "date_due": TODAY, "settled": True,
        })
        assert resp.status_code == 201
        eid = resp.json()["id"]
        time.sleep(2)
        msgs_after = requests.get("http://localhost:8030/api/v1/messages", timeout=5).json().get("messages", [])
        new_settled = [m for m in msgs_after
                       if m.get("ID") not in {x.get("ID") for x in msgs_before}
                       and "CreateSettled" in m.get("Subject", "")
                       and "marked as paid" in m.get("Subject", "")]
        assert len(new_settled) == 0
        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_no_settled_on_bulk_2_plus(self, driver, w, ctx):
        """Bulk settle with 2+ expenses does NOT send settled notifications."""
        a = api_post("/api/v1/expenses/", ctx, json={
            "title": "BulkNoNotify A", "type": "expense", "value": "1.00",
            "date_due": IN_3_DAYS, "settled": False,
        })
        b = api_post("/api/v1/expenses/", ctx, json={
            "title": "BulkNoNotify B", "type": "expense", "value": "1.00",
            "date_due": IN_3_DAYS, "settled": False,
        })
        assert a.status_code == 201 and b.status_code == 201
        eid_a, eid_b = a.json()["id"], b.json()["id"]
        msgs_before = requests.get("http://localhost:8030/api/v1/messages", timeout=5).json().get("messages", [])
        # Bulk settle via browser
        driver.get(_url("/budget/expenses/"))
        time.sleep(2)
        search_el = driver.find_element(By.ID, "exp-search")
        driver.execute_script(
            "arguments[0].value=arguments[1];"
            "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));",
            search_el, "BulkNoNotify",
        )
        time.sleep(2)
        driver.find_element(By.ID, "exp-select-all").click()
        time.sleep(0.3)
        SeleniumSelect(driver.find_element(By.ID, "exp-bulk-action")).select_by_value("settle")
        driver.find_element(By.ID, "exp-bulk-go").click()
        time.sleep(0.5)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(2)
        msgs_after = requests.get("http://localhost:8030/api/v1/messages", timeout=5).json().get("messages", [])
        new_settled = [m for m in msgs_after
                       if m.get("ID") not in {x.get("ID") for x in msgs_before}
                       and "marked as paid" in m.get("Subject", "")]
        assert len(new_settled) == 0
        api_delete(f"/api/v1/expenses/{eid_a}/", ctx)
        api_delete(f"/api/v1/expenses/{eid_b}/", ctx)

    def test_settled_on_bulk_exactly_1(self, driver, w, ctx):
        """Bulk settle with exactly 1 expense DOES send settled notification."""
        e = _mk(ctx, "BulkNotify Single", IN_3_DAYS)
        eid = e["id"]
        seen = mailpit_seen_ids()
        # Bulk settle via browser
        driver.get(_url("/budget/expenses/"))
        time.sleep(2)
        search_el = driver.find_element(By.ID, "exp-search")
        driver.execute_script(
            "arguments[0].value=arguments[1];"
            "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));",
            search_el, "BulkNotify Single",
        )
        time.sleep(2)
        driver.find_element(By.ID, "exp-select-all").click()
        time.sleep(0.3)
        SeleniumSelect(driver.find_element(By.ID, "exp-bulk-action")).select_by_value("settle")
        driver.find_element(By.ID, "exp-bulk-go").click()
        time.sleep(0.5)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(2)
        exp = _get(ctx, eid)
        assert exp["settled"] is True
        assert exp["last_notification_class_sent"] == "settled"
        fetch_email(ctx["email"], "Payment marked as paid", timeout=30, ignore_ids=seen)
        api_delete(f"/api/v1/expenses/{eid}/", ctx)


class TestMuteAll:

    def _trigger_soon_email(self, ctx, title):
        e = _mk(ctx, title, IN_10_DAYS)
        eid = e["id"]
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"date_due": IN_3_DAYS})
        seen = mailpit_seen_ids()
        run_cmd("send_expense_notifications")
        time.sleep(1)
        body = fetch_email(ctx["email"], "Payment due in", timeout=30, ignore_ids=seen)
        return eid, body

    def _find_link(self, body, keyword):
        # Extract from href attributes first (HTML emails), fall back to bare URLs.
        candidates = re.findall(r'href=["\']?(https?://[^"\'>\s]+)', body)
        if not candidates:
            candidates = [raw.rstrip('.,)"\'>')
                          for raw in re.findall(r'https?://\S+', body)]
        for url in candidates:
            if keyword in url:
                return re.sub(r'https?://[^/]+', BASE_URL, url)
        return None

    def test_mute_all_via_link(self, driver, w, ctx):
        """Clicking the mute-all link disables email_notifications on the account."""
        api_patch("/api/v1/account/", ctx, json={"email_notifications": True})
        eid, body = self._trigger_soon_email(ctx, "MuteAllTest")
        mute_all_link = self._find_link(body, "mute-all")
        if mute_all_link:
            s = _auth_session(driver)
            s.get(mute_all_link, timeout=10, allow_redirects=True)
            time.sleep(1)
            account = api_get("/api/v1/account/", ctx).json()
            assert account["email_notifications"] is False
        api_delete(f"/api/v1/expenses/{eid}/", ctx)
        api_patch("/api/v1/account/", ctx, json={"email_notifications": True})


class TestAutoSettleAndApiSettled:

    def test_auto_settle_no_due_notification(self, driver, w, ctx):
        """auto_settle_on_due_date expenses get no due-date notifications from cron."""
        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "AutoSettle NoDueNotif", "type": "expense", "value": "5.00",
            "date_due": IN_10_DAYS, "settled": False,
            "auto_settle_on_due_date": True, "notify": True,
        })
        assert resp.status_code == 201
        eid = resp.json()["id"]
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"date_due": IN_3_DAYS})
        assert _get(ctx, eid)["last_notification_class_sent"] == ""
        run_cmd("send_expense_notifications")
        time.sleep(1)
        assert _get(ctx, eid)["last_notification_class_sent"] == ""
        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_auto_settle_sends_settled_for_due_today(self, driver, w, ctx):
        """auto_settle_expenses sends settled notification when due date is today."""
        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "AutoSettle DueToday", "type": "expense", "value": "3.00",
            "date_due": TODAY, "settled": False,
            "auto_settle_on_due_date": True, "notify": True,
        })
        assert resp.status_code == 201
        eid = resp.json()["id"]
        seen = mailpit_seen_ids()
        run_cmd("auto_settle_expenses")
        time.sleep(1)
        exp = _get(ctx, eid)
        assert exp["settled"] is True
        assert exp["last_notification_class_sent"] == "settled"
        fetch_email(ctx["email"], "Payment marked as paid", timeout=30, ignore_ids=seen)
        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_auto_settle_no_settled_for_old_due(self, driver, w, ctx):
        """auto_settle_expenses does NOT send settled notification for old due dates."""
        long_ago = (date.fromisoformat(TODAY) - timedelta(days=10)).isoformat()
        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "AutoSettle OldDue", "type": "expense", "value": "7.00",
            "date_due": long_ago, "settled": False,
            "auto_settle_on_due_date": True, "notify": True,
        })
        assert resp.status_code == 201
        eid = resp.json()["id"]
        msgs_before = requests.get("http://localhost:8030/api/v1/messages", timeout=5).json().get("messages", [])
        run_cmd("auto_settle_expenses")
        time.sleep(2)
        assert _get(ctx, eid)["settled"] is True
        msgs_after = requests.get("http://localhost:8030/api/v1/messages", timeout=5).json().get("messages", [])
        new_settled = [m for m in msgs_after
                       if m.get("ID") not in {x.get("ID") for x in msgs_before}
                       and "OldDue" in m.get("Subject", "")]
        assert len(new_settled) == 0
        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_settled_via_api_patch_sends_notification(self, driver, w, ctx):
        """API PATCH settled=False -> True sends settled notification."""
        e = _mk(ctx, "ApiPatch Settle", IN_3_DAYS)
        eid = e["id"]
        seen = mailpit_seen_ids()
        resp = api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"settled": True})
        assert resp.status_code == 200
        time.sleep(1)
        exp = _get(ctx, eid)
        assert exp["settled"] is True
        assert exp["last_notification_class_sent"] == "settled"
        fetch_email(ctx["email"], "Payment marked as paid", timeout=30, ignore_ids=seen)
        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_no_settled_when_profile_off(self, driver, w, ctx):
        """No settled notification when email_notifications=False."""
        api_patch("/api/v1/account/", ctx, json={"email_notifications": False})
        e = _mk(ctx, "ApiSettle ProfileOff", IN_3_DAYS)
        eid = e["id"]
        msgs_before = requests.get("http://localhost:8030/api/v1/messages", timeout=5).json().get("messages", [])
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"settled": True})
        time.sleep(2)
        msgs_after = requests.get("http://localhost:8030/api/v1/messages", timeout=5).json().get("messages", [])
        new_msgs = [m for m in msgs_after
                    if m.get("ID") not in {x.get("ID") for x in msgs_before}
                    and "ProfileOff" in m.get("Subject", "")]
        assert len(new_msgs) == 0
        api_patch("/api/v1/account/", ctx, json={"email_notifications": True})
        api_delete(f"/api/v1/expenses/{eid}/", ctx)

    def test_no_settled_when_expense_muted(self, driver, w, ctx):
        """No settled notification when expense.notify=False."""
        e = _mk(ctx, "ApiSettle ExpenseMuted", IN_3_DAYS, notify=False)
        eid = e["id"]
        msgs_before = requests.get("http://localhost:8030/api/v1/messages", timeout=5).json().get("messages", [])
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"settled": True})
        time.sleep(2)
        msgs_after = requests.get("http://localhost:8030/api/v1/messages", timeout=5).json().get("messages", [])
        new_msgs = [m for m in msgs_after
                    if m.get("ID") not in {x.get("ID") for x in msgs_before}
                    and "ExpenseMuted" in m.get("Subject", "")]
        assert len(new_msgs) == 0
        api_delete(f"/api/v1/expenses/{eid}/", ctx)
