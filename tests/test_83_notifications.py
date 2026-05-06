"""
Expense notification system tests.

Covers:
- Initial notification class set on create/edit
- Due-date notifications via send_expense_notifications cron
- Duplicate suppression
- Settled notification (auto-settle, edit, single bulk action)
- No settled notification for bulk with 2+ items or on initial create-settled
- Email action links: settle-via-email, mute expense, mute all
- Respects feuser.email_notifications=False
"""
import time
from datetime import date, timedelta

import requests

from conftest import (
    BASE_URL, api_delete, api_get, api_patch, api_post,
    extract_link, fetch_email, mailpit_seen_ids, run_cmd, server_today,
)

_today     = date.fromisoformat(server_today())
TODAY      = _today.isoformat()
YESTERDAY  = (_today - timedelta(days=1)).isoformat()
TOMORROW   = (_today + timedelta(days=1)).isoformat()
IN_3_DAYS  = (_today + timedelta(days=3)).isoformat()
IN_10_DAYS = (_today + timedelta(days=10)).isoformat()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_unsettled(ctx, title, date_due, notify=True, **kwargs):
    resp = api_post("/api/v1/expenses/", ctx, json={
        "title": title, "type": "expense", "value": "42.00",
        "date_due": date_due, "settled": False, "notify": notify, **kwargs,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


def _get_expense(ctx, eid):
    resp = api_get(f"/api/v1/expenses/{eid}/", ctx)
    assert resp.status_code == 200
    return resp.json()


def _run_notify():
    return run_cmd("send_expense_notifications")


def _run_auto_settle():
    return run_cmd("auto_settle_expenses")


def _auth_session(driver):
    """requests.Session carrying the driver's session cookies (no domain restriction)."""
    s = requests.Session()
    s.cookies.update({c["name"]: c["value"] for c in driver.get_cookies()})
    return s


def _post_form(driver, url, data):
    """
    POST a Django form using the driver's session.
    GETs the expenses list page first to obtain a fresh masked CSRF token from
    the server (Django 5 stores a masked value in cookies; the form field is a
    different masked version of the same secret, so we must extract it from HTML).
    For POST-only endpoints the expenses list provides the token.
    """
    import re
    s = _auth_session(driver)
    # Use the edit page if it's a GET-able endpoint, otherwise the new-expense form
    # (always has a CSRF token regardless of data state).
    token_page = url if url.endswith("/edit/") else f"{BASE_URL}/budget/expenses/new/"
    page = s.get(token_page)
    m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.text)
    csrf = m.group(1) if m else ""
    return s.post(url, data=dict(data, csrfmiddlewaretoken=csrf),
                  headers={"Referer": BASE_URL + "/"}, allow_redirects=False)


def _fetch_notification_email(ctx, subject_fragment, timeout=30, ignore_ids=None):
    """Poll mailpit for a notification email to the test user."""
    email_addr = ctx.get("email", "")
    return fetch_email(email_addr, subject_fragment, timeout=timeout, ignore_ids=ignore_ids)


# ---------------------------------------------------------------------------
# 1. Initial notification class on create / edit
# ---------------------------------------------------------------------------

class TestInitialNotificationClass:

    def test_83_00_create_far_future_class_empty(self, driver, w, ctx):
        """Expense due in 10 days gets last_notification_class_sent = ''."""
        d = _create_unsettled(ctx, "NotifyClass Far", IN_10_DAYS)
        eid = d["id"]
        ctx["nc_far_eid"] = eid
        assert _get_expense(ctx, eid)["last_notification_class_sent"] == ""

    def test_83_01_create_soon_class_soon(self, driver, w, ctx):
        """Expense due in 3 days gets last_notification_class_sent = 'soon'."""
        d = _create_unsettled(ctx, "NotifyClass Soon", IN_3_DAYS)
        eid = d["id"]
        ctx["nc_soon_eid"] = eid
        assert _get_expense(ctx, eid)["last_notification_class_sent"] == "soon"

    def test_83_02_create_tomorrow_class_tomorrow(self, driver, w, ctx):
        """Expense due tomorrow gets last_notification_class_sent = 'tomorrow'."""
        d = _create_unsettled(ctx, "NotifyClass Tomorrow", TOMORROW)
        eid = d["id"]
        ctx["nc_tomorrow_eid"] = eid
        assert _get_expense(ctx, eid)["last_notification_class_sent"] == "tomorrow"

    def test_83_03_create_past_class_late(self, driver, w, ctx):
        """Expense due yesterday gets last_notification_class_sent = 'late'."""
        d = _create_unsettled(ctx, "NotifyClass Late", YESTERDAY)
        eid = d["id"]
        ctx["nc_late_eid"] = eid
        assert _get_expense(ctx, eid)["last_notification_class_sent"] == "late"

    def test_83_04_create_settled_class_settled(self, driver, w, ctx):
        """Already-settled expense gets last_notification_class_sent = 'settled'."""
        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "NotifyClass Settled", "type": "expense", "value": "1.00",
            "date_due": YESTERDAY, "settled": True,
        })
        assert resp.status_code == 201
        eid = resp.json()["id"]
        ctx["nc_settled_eid"] = eid
        assert _get_expense(ctx, eid)["last_notification_class_sent"] == "settled"

    def test_83_05_edit_moves_class_forward(self, driver, w, ctx):
        """
        Editing an expense with a far-future due date to a near date updates
        last_notification_class_sent via the web form.
        """
        eid = ctx["nc_far_eid"]
        assert _get_expense(ctx, eid)["last_notification_class_sent"] == ""

        resp = _post_form(driver, f"{BASE_URL}/budget/expenses/{eid}/edit/", {
            "title": "NotifyClass Far", "type": "expense", "value": "42.00",
            "date_due": TOMORROW, "notify": "on",
        })
        assert resp.status_code in (302, 200), f"Edit returned {resp.status_code}"
        assert _get_expense(ctx, eid)["last_notification_class_sent"] == "tomorrow"

    def test_83_06_edit_moves_class_back_when_date_pushed_far(self, driver, w, ctx):
        """
        Editing an expense (currently 'tomorrow') to a far-future due date
        resets last_notification_class_sent to '' so future 'soon' notifications fire.
        """
        eid = ctx["nc_far_eid"]
        resp = _post_form(driver, f"{BASE_URL}/budget/expenses/{eid}/edit/", {
            "title": "NotifyClass Far", "type": "expense", "value": "42.00",
            "date_due": IN_10_DAYS, "notify": "on",
        })
        assert resp.status_code in (302, 200), f"Edit returned {resp.status_code}"
        assert _get_expense(ctx, eid)["last_notification_class_sent"] == ""

    def test_83_08_create_today_class_today(self, driver, w, ctx):
        """Expense due today gets last_notification_class_sent = 'today'."""
        d = _create_unsettled(ctx, "NotifyClass Today", TODAY)
        eid = d["id"]
        ctx["nc_today_eid"] = eid
        assert _get_expense(ctx, eid)["last_notification_class_sent"] == "today"

    def test_83_07_cleanup_initial_class_expenses(self, driver, w, ctx):
        for key in ("nc_far_eid", "nc_soon_eid", "nc_tomorrow_eid", "nc_today_eid", "nc_late_eid", "nc_settled_eid"):
            if key in ctx:
                api_delete(f"/api/v1/expenses/{ctx.pop(key)}/", ctx)


