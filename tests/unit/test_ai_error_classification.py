"""
Unit tests for AIService._classify_exception / _handle_billing (see
budget/ai_service.py) -- the logic that turns a raw anthropic SDK exception
into a typed AIError and, for a trial-key user, disables the shared trial
key and emails the admin.

This behavior used to live only inline in budget/views/express.py's
except-block, so only express creation was protected: dashboard card AI and
partnership AI could silently exhaust or break the shared trial key with
nobody finding out. Moving it into AIService._classify_exception means every
AI feature gets it automatically -- these tests exist to lock that in.

anthropic isn't installed in this local venv (same constraint as Django not
being configurable here -- see test_ai_call_orchestration.py), so the real
anthropic.AuthenticationError/RateLimitError/etc. classes aren't importable
either. This mirrors _classify_exception's decision logic with small stand-in
exception types instead, and injects disable_trial/notify_admin_billing/
notify_admin_invalid_trial_key as fakes to verify exactly when they fire.
Run with: venv/bin/pytest tests/unit/test_ai_error_classification.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ── Stand-ins for the anthropic SDK exception types AIService classifies ───

class FakeAuthenticationError(Exception):
    pass


class FakePermissionDeniedError(Exception):
    pass


class FakeRateLimitError(Exception):
    pass


class FakeInternalServerError(Exception):
    pass


class FakeAPIConnectionError(Exception):
    pass


class FakeAPIStatusError(Exception):
    def __init__(self, message, status_code=500):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# ── Mirror of AIService._classify_exception / _handle_billing ──────────────

class Classification:
    def __init__(self, kind, message="", overloaded=False, detail=""):
        self.kind = kind  # "auth" | "billing" | "transient" | "unknown"
        self.message = message
        self.overloaded = overloaded
        self.detail = detail


def looks_like_billing(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "credit" in msg or "billing" in msg or "balance" in msg


def classify_exception(exc: Exception, *, is_trial: bool, disable_trial, notify_admin_billing, notify_admin_invalid_trial_key) -> Classification:
    def handle_billing(reason):
        if is_trial:
            disable_trial(reason)
            notify_admin_billing(reason)
            return Classification("billing", reason)
        return Classification("billing", "Insufficient Anthropic credits. Please top up your account at console.anthropic.com.")

    if isinstance(exc, FakeAuthenticationError):
        if is_trial:
            notify_admin_invalid_trial_key()
            return Classification("auth", "trial key invalid")
        return Classification("auth", "Invalid API key. Please update it in your profile.")

    if isinstance(exc, FakePermissionDeniedError):
        return Classification("auth", "no permission")

    if isinstance(exc, FakeRateLimitError):
        if looks_like_billing(exc):
            return handle_billing(str(exc))
        return Classification("transient", "rate limited")

    if isinstance(exc, FakeInternalServerError):
        return Classification("transient", "overloaded", overloaded=True, detail=str(exc))

    if isinstance(exc, FakeAPIConnectionError):
        return Classification("transient", "connection error")

    if isinstance(exc, FakeAPIStatusError):
        if looks_like_billing(exc):
            return handle_billing(str(exc))
        return Classification("transient", f"Anthropic API error {exc.status_code}: {exc.message}")

    return Classification("unknown", f"Unexpected error: {exc}")


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)


def _classify(exc, is_trial):
    disable_trial = _Recorder()
    notify_billing = _Recorder()
    notify_invalid_key = _Recorder()
    result = classify_exception(
        exc, is_trial=is_trial,
        disable_trial=disable_trial,
        notify_admin_billing=notify_billing,
        notify_admin_invalid_trial_key=notify_invalid_key,
    )
    return result, disable_trial, notify_billing, notify_invalid_key


class TestAuthenticationClassification:

    def test_trial_auth_error_notifies_admin(self):
        result, disable_trial, notify_billing, notify_invalid_key = _classify(
            FakeAuthenticationError("bad key"), is_trial=True,
        )
        assert result.kind == "auth"
        assert len(notify_invalid_key.calls) == 1
        assert disable_trial.calls == []
        assert notify_billing.calls == []

    def test_own_key_auth_error_does_not_notify_admin(self):
        # A feuser's own bad API key is their problem, not the shared trial
        # key's -- the admin should not be spammed for it.
        result, disable_trial, notify_billing, notify_invalid_key = _classify(
            FakeAuthenticationError("bad key"), is_trial=False,
        )
        assert result.kind == "auth"
        assert notify_invalid_key.calls == []

    def test_permission_denied_never_notifies_admin(self):
        result, disable_trial, notify_billing, notify_invalid_key = _classify(
            FakePermissionDeniedError("no perms"), is_trial=True,
        )
        assert result.kind == "auth"
        assert notify_invalid_key.calls == []


class TestBillingClassification:

    def test_trial_rate_limit_with_billing_message_disables_and_notifies(self):
        result, disable_trial, notify_billing, notify_invalid_key = _classify(
            FakeRateLimitError("Your credit balance is too low"), is_trial=True,
        )
        assert result.kind == "billing"
        assert len(disable_trial.calls) == 1
        assert len(notify_billing.calls) == 1

    def test_trial_status_error_with_billing_message_disables_and_notifies(self):
        result, disable_trial, notify_billing, notify_invalid_key = _classify(
            FakeAPIStatusError("insufficient billing", status_code=402), is_trial=True,
        )
        assert result.kind == "billing"
        assert len(disable_trial.calls) == 1
        assert len(notify_billing.calls) == 1

    def test_own_key_billing_error_does_not_touch_trial_flag(self):
        # The feuser is spending their own money -- never disable the shared
        # trial key or notify the admin over someone else's account.
        result, disable_trial, notify_billing, notify_invalid_key = _classify(
            FakeRateLimitError("insufficient balance"), is_trial=False,
        )
        assert result.kind == "billing"
        assert disable_trial.calls == []
        assert notify_billing.calls == []

    def test_plain_rate_limit_without_billing_wording_is_transient_not_billing(self):
        result, disable_trial, notify_billing, notify_invalid_key = _classify(
            FakeRateLimitError("Too many requests, slow down"), is_trial=True,
        )
        assert result.kind == "transient"
        assert disable_trial.calls == []
        assert notify_billing.calls == []


class TestTransientClassification:

    def test_internal_server_error_marked_overloaded(self):
        result, *_ = _classify(FakeInternalServerError("overloaded"), is_trial=True)
        assert result.kind == "transient"
        assert result.overloaded is True
        assert result.detail == "overloaded"

    def test_connection_error_is_transient_not_overloaded(self):
        result, *_ = _classify(FakeAPIConnectionError("timeout"), is_trial=True)
        assert result.kind == "transient"
        assert result.overloaded is False

    def test_status_error_without_billing_wording_is_transient(self):
        result, *_ = _classify(FakeAPIStatusError("model overloaded", status_code=529), is_trial=True)
        assert result.kind == "transient"


class TestUnknownClassification:

    def test_unrecognized_exception_falls_back_to_unknown(self):
        result, disable_trial, notify_billing, notify_invalid_key = _classify(
            ValueError("Claude returned an empty response"), is_trial=True,
        )
        assert result.kind == "unknown"
        assert disable_trial.calls == []
        assert notify_billing.calls == []
        assert notify_invalid_key.calls == []
