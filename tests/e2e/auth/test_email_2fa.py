"""
Email second factor: setup and login via a code read from Mailpit, plus the
send-code endpoint's anti-spam guarantees (server-resolved target, cooldown
throttle). Mirrors tests/e2e/auth/test_totp.py's structure.

Run with (live stack at :8080 + Mailpit at :8030 required):
    pytest tests/e2e/auth/test_email_2fa.py -v | tee logfile.log
"""
import re
import time

import pyotp
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from bhelpers import _shell
from helpers import (
    _url, fill, click, submit, wait_url, wait_text,
    setup_user, cleanup_user, create_confirmed_user,
    mailpit_seen_ids, fetch_email,
    http_session, form_login, form_post,
)

SETUP_CODE_SUBJECT = "Confirm your email for two-factor authentication"
LOGIN_CODE_SUBJECT = "Your Comaney sign-in code"
_FACTOR_SECRET = "JBSWY3DPEHPK3PXP"


def _fetch_email_retrying_resend(driver, email, subject, seen, overall_timeout=90):
    """The send-code cooldown is shared within a purpose ("setup" or
    "login", see feusers/email_factor_service.py) but not across the two, so
    this shouldn't normally be needed between a setup send and the
    following login send anymore - kept as resilience against any other
    same-purpose collision (e.g. a rerun landing two sends close together).
    Click "Resend code" and keep polling Mailpit until a send actually goes
    out, same as a real user would if nothing arrived."""
    deadline = time.time() + overall_timeout
    while time.time() < deadline:
        try:
            return fetch_email(email, subject, timeout=5, ignore_ids=seen)
        except TimeoutError:
            pass
        try:
            btn = driver.find_element(By.ID, "email2fa-resend-btn")
            if btn.is_enabled():
                btn.click()
        except Exception:
            pass
        time.sleep(3)
    raise TimeoutError(f"Email '{subject}' for {email} never arrived after retrying resend")


def _extract_code(body: str) -> str:
    # A generic \d{6} match is not safe here: the email's inline CSS has
    # hex colors like #141414 that also look like a 6-digit code. Anchor on
    # the <span> the code is actually rendered in (see
    # templates/emails/second_factor_email_code.html).
    match = re.search(r'<span[^>]*>\s*(\d{6})\s*</span>', body)
    assert match, f"No 6-digit code found in email body: {body!r}"
    return match.group(1)


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestEmailTwoFactor:

    def _setup_email_2fa(self, driver, w, ctx):
        # Setup uses its own email copy (see
        # templates/emails/second_factor_email_code_setup.html): telling the
        # user they're "finishing signing in" during setup would be wrong.
        seen = mailpit_seen_ids()
        driver.get(_url("/email-2fa/setup/"))
        body = fetch_email(ctx["email"], SETUP_CODE_SUBJECT, ignore_ids=seen)
        fill(w, By.ID, "id_code", _extract_code(body))
        submit(w)
        # No dedicated "added" screen: setup redirects straight to the
        # profile page, which flashes the one-time recovery code itself.
        wait_url(w, "/profile/")
        recovery_el = w.until(EC.presence_of_element_located((By.ID, "recovery-code")))
        ctx["recovery_code"] = recovery_el.text.strip()

    def test_setup_2fa(self, driver, w, ctx):
        self._setup_email_2fa(driver, w, ctx)
        assert len(ctx["recovery_code"]) > 5

    def test_profile_hides_add_option_once_the_one_allowed_factor_exists(self, driver, w, ctx):
        # profile.html's "Add new second factor" dropdown only lists "Email
        # code" (its menu-item link to email_factor_setup) while
        # email_2fa_available and not has_email_factor; check the link
        # itself rather than page text, since the registered factor's own
        # row also legitimately displays the "Email Code" label.
        driver.get(_url("/profile/"))
        wait_text(driver, w, "Email Code")
        assert "/email-2fa/setup/" not in driver.page_source

    def test_login_with_email_code(self, driver, w, ctx):
        seen = mailpit_seen_ids()
        click(w, By.CSS_SELECTOR, "button[type=submit]#logout-button")
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", ctx["email"])
        fill(w, By.ID, "id_password", ctx["password"])
        submit(w)
        wait_url(w, "/twofa/verify/")
        body = _fetch_email_retrying_resend(driver, ctx["email"], LOGIN_CODE_SUBJECT, seen)
        fill(w, By.ID, "id_code", _extract_code(body))
        submit(w)
        wait_url(w, "/budget/")


def _enable_email_factor_directly(email: str):
    """Bypass the UI: create the EmailFactor row via the Django shell, same
    approach test_totp_recovery_rate_limit.py uses for TOTPFactor. Fast and
    deterministic for a test that only cares about the send-code endpoint,
    not the setup flow."""
    _shell(
        f"from feusers.models import FeUser, EmailFactor; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"EmailFactor.objects.create(feuser=u, secret='{_FACTOR_SECRET}', is_primary=True, label='Email Code')"
    )