# ---------------------------------------------------------------------------
# 2. Due-date notification cron
# ---------------------------------------------------------------------------

class TestDueDateNotifications:

    def test_83_10_soon_notification_fires(self, driver, w, ctx):
        """Expense due in 3 days: cron sends 'soon' email and advances class."""
        # Create with far-future date so class starts at ""
        d = _create_unsettled(ctx, "NotifyCron Soon", IN_10_DAYS)
        eid = d["id"]
        ctx["cron_soon_eid"] = eid

        # Patch due date to 3 days via API (doesn't reset class)
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"date_due": IN_3_DAYS})
        assert _get_expense(ctx, eid)["last_notification_class_sent"] == ""

        seen = mailpit_seen_ids()
        _run_notify()
        time.sleep(1)

        exp = _get_expense(ctx, eid)
        assert exp["last_notification_class_sent"] == "soon"
        _fetch_notification_email(ctx, "Payment due in", timeout=30, ignore_ids=seen)

    def test_83_11_no_duplicate_on_second_run(self, driver, w, ctx):
        """Running the cron a second time does not send another 'soon' email."""
        seen = mailpit_seen_ids()
        _run_notify()
        time.sleep(1)
        exp = _get_expense(ctx, ctx["cron_soon_eid"])
        # Class must stay at "soon" — cron should not advance or re-send
        assert exp["last_notification_class_sent"] == "soon"
        # No new messages should have arrived
        msgs_after = {m["ID"] for m in requests.get(
            "http://localhost:8030/api/v1/messages", timeout=5
        ).json().get("messages", [])}
        assert not (msgs_after - seen), "Second cron run must not send a duplicate email"

    def test_83_12_tomorrow_notification_fires(self, driver, w, ctx):
        """When class is 'soon' and due date becomes tomorrow, cron sends 'tomorrow'."""
        eid = ctx["cron_soon_eid"]
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"date_due": TOMORROW})

        seen = mailpit_seen_ids()
        _run_notify()
        time.sleep(1)

        exp = _get_expense(ctx, eid)
        assert exp["last_notification_class_sent"] == "tomorrow"
        _fetch_notification_email(ctx, "Payment due tomorrow", timeout=30, ignore_ids=seen)

    def test_83_12b_today_notification_fires(self, driver, w, ctx):
        """When class is 'tomorrow' and due date reaches today, cron sends 'today'."""
        eid = ctx["cron_soon_eid"]
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"date_due": TODAY})

        seen = mailpit_seen_ids()
        _run_notify()
        time.sleep(1)

        exp = _get_expense(ctx, eid)
        assert exp["last_notification_class_sent"] == "today"
        _fetch_notification_email(ctx, "Payment due today", timeout=30, ignore_ids=seen)

    def test_83_13_late_notification_fires(self, driver, w, ctx):
        """When class is 'today' and due date passes, cron sends 'late'."""
        eid = ctx["cron_soon_eid"]
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"date_due": YESTERDAY})

        seen = mailpit_seen_ids()
        _run_notify()
        time.sleep(1)

        exp = _get_expense(ctx, eid)
        assert exp["last_notification_class_sent"] == "late"
        _fetch_notification_email(ctx, "Payment overdue", timeout=30, ignore_ids=seen)

    def test_83_14_no_notification_when_feuser_disabled(self, driver, w, ctx):
        """No email if feuser.email_notifications = False."""
        api_patch("/api/v1/account/", ctx, json={"email_notifications": False})
        d = _create_unsettled(ctx, "NotifyDisabled User", IN_10_DAYS)
        eid = d["id"]
        ctx["cron_disabled_eid"] = eid
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"date_due": IN_3_DAYS})

        _run_notify()
        time.sleep(1)

        exp = _get_expense(ctx, eid)
        assert exp["last_notification_class_sent"] == ""
        api_patch("/api/v1/account/", ctx, json={"email_notifications": True})

    def test_83_15_no_notification_when_expense_muted(self, driver, w, ctx):
        """No email if expense.notify = False."""
        d = _create_unsettled(ctx, "NotifyMuted Expense", IN_10_DAYS, notify=False)
        eid = d["id"]
        ctx["cron_muted_eid"] = eid
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"date_due": IN_3_DAYS})

        _run_notify()
        time.sleep(1)

        exp = _get_expense(ctx, eid)
        assert exp["last_notification_class_sent"] == ""

    def test_83_16_cleanup_cron_expenses(self, driver, w, ctx):
        for key in ("cron_soon_eid", "cron_disabled_eid", "cron_muted_eid"):
            if key in ctx:
                api_delete(f"/api/v1/expenses/{ctx.pop(key)}/", ctx)