def _complete_email_login(s, email, password):
    """Password step + the real TOTP-by-email verify step (using the fixed
    _FACTOR_SECRET an _enable_email_factor_directly-created factor has),
    landing the session fully authenticated (feuser_id set)."""
    login_resp = form_login(s, email, password)
    assert login_resp.status_code in (301, 302), f"password step failed: {login_resp.status_code}"
    code = pyotp.TOTP(_FACTOR_SECRET, interval=300).now()
    resp, _ = form_post(s, "/twofa/verify/", {"code": code}, csrf_path="/twofa/verify/")
    assert resp.status_code in (301, 302), f"2FA verify step failed: {resp.status_code} {resp.text[:500]}"
    return resp


class TestEmailSendCodeThrottle:
    """The single send-code endpoint (/email-2fa/send-code/) must resolve its
    target purely from session state, and must not let a session hammer it
    for free emails."""

    def test_setup_send_does_not_consume_the_post_setup_cooldown(self):
        """Regression test: a send during setup and the very next send in a
        post-setup context (e.g. opening "Test" moments after finishing
        setup) must use separate throttle buckets (see request_send's
        purpose-scoped identity), so the post-setup send still goes out
        instead of silently being swallowed by the setup send's own 60s
        cooldown."""
        user = create_confirmed_user()
        email = user["email"]
        try:
            s = http_session()
            login_resp = form_login(s, email, user["password"])
            assert login_resp.status_code in (301, 302)
            s.get(_url("/email-2fa/setup/"), timeout=10)

            seen = mailpit_seen_ids()
            setup_send, _ = form_post(s, "/email-2fa/send-code/", {}, csrf_path="/email-2fa/setup/")
            assert setup_send.status_code == 200, setup_send.text
            code = _extract_code(fetch_email(email, SETUP_CODE_SUBJECT, ignore_ids=seen))

            finish, _ = form_post(s, "/email-2fa/setup/", {"code": code}, csrf_path="/email-2fa/setup/")
            assert finish.status_code in (301, 302), finish.text

            seen2 = mailpit_seen_ids()
            post_setup_send, _ = form_post(s, "/email-2fa/send-code/", {}, csrf_path="/profile/")
            assert post_setup_send.status_code == 200, (
                f"Post-setup send was throttled by the setup send's own cooldown: {post_setup_send.text}"
            )
            fetch_email(email, LOGIN_CODE_SUBJECT, timeout=15, ignore_ids=seen2)
        finally:
            cleanup_user(email)

    def test_testing_the_method_does_not_block_the_next_login_send(self):
        """Regression test: factor_test sends must use the "confirm" bucket,
        separate from "login", so testing the method right before logging
        out never blocks the very next login attempt's send."""
        user = create_confirmed_user()
        email = user["email"]
        try:
            _enable_email_factor_directly(email)
            factor_id = _shell(
                f"from feusers.models import FeUser, EmailFactor; "
                f"u = FeUser.objects.get(email='{email}'); "
                f"print(EmailFactor.objects.get(feuser=u).pk)"
            )
            s = http_session()
            _complete_email_login(s, email, user["password"])

            test_send, _ = form_post(
                s, "/email-2fa/send-code/", {}, csrf_path=f"/twofa/factor/email/{factor_id}/test/",
            )
            assert test_send.status_code == 200, test_send.text

            form_post(s, "/logout/", {}, csrf_path="/profile/")
            login_resp = form_login(s, email, user["password"])
            assert login_resp.status_code in (301, 302)

            login_send, _ = form_post(s, "/email-2fa/send-code/", {}, csrf_path="/twofa/verify/")
            assert login_send.status_code == 200, (
                f"Testing the method blocked the very next login send: {login_send.text}"
            )
        finally:
            cleanup_user(email)

    def test_successful_login_clears_the_login_throttle(self):
        """Regression test: a completed login must reset the "login" bucket
        (clear_login_send_throttle), so logging out and immediately signing
        back in still gets a fresh code instead of being throttled by the
        send from the login that just succeeded."""
        user = create_confirmed_user()
        email = user["email"]
        try:
            _enable_email_factor_directly(email)
            s = http_session()
            _complete_email_login(s, email, user["password"])

            form_post(s, "/logout/", {}, csrf_path="/profile/")
            login_resp = form_login(s, email, user["password"])
            assert login_resp.status_code in (301, 302)

            relogin_send, _ = form_post(s, "/email-2fa/send-code/", {}, csrf_path="/twofa/verify/")
            assert relogin_send.status_code == 200, (
                f"A successful login did not clear the throttle for the next one: {relogin_send.text}"
            )
        finally:
            cleanup_user(email)

    def test_send_code_without_any_session_is_rejected(self):
        s = http_session()
        resp, _ = form_post(s, "/email-2fa/send-code/", {}, csrf_path="/login/")
        assert resp.status_code == 400

    def test_second_send_within_the_cooldown_is_throttled(self):
        user = create_confirmed_user()
        try:
            _enable_email_factor_directly(user["email"])
            s = http_session()
            login_resp = form_login(s, user["email"], user["password"])
            assert login_resp.status_code in (301, 302), \
                f"password step failed: {login_resp.status_code}"

            first, _ = form_post(s, "/email-2fa/send-code/", {}, csrf_path="/twofa/verify/")
            assert first.status_code == 200, first.text

            second, _ = form_post(s, "/email-2fa/send-code/", {}, csrf_path="/twofa/verify/")
            assert second.status_code == 429, (
                "A second immediate send-code request was not throttled: "
                f"got {second.status_code} / {second.text}"
            )
        finally:
            cleanup_user(user["email"])