# ---------------------------------------------------------------------------
# 3. Settled notifications
# ---------------------------------------------------------------------------

class TestSettledNotifications:

    def test_83_20_settled_on_auto_settle(self, driver, w, ctx):
        """auto_settle_expenses sends 'settled' notification."""
        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "AutoSettle Notify",
            "type": "expense", "value": "5.00",
            "date_due": YESTERDAY,
            "settled": False,
            "auto_settle_on_due_date": True,
            "notify": True,
        })
        assert resp.status_code == 201
        eid = resp.json()["id"]
        ctx["settle_auto_eid"] = eid

        seen = mailpit_seen_ids()
        _run_auto_settle()
        time.sleep(1)

        exp = _get_expense(ctx, eid)
        assert exp["settled"] is True
        assert exp["last_notification_class_sent"] == "settled"
        _fetch_notification_email(ctx, "Payment marked as paid", timeout=30, ignore_ids=seen)

    def test_83_21_settled_on_manual_edit(self, driver, w, ctx):
        """Editing an expense from unsettled to settled via web form sends notification."""
        d = _create_unsettled(ctx, "ManualSettle Notify", IN_3_DAYS)
        eid = d["id"]
        ctx["settle_manual_eid"] = eid

        seen = mailpit_seen_ids()
        _post_form(driver, f"{BASE_URL}/budget/expenses/{eid}/edit/", {
            "title": "ManualSettle Notify", "type": "expense", "value": "42.00",
            "date_due": IN_3_DAYS, "settled": "on", "notify": "on",
        })
        time.sleep(1)

        exp = _get_expense(ctx, eid)
        assert exp["settled"] is True
        assert exp["last_notification_class_sent"] == "settled"
        _fetch_notification_email(ctx, "Payment marked as paid", timeout=30, ignore_ids=seen)

    def test_83_22_no_settled_notification_on_create_already_settled(self, driver, w, ctx):
        """Creating an expense with settled=True does NOT send settled notification email."""
        import requests as _req
        msgs_before = _req.get("http://localhost:8030/api/v1/messages", timeout=5).json().get("messages", [])
        count_before = len(msgs_before)

        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "CreateSettled NoNotify",
            "type": "expense", "value": "1.00",
            "date_due": TODAY, "settled": True,
        })
        assert resp.status_code == 201
        eid = resp.json()["id"]
        ctx["no_notify_settled_eid"] = eid

        time.sleep(2)
        msgs_after = _req.get("http://localhost:8030/api/v1/messages", timeout=5).json().get("messages", [])
        new_msgs = [m for m in msgs_after if m not in msgs_before
                    and "CreateSettled" in m.get("Subject", "")
                    and "marked as paid" in m.get("Subject", "")]
        assert len(new_msgs) == 0, f"Unexpected settled notification sent: {new_msgs}"

    def test_83_23_no_settled_on_bulk_2_plus(self, driver, w, ctx):
        """Bulk settle with 2+ expenses does NOT send settled notifications."""
        import requests as _req
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
        ctx["bulk_no_notify_a"] = eid_a
        ctx["bulk_no_notify_b"] = eid_b

        msgs_before = _req.get("http://localhost:8030/api/v1/messages", timeout=5).json().get("messages", [])

        _post_form(driver, f"{BASE_URL}/budget/expenses/bulk-action/", {
            "action": "settle", "uid": [str(eid_a), str(eid_b)],
        })
        time.sleep(2)

        msgs_after = _req.get("http://localhost:8030/api/v1/messages", timeout=5).json().get("messages", [])
        new_settled = [m for m in msgs_after
                       if m.get("ID") not in {x.get("ID") for x in msgs_before}
                       and "marked as paid" in m.get("Subject", "")]
        assert len(new_settled) == 0, f"Got unexpected settled notification(s): {new_settled}"

    def test_83_24_settled_on_bulk_exactly_1(self, driver, w, ctx):
        """Bulk settle with exactly 1 expense DOES send settled notification."""
        d = _create_unsettled(ctx, "BulkNotify Single", IN_3_DAYS)
        eid = d["id"]
        ctx["bulk_single_eid"] = eid

        seen = mailpit_seen_ids()
        _post_form(driver, f"{BASE_URL}/budget/expenses/bulk-action/", {
            "action": "settle", "uid": [str(eid)],
        })
        time.sleep(1)

        exp = _get_expense(ctx, eid)
        assert exp["settled"] is True
        assert exp["last_notification_class_sent"] == "settled"
        _fetch_notification_email(ctx, "Payment marked as paid", timeout=30, ignore_ids=seen)

    def test_83_25_cleanup_settled_expenses(self, driver, w, ctx):
        for key in ("settle_auto_eid", "settle_manual_eid", "no_notify_settled_eid",
                    "bulk_no_notify_a", "bulk_no_notify_b", "bulk_single_eid"):
            if key in ctx:
                api_delete(f"/api/v1/expenses/{ctx.pop(key)}/", ctx)