class TestEmailFactorSecurity:
    """Pentest-style regression tests for the invariants the feature's design
    relies on: mailbox control must be proven before a factor is created,
    the one-factor-per-account cap is enforced server-side (not just hidden
    in the UI), the send-code endpoint cannot be redirected at another
    account via extra body params, and cross-user IDOR is not possible on
    any of the generic factor-management views."""

    def test_wrong_setup_code_does_not_create_a_factor(self):
        user = create_confirmed_user()
        email = user["email"]
        try:
            s = http_session()
            login_resp = form_login(s, email, user["password"])
            assert login_resp.status_code in (301, 302)
            s.get(_url("/email-2fa/setup/"), timeout=10)  # primes the session-held secret

            resp, _ = form_post(s, "/email-2fa/setup/", {"code": "000000"}, csrf_path="/email-2fa/setup/")
            assert resp.status_code == 200, "A wrong code must re-render the form, not redirect/succeed"
            assert "Invalid code" in resp.text

            exists = _shell(
                f"from feusers.models import FeUser, EmailFactor; "
                f"u = FeUser.objects.get(email='{email}'); "
                f"print(EmailFactor.objects.filter(feuser=u).exists())"
            )
            assert exists == "False", "A wrong confirmation code must never create an EmailFactor"
        finally:
            cleanup_user(email)

    def test_setup_view_redirects_away_once_a_factor_already_exists(self):
        """Enforced in email_factor_setup itself, not just by hiding the
        profile-page link: capped at one EmailFactor per account."""
        user = create_confirmed_user()
        try:
            _enable_email_factor_directly(user["email"])
            s = http_session()
            _complete_email_login(s, user["email"], user["password"])

            r = s.get(_url("/email-2fa/setup/"), allow_redirects=False, timeout=10)
            assert r.status_code in (301, 302), (
                f"Setup view did not redirect away despite an existing EmailFactor: {r.status_code}"
            )
            assert "/email-2fa/setup/" not in (r.headers.get("Location") or "")
        finally:
            cleanup_user(user["email"])

    def test_send_code_ignores_client_supplied_target_override(self):
        """email_factor_send_code takes zero client-supplied user/factor
        identifiers by design (see feusers/views/email_factor.py): it
        resolves the target purely from session state. This locks that in by
        trying to override the target via extra POST body fields anyway and
        confirming the named victim account is completely unaffected."""
        attacker = create_confirmed_user()
        victim = create_confirmed_user()
        try:
            _enable_email_factor_directly(attacker["email"])
            _enable_email_factor_directly(victim["email"])

            s = http_session()
            _complete_email_login(s, attacker["email"], attacker["password"])

            resp, _ = form_post(s, "/email-2fa/send-code/", {
                "feuser_id": "1", "factor_id": "1",
                "email": victim["email"], "target_email": victim["email"],
            }, csrf_path="/twofa/verify/")
            assert resp.status_code == 200, resp.text

            # If the spoofed params had any effect on who gets targeted, the
            # victim's own send-code cooldown would now be consumed too.
            # Confirm it wasn't: the victim can still send immediately.
            s2 = http_session()
            _complete_email_login(s2, victim["email"], victim["password"])
            victim_resp, _ = form_post(s2, "/email-2fa/send-code/", {}, csrf_path="/twofa/verify/")
            assert victim_resp.status_code == 200, (
                "Victim's cooldown was already consumed - the attacker's spoofed "
                f"body params leaked into the victim's account: {victim_resp.text}"
            )
        finally:
            cleanup_user(attacker["email"])
            cleanup_user(victim["email"])

    def test_cross_user_cannot_test_another_users_email_factor(self):
        """IDOR check: factor_test resolves its target scoped to the
        requesting feuser's own factors (_find(get_all_factors(feuser),...)),
        so guessing another user's factor pk must not work."""
        victim = create_confirmed_user()
        attacker = create_confirmed_user()
        try:
            _enable_email_factor_directly(victim["email"])
            factor_id = _shell(
                f"from feusers.models import FeUser, EmailFactor; "
                f"u = FeUser.objects.get(email='{victim['email']}'); "
                f"print(EmailFactor.objects.get(feuser=u).pk)"
            )

            s = http_session()
            # Attacker has no 2FA of their own, so password login alone
            # reaches a fully authenticated session.
            login_resp = form_login(s, attacker["email"], attacker["password"])
            assert login_resp.status_code in (301, 302)

            r = s.get(_url(f"/twofa/factor/email/{factor_id}/test/"), allow_redirects=False, timeout=10)
            assert r.status_code in (301, 302), (
                f"Attacker reached another user's factor_test page: {r.status_code}"
            )
            assert "profile" in (r.headers.get("Location") or "").lower()
        finally:
            cleanup_user(victim["email"])
            cleanup_user(attacker["email"])