# ---------------------------------------------------------------------------
# 4. Email action links
# ---------------------------------------------------------------------------

class TestEmailActionLinks:

    def test_83_30_settle_via_email_link(self, driver, w, ctx):
        """The settle-via-email link settles the expense and sends settled notification."""
        # Create expense with class "late" so we can get a "late" email with the settle link
        d = _create_unsettled(ctx, "EmailLink Settle", IN_10_DAYS)
        eid = d["id"]
        ctx["link_settle_eid"] = eid

        # Patch to yesterday to set target class = "late" without resetting class
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"date_due": YESTERDAY})

        seen_before_notify = mailpit_seen_ids()
        _run_notify()
        time.sleep(1)

        body = _fetch_notification_email(ctx, "Payment overdue", timeout=30, ignore_ids=seen_before_notify)
        settle_url = extract_link(body)
        assert "/settle-via-email/" in settle_url

        # Click the link using auth session (requires login)
        seen_before_settle = mailpit_seen_ids()
        s = _auth_session(driver)
        resp = s.get(settle_url, allow_redirects=True)
        assert resp.status_code == 200

        time.sleep(1)
        exp = _get_expense(ctx, eid)
        assert exp["settled"] is True
        assert exp["last_notification_class_sent"] == "settled"
        _fetch_notification_email(ctx, "Payment marked as paid", timeout=30, ignore_ids=seen_before_settle)

    def test_83_31_mute_expense_via_link(self, driver, w, ctx):
        """The mute-notifications link sets expense.notify = False."""
        d = _create_unsettled(ctx, "EmailLink Mute", IN_10_DAYS)
        eid = d["id"]
        ctx["link_mute_eid"] = eid
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"date_due": IN_3_DAYS})

        _run_notify()
        time.sleep(1)

        body = _fetch_notification_email(ctx, "Payment due in", timeout=30)
        import re
        links = [
            re.sub(r'https?://[^/]+', "http://localhost:8080", raw.rstrip('.,)'))
            for raw in re.findall(r'https?://\S+', body)
        ]
        mute_url = next((u for u in links if "/mute-notifications/" in u), None)
        assert mute_url, f"mute_url not found in email body:\n{body}"

        s = _auth_session(driver)
        resp = s.get(mute_url, allow_redirects=True)
        assert resp.status_code == 200

        exp = _get_expense(ctx, eid)
        assert exp["notify"] is False

    def test_83_32_mute_all_via_link(self, driver, w, ctx):
        """The mute-all link sets feuser.email_notifications = False."""
        import re
        api_patch("/api/v1/account/", ctx, json={"email_notifications": True})
        d = _create_unsettled(ctx, "EmailLink MuteAll", IN_10_DAYS)
        eid = d["id"]
        ctx["link_muteall_eid"] = eid
        # Patch date so class is "" → cron will send "soon"
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"date_due": IN_3_DAYS})

        _run_notify()
        time.sleep(1)

        body = _fetch_notification_email(ctx, "Payment due in", timeout=30)
        links = [
            re.sub(r'https?://[^/]+', "http://localhost:8080", raw.rstrip('.,)'))
            for raw in re.findall(r'https?://\S+', body)
        ]
        mute_all_url = next((u for u in links if "/mute-all/" in u), None)
        assert mute_all_url, f"mute_all_url not found:\n{body}"

        s = _auth_session(driver)
        resp = s.get(mute_all_url, allow_redirects=True)
        assert resp.status_code == 200

        account = api_get("/api/v1/account/", ctx).json()
        assert account["email_notifications"] is False

        api_patch("/api/v1/account/", ctx, json={"email_notifications": True})

    def test_83_33_cleanup_link_expenses(self, driver, w, ctx):
        for key in ("link_settle_eid", "link_mute_eid", "link_muteall_eid"):
            if key in ctx:
                api_delete(f"/api/v1/expenses/{ctx.pop(key)}/", ctx)


# ---------------------------------------------------------------------------
# 5. Additional coverage: auto_settle_on_due_date flag and API PATCH settle
# ---------------------------------------------------------------------------

class TestAutoSettleAndApiSettled:

    def test_83_40_auto_settle_expense_gets_no_due_notification(self, driver, w, ctx):
        """
        Expense with auto_settle_on_due_date=True must NEVER receive
        'soon / tomorrow / late' due-date reminders from send_expense_notifications —
        those reminders only make sense for expenses the user must pay manually.
        """
        # Create with IN_10_DAYS so set_initial_notification_class gives "" (no class).
        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "AutoSettle NoDueNotif",
            "type": "expense", "value": "5.00",
            "date_due": IN_10_DAYS,
            "settled": False,
            "auto_settle_on_due_date": True,
            "notify": True,
        })
        assert resp.status_code == 201
        eid = resp.json()["id"]
        ctx["as_no_due_eid"] = eid

        # Patch due date to 3 days — without auto_settle filter the cron would
        # now send "soon".  last_notification_class_sent stays "" (PATCH doesn't
        # call set_initial_notification_class).
        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"date_due": IN_3_DAYS})
        assert _get_expense(ctx, eid)["last_notification_class_sent"] == ""

        _run_notify()
        time.sleep(1)

        exp = _get_expense(ctx, eid)
        assert exp["last_notification_class_sent"] == "", (
            "Due-date notification must NOT be sent for an auto_settle_on_due_date expense"
        )

    def test_83_41_auto_settle_sends_settled_for_due_today(self, driver, w, ctx):
        """
        auto_settle_expenses sends 'settled' notification when the due date is
        today (just drifted into the past = within the 1-day threshold).
        """
        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "AutoSettle DueToday",
            "type": "expense", "value": "3.00",
            "date_due": TODAY,
            "settled": False,
            "auto_settle_on_due_date": True,
            "notify": True,
        })
        assert resp.status_code == 201
        eid = resp.json()["id"]
        ctx["as_today_eid"] = eid

        seen = mailpit_seen_ids()
        _run_auto_settle()
        time.sleep(1)

        exp = _get_expense(ctx, eid)
        assert exp["settled"] is True
        assert exp["last_notification_class_sent"] == "settled"
        _fetch_notification_email(ctx, "Payment marked as paid", timeout=30, ignore_ids=seen)

    def test_83_42_auto_settle_no_settled_for_old_due(self, driver, w, ctx):
        """
        auto_settle_expenses does NOT send 'settled' notification when the due
        date is more than 1 day in the past (backfill / old debt scenario).
        """
        import requests as _req
        LONG_AGO = (date.today() - timedelta(days=10)).isoformat()

        resp = api_post("/api/v1/expenses/", ctx, json={
            "title": "AutoSettle OldDue",
            "type": "expense", "value": "7.00",
            "date_due": LONG_AGO,
            "settled": False,
            "auto_settle_on_due_date": True,
            "notify": True,
        })
        assert resp.status_code == 201
        eid = resp.json()["id"]
        ctx["as_old_eid"] = eid

        msgs_before = _req.get(
            "http://localhost:8030/api/v1/messages", timeout=5
        ).json().get("messages", [])

        _run_auto_settle()
        time.sleep(2)

        exp = _get_expense(ctx, eid)
        assert exp["settled"] is True, "Expense should have been auto-settled"

        msgs_after = _req.get(
            "http://localhost:8030/api/v1/messages", timeout=5
        ).json().get("messages", [])
        new_settled = [
            m for m in msgs_after
            if m.get("ID") not in {x.get("ID") for x in msgs_before}
            and "OldDue" in m.get("Subject", "")
        ]
        assert len(new_settled) == 0, (
            f"Settled notification must NOT fire for an old due date, got: {new_settled}"
        )

    def test_83_43_settled_via_api_patch_sends_notification(self, driver, w, ctx):
        """API PATCH that transitions settled=False → True sends 'settled' notification."""
        d = _create_unsettled(ctx, "ApiPatch Settle", IN_3_DAYS)
        eid = d["id"]
        ctx["api_settle_eid"] = eid

        seen = mailpit_seen_ids()
        resp = api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"settled": True})
        assert resp.status_code == 200
        time.sleep(1)

        exp = _get_expense(ctx, eid)
        assert exp["settled"] is True
        assert exp["last_notification_class_sent"] == "settled"
        _fetch_notification_email(ctx, "Payment marked as paid", timeout=30, ignore_ids=seen)

    def test_83_44_no_settled_via_api_when_profile_notis_off(self, driver, w, ctx):
        """No settled notification when feuser.email_notifications = False."""
        import requests as _req
        api_patch("/api/v1/account/", ctx, json={"email_notifications": False})

        d = _create_unsettled(ctx, "ApiSettle ProfileOff", IN_3_DAYS)
        eid = d["id"]
        ctx["api_profile_off_eid"] = eid

        msgs_before = _req.get(
            "http://localhost:8030/api/v1/messages", timeout=5
        ).json().get("messages", [])

        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"settled": True})
        time.sleep(2)

        msgs_after = _req.get(
            "http://localhost:8030/api/v1/messages", timeout=5
        ).json().get("messages", [])
        new_msgs = [
            m for m in msgs_after
            if m.get("ID") not in {x.get("ID") for x in msgs_before}
            and "ProfileOff" in m.get("Subject", "")
        ]
        assert len(new_msgs) == 0, (
            f"Settled notification must not fire when email_notifications=False: {new_msgs}"
        )

        api_patch("/api/v1/account/", ctx, json={"email_notifications": True})

    def test_83_45_no_settled_via_api_when_expense_muted(self, driver, w, ctx):
        """No settled notification when expense.notify = False."""
        import requests as _req
        d = _create_unsettled(ctx, "ApiSettle ExpenseMuted", IN_3_DAYS, notify=False)
        eid = d["id"]
        ctx["api_muted_eid"] = eid

        msgs_before = _req.get(
            "http://localhost:8030/api/v1/messages", timeout=5
        ).json().get("messages", [])

        api_patch(f"/api/v1/expenses/{eid}/", ctx, json={"settled": True})
        time.sleep(2)

        msgs_after = _req.get(
            "http://localhost:8030/api/v1/messages", timeout=5
        ).json().get("messages", [])
        new_msgs = [
            m for m in msgs_after
            if m.get("ID") not in {x.get("ID") for x in msgs_before}
            and "ExpenseMuted" in m.get("Subject", "")
        ]
        assert len(new_msgs) == 0, (
            f"Settled notification must not fire when expense.notify=False: {new_msgs}"
        )

    def test_83_46_cleanup(self, driver, w, ctx):
        for key in ("as_no_due_eid", "as_today_eid", "as_old_eid",
                    "api_settle_eid", "api_profile_off_eid", "api_muted_eid"):
            if key in ctx:
                api_delete(f"/api/v1/expenses/{ctx.pop(key)}/", ctx)
