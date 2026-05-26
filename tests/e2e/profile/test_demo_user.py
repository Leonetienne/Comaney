"""
Demo user feature tests.

Covers:
  - Demo banner shown at every login and must be accepted
  - UI elements greyed out / hidden for demo users
  - Server rejects restricted actions even when called directly (pentest)
  - special_ai_trial_budget is displayed and enforced
  - --demo and --ai-trial-budget flags on create_user management command
  - Real users cannot invite a demo account as buddy or project member

All tests are skipped automatically when ENABLE_DEMO_USERS is not set on the
target server (dev/self-hosted systems without a demo user configured).
"""
import subprocess
import time
import uuid
import warnings

import pytest
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from helpers import (
    _url, run_cmd, setup_user, cleanup_user,
    fill, click, browser_login,
    DOCKER_WEB, PASSWORD,
)

DEMO_PASSWORD = "D3m0Test1ng!"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_email():
    return f"demo.{uuid.uuid4().hex[:8]}@example.com"


def _shell(code: str, timeout: int = 15) -> str:
    r = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c", code],
        capture_output=True, text=True, timeout=timeout,
    )
    assert r.returncode == 0, f"shell failed:\n{r.stderr}"
    return r.stdout.strip()


def _demo_users_enabled() -> bool:
    """Return True if the target server has ENABLE_DEMO_USERS=TRUE."""
    return _shell("from django.conf import settings; print(settings.ENABLE_DEMO_USERS)") == "True"


def _create_demo_user(email: str, *, ai_trial_budget: int | None = None) -> None:
    cmd = ["docker", "exec", DOCKER_WEB, "python", "manage.py",
           "create_user", email, "-p", DEMO_PASSWORD, "--demo",
           "--first-name", "Dean", "--last-name", "Demo"]
    if ai_trial_budget is not None:
        cmd += ["--ai-trial-budget", str(ai_trial_budget)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    assert r.returncode == 0, f"create_user --demo failed:\n{r.stderr}"


def _http_session(email: str, password: str, accept_banner: bool = True) -> requests.Session:
    """Return a logged-in requests.Session. Accepts the demo banner if the user is a demo user."""
    s = requests.Session()

    # Get CSRF from login page
    r = s.get(_url("/login/"), timeout=10)
    csrf = _extract_csrf(r.text)
    s.post(_url("/login/"), data={
        "csrfmiddlewaretoken": csrf,
        "email": email,
        "password": password,
    }, allow_redirects=True, timeout=10)

    if accept_banner:
        r = s.get(_url("/demo-banner/"), timeout=10)
        # Only try to accept if we actually got the banner page (non-demo users are redirected away).
        if "btn-demo-accept" in r.text or "Okay, I understand" in r.text:
            csrf2 = _extract_csrf(r.text)
            s.post(_url("/demo-banner/"), data={
                "csrfmiddlewaretoken": csrf2,
                "action": "accept",
            }, allow_redirects=True, timeout=10)

    return s


def _extract_csrf(html: str) -> str:
    import re
    m = re.search(r'csrfmiddlewaretoken["\s]+value=["\']([^"\']+)', html)
    if not m:
        m = re.search(r'csrfmiddlewaretoken.*?value="([^"]+)"', html)
    assert m, "CSRF token not found in page"
    return m.group(1)


def _get_csrf(session: requests.Session, path: str) -> str:
    r = session.get(_url(path), timeout=10)
    return _extract_csrf(r.text)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True, scope="module")
def _require_demo_users():
    """Skip every test in this module when ENABLE_DEMO_USERS is not set on the server."""
    if not _demo_users_enabled():
        warnings.warn("ENABLE_DEMO_USERS is not set on this server — skipping demo user tests.", UserWarning)
        pytest.skip("ENABLE_DEMO_USERS is not set on this server")


@pytest.fixture(scope="module")
def demo_ctx():
    email = _fresh_email()
    _create_demo_user(email)
    yield {"email": email, "password": DEMO_PASSWORD}
    cleanup_user(email)


@pytest.fixture(scope="module")
def real_ctx(driver, w):
    ctx = setup_user(driver, w)
    yield ctx
    cleanup_user(ctx["email"])


# ---------------------------------------------------------------------------
# Management command
# ---------------------------------------------------------------------------

class TestCreateUserDemoFlags:

    def test_create_demo_user_flag(self, driver, w):
        email = _fresh_email()
        try:
            r = subprocess.run(
                ["docker", "exec", DOCKER_WEB, "python", "manage.py",
                 "create_user", email, "-p", DEMO_PASSWORD, "--demo"],
                capture_output=True, text=True, timeout=15,
            )
            assert r.returncode == 0
            is_demo = _shell(
                f"from feusers.models import FeUser; "
                f"print(FeUser.objects.get(email='{email}').is_demo)"
            )
            assert is_demo == "True"
        finally:
            cleanup_user(email)

    def test_create_user_ai_trial_budget_flag(self, driver, w):
        email = _fresh_email()
        try:
            r = subprocess.run(
                ["docker", "exec", DOCKER_WEB, "python", "manage.py",
                 "create_user", email, "-p", DEMO_PASSWORD, "--ai-trial-budget", "42"],
                capture_output=True, text=True, timeout=15,
            )
            assert r.returncode == 0
            budget = _shell(
                f"from feusers.models import FeUser; "
                f"print(FeUser.objects.get(email='{email}').special_ai_trial_budget)"
            )
            assert budget == "42"
        finally:
            cleanup_user(email)

    def test_create_demo_user_with_budget(self, driver, w):
        email = _fresh_email()
        try:
            r = subprocess.run(
                ["docker", "exec", DOCKER_WEB, "python", "manage.py",
                 "create_user", email, "-p", DEMO_PASSWORD,
                 "--demo", "--ai-trial-budget", "100"],
                capture_output=True, text=True, timeout=15,
            )
            assert r.returncode == 0
            row = _shell(
                f"from feusers.models import FeUser; "
                f"u = FeUser.objects.get(email='{email}'); "
                f"print(u.is_demo, u.special_ai_trial_budget)"
            )
            assert "True 100" in row
        finally:
            cleanup_user(email)


# ---------------------------------------------------------------------------
# Demo banner
# ---------------------------------------------------------------------------

class TestDemoBanner:

    def test_banner_shown_after_login(self, driver, w, demo_ctx):
        driver.delete_all_cookies()
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", demo_ctx["email"])
        fill(w, By.ID, "id_password", demo_ctx["password"])
        click(w, By.CSS_SELECTOR, "button[type=submit]")
        time.sleep(2)
        assert "/demo-banner/" in driver.current_url, (
            f"Expected banner redirect, got: {driver.current_url}"
        )
        assert "Okay, I understand" in driver.page_source

    def test_protected_page_redirects_to_banner(self, driver, w, demo_ctx):
        # After login without accepting banner, any protected page should redirect.
        driver.delete_all_cookies()
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", demo_ctx["email"])
        fill(w, By.ID, "id_password", demo_ctx["password"])
        click(w, By.CSS_SELECTOR, "button[type=submit]")
        time.sleep(2)
        # Try to navigate directly to dashboard.
        driver.get(_url("/budget/"))
        time.sleep(1)
        assert "/demo-banner/" in driver.current_url

    def test_banner_accept_proceeds_to_dashboard(self, driver, w, demo_ctx):
        # Accept the banner and verify we land on the dashboard.
        click(w, By.ID, "btn-demo-accept")
        time.sleep(2)
        assert "/budget/" in driver.current_url

    def test_banner_shown_again_after_logout(self, driver, w, demo_ctx):
        # Click the real logout button so the server flushes the session.
        click(w, By.ID, "logout-button")
        time.sleep(1)
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", demo_ctx["email"])
        fill(w, By.ID, "id_password", demo_ctx["password"])
        click(w, By.CSS_SELECTOR, "button[type=submit]")
        time.sleep(2)
        assert "/demo-banner/" in driver.current_url
        # Accept so other tests in this class can proceed.
        click(w, By.ID, "btn-demo-accept")
        time.sleep(2)

    def test_banner_content_mentions_restrictions(self, driver, w, demo_ctx):
        driver.delete_all_cookies()
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", demo_ctx["email"])
        fill(w, By.ID, "id_password", demo_ctx["password"])
        click(w, By.CSS_SELECTOR, "button[type=submit]")
        time.sleep(2)
        src = driver.page_source
        assert "demo" in src.lower()
        assert "personal" in src.lower() or "sensitive" in src.lower()
        assert "deleted" in src.lower() or "reset" in src.lower()
        # Accept for cleanup.
        click(w, By.ID, "btn-demo-accept")
        time.sleep(1)


# ---------------------------------------------------------------------------
# UI restrictions
# ---------------------------------------------------------------------------

def _demo_login_and_accept(driver, w, demo_ctx):
    driver.delete_all_cookies()
    driver.get(_url("/login/"))
    fill(w, By.ID, "id_email", demo_ctx["email"])
    fill(w, By.ID, "id_password", demo_ctx["password"])
    click(w, By.CSS_SELECTOR, "button[type=submit]")
    time.sleep(2)
    if "/demo-banner/" in driver.current_url:
        click(w, By.ID, "btn-demo-accept")
        time.sleep(2)


class TestDemoUserUIRestrictions:

    def test_profile_api_key_section_disabled(self, driver, w, demo_ctx):
        _demo_login_and_accept(driver, w, demo_ctx)
        driver.get(_url("/profile/"))
        time.sleep(1)
        src = driver.page_source
        # The generate button must be present but disabled.
        btns = driver.find_elements(By.XPATH, "//button[@disabled and contains(., 'Generate API key')]")
        assert btns, "Expected disabled 'Generate API key' button for demo user"

    def test_profile_ai_section_disabled(self, driver, w, demo_ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        # The fieldset wrapping AI section should be disabled.
        fieldsets = driver.find_elements(By.CSS_SELECTOR, "fieldset[disabled]")
        assert fieldsets, "Expected disabled fieldset around AI section for demo user"

    def test_profile_delete_account_disabled(self, driver, w, demo_ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        btns = driver.find_elements(By.XPATH, "//button[@disabled and contains(., 'Delete account')]")
        assert btns, "Expected disabled 'Delete account' button for demo user"

    def test_buddies_invite_form_disabled(self, driver, w, demo_ctx):
        driver.get(_url("/buddies/"))
        time.sleep(1)
        # The invite input must be disabled.
        disabled_inputs = driver.find_elements(
            By.XPATH, "//input[@type='email' and @disabled]"
        )
        assert disabled_inputs, "Expected disabled email invite input for demo user"


# ---------------------------------------------------------------------------
# Server-side enforcement (pentest)
# ---------------------------------------------------------------------------

class TestDemoUserServerEnforcement:

    def test_cannot_delete_account_via_post(self, demo_ctx):
        s = _http_session(demo_ctx["email"], demo_ctx["password"])
        csrf = _get_csrf(s, "/account/delete/")
        r = s.post(_url("/account/delete/"), data={
            "csrfmiddlewaretoken": csrf,
            "password": demo_ctx["password"],
        }, allow_redirects=False, timeout=10)
        # Must not redirect to landing page (which would indicate deletion).
        assert r.status_code != 302 or "/account/delete/" in r.headers.get("Location", "") or r.status_code == 200
        # Verify user still exists.
        exists = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.filter(email='{demo_ctx['email']}').exists())"
        )
        assert exists == "True", "Demo user was deleted but should not have been"

    def test_cannot_set_anthropic_api_key(self, demo_ctx):
        s = _http_session(demo_ctx["email"], demo_ctx["password"])
        csrf = _get_csrf(s, "/profile/")
        s.post(_url("/profile/"), data={
            "csrfmiddlewaretoken": csrf,
            "action": "ai",
            "anthropic_api_key": "sk-ant-hacked-key-123",
            "ai_custom_instructions": "",
        }, allow_redirects=True, timeout=10)
        key = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{demo_ctx['email']}').anthropic_api_key)"
        )
        assert "hacked" not in key, "Demo user's Anthropic key was set despite restriction"

    def test_cannot_generate_rest_api_key(self, demo_ctx):
        s = _http_session(demo_ctx["email"], demo_ctx["password"])
        csrf = _get_csrf(s, "/profile/")
        s.post(_url("/api-key/generate/"), data={
            "csrfmiddlewaretoken": csrf,
        }, allow_redirects=True, timeout=10)
        api_key = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{demo_ctx['email']}').api_key)"
        )
        assert api_key in ("None", ""), f"Demo user got a REST API key: {api_key}"

    def test_cannot_invite_buddy(self, demo_ctx):
        s = _http_session(demo_ctx["email"], demo_ctx["password"])
        target_email = f"victim.{uuid.uuid4().hex[:6]}@example.com"
        csrf = _get_csrf(s, "/buddies/my-buddies/")
        r = s.post(_url("/buddies/invite-actual/"), data={
            "csrfmiddlewaretoken": csrf,
            "email": target_email,
        }, allow_redirects=True, timeout=10)
        assert "Demo accounts cannot invite buddies" in r.text or r.status_code in (403, 400)

    def test_cannot_send_personal_merge_invite(self, demo_ctx):
        """Demo user cannot use 'merge into...' on their personal offline buddy."""
        dummy_id = _shell(
            f"from feusers.models import FeUser; from buddies.models import DummyUser; "
            f"u = FeUser.objects.get(email='{demo_ctx['email']}'); "
            f"d = DummyUser.objects.create(display_name='OfflinePal', owning_feuser=u); print(d.uid)"
        )
        try:
            s = _http_session(demo_ctx["email"], demo_ctx["password"])
            csrf = _get_csrf(s, "/buddies/my-buddies/")
            r = s.post(_url(f"/buddies/dummy/{dummy_id}/merge/"), data={
                "csrfmiddlewaretoken": csrf,
                "target_key": f"f{uuid.uuid4().int % 100000}",
            }, allow_redirects=True, timeout=10)
            assert "Demo accounts cannot merge buddies" in r.text or r.status_code in (403, 400)
        finally:
            _shell(f"from buddies.models import DummyUser; DummyUser.objects.filter(uid={dummy_id}).delete()")

    def test_cannot_invite_project_member(self, demo_ctx):
        """Demo user cannot invite anyone to a project via /projects/<id>/invite/."""
        project_id = _shell(
            f"from feusers.models import FeUser; from buddies.services import ProjectService; "
            f"u = FeUser.objects.get(email='{demo_ctx['email']}'); "
            f"g = ProjectService.create_group(u, 'DemoProjectInviteTest'); print(g.uid)"
        )
        try:
            s = _http_session(demo_ctx["email"], demo_ctx["password"])
            csrf = _get_csrf(s, f"/projects/{project_id}/settings/")
            r = s.post(_url(f"/projects/{project_id}/invite/"), data={
                "csrfmiddlewaretoken": csrf,
                "email": f"victim.{uuid.uuid4().hex[:6]}@example.com",
            }, allow_redirects=True, timeout=10)
            assert "Demo accounts cannot invite" in r.text or r.status_code in (403, 400)
        finally:
            _shell(f"from buddies.models import Project; Project.objects.filter(uid={project_id}).delete()")

    def test_cannot_send_project_merge_invite(self, demo_ctx):
        """Demo user cannot use 'merge into...' on a project's offline member."""
        ids = _shell(
            f"from feusers.models import FeUser; from buddies.services import ProjectService; "
            f"from buddies.models import DummyUser; "
            f"u = FeUser.objects.get(email='{demo_ctx['email']}'); "
            f"g = ProjectService.create_group(u, 'DemoProjectMergeTest'); "
            f"d = DummyUser.objects.create(display_name='OfflineProjectPal', owning_group=g); "
            f"print(g.uid, d.uid)"
        )
        project_id, dummy_id = ids.split()
        try:
            s = _http_session(demo_ctx["email"], demo_ctx["password"])
            csrf = _get_csrf(s, f"/projects/{project_id}/settings/")
            r = s.post(_url(f"/projects/{project_id}/dummy/{dummy_id}/merge/"), data={
                "csrfmiddlewaretoken": csrf,
                "target_key": f"f{uuid.uuid4().int % 100000}",
            }, allow_redirects=True, timeout=10)
            assert "Demo accounts cannot merge buddies" in r.text or r.status_code in (403, 400)
        finally:
            _shell(f"from buddies.models import Project; Project.objects.filter(uid={project_id}).delete()")

    def test_cannot_send_partnership_invite(self, demo_ctx):
        import json as _json
        s = _http_session(demo_ctx["email"], demo_ctx["password"])
        csrf = _get_csrf(s, "/buddies/")
        r = s.post(_url("/buddies/partnership/invite/"), data=_json.dumps({"invitee_id": 9999}),
                   headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
                   timeout=10)
        assert r.status_code == 403
        assert "demo" in r.text.lower()

    def test_real_user_cannot_invite_demo_as_buddy(self, demo_ctx, real_ctx):
        s = _http_session(real_ctx["email"], real_ctx["password"])
        csrf = _get_csrf(s, "/buddies/my-buddies/")
        r = s.post(_url("/buddies/invite-actual/"), data={
            "csrfmiddlewaretoken": csrf,
            "email": demo_ctx["email"],
        }, allow_redirects=True, timeout=10)
        assert "not available" in r.text.lower() or r.status_code in (403, 400)
        link_exists = _shell(
            f"from feusers.models import FeUser; from buddies.models import BuddyLink; "
            f"from django.db.models import Q; "
            f"u1 = FeUser.objects.get(email='{real_ctx['email']}'); "
            f"u2 = FeUser.objects.get(email='{demo_ctx['email']}'); "
            f"print(BuddyLink.objects.filter(Q(user_a=u1,user_b=u2)|Q(user_a=u2,user_b=u1)).exists())"
        )
        assert link_exists == "False", "BuddyLink was created with a demo user"

    def test_real_user_cannot_invite_demo_to_project(self, demo_ctx, real_ctx):
        project_id = _shell(
            f"from feusers.models import FeUser; from buddies.services import ProjectService; "
            f"u = FeUser.objects.get(email='{real_ctx['email']}'); "
            f"g = ProjectService.create_group(u, 'RealUserPenTestProject'); print(g.uid)"
        )
        try:
            s = _http_session(real_ctx["email"], real_ctx["password"])
            csrf = _get_csrf(s, f"/projects/{project_id}/settings/")
            r = s.post(_url(f"/projects/{project_id}/invite/"), data={
                "csrfmiddlewaretoken": csrf,
                "email": demo_ctx["email"],
            }, allow_redirects=True, timeout=10)
            assert "not available" in r.text.lower() or r.status_code in (403, 400)
            member_exists = _shell(
                f"from feusers.models import FeUser; from buddies.models import Project, BuddyGroupMember; "
                f"demo = FeUser.objects.get(email='{demo_ctx['email']}'); "
                f"g = Project.objects.get(uid={project_id}); "
                f"print(BuddyGroupMember.objects.filter(group=g, feuser=demo).exists())"
            )
            assert member_exists == "False", "Demo user was added to a project"
        finally:
            _shell(f"from buddies.models import Project; Project.objects.filter(uid={project_id}).delete()")

    def test_real_user_cannot_send_merge_request_to_demo(self, demo_ctx, real_ctx):
        """A real user cannot target a demo account via 'merge into...' on a personal offline buddy."""
        dummy_id = _shell(
            f"from feusers.models import FeUser; from buddies.models import DummyUser; "
            f"u = FeUser.objects.get(email='{real_ctx['email']}'); "
            f"d = DummyUser.objects.create(display_name='RealUserOfflinePal', owning_feuser=u); print(d.uid)"
        )
        try:
            demo_pk = _shell(
                f"from feusers.models import FeUser; "
                f"print(FeUser.objects.get(email='{demo_ctx['email']}').pk)"
            )
            s = _http_session(real_ctx["email"], real_ctx["password"])
            csrf = _get_csrf(s, "/buddies/my-buddies/")
            r = s.post(_url(f"/buddies/dummy/{dummy_id}/merge/"), data={
                "csrfmiddlewaretoken": csrf,
                "target_key": f"f{demo_pk}",
            }, allow_redirects=True, timeout=10)
            assert "cannot be merge targets" in r.text.lower() or r.status_code in (403, 400)
            invite_exists = _shell(
                f"from buddies.models import DummyMergeInvite; "
                f"print(DummyMergeInvite.objects.filter(dummy_id={dummy_id}).exists())"
            )
            assert invite_exists == "False", "A merge invite was created targeting a demo account"
        finally:
            _shell(f"from buddies.models import DummyUser; DummyUser.objects.filter(uid={dummy_id}).delete()")

    def test_real_user_cannot_send_merge_request_to_demo_in_project(self, demo_ctx, real_ctx):
        """A project admin cannot target a demo account via 'merge into...' on an offline project member."""
        ids = _shell(
            f"from feusers.models import FeUser; from buddies.services import ProjectService; "
            f"from buddies.models import DummyUser; "
            f"u = FeUser.objects.get(email='{real_ctx['email']}'); "
            f"g = ProjectService.create_group(u, 'RealUserMergeDemoTargetProject'); "
            f"d = DummyUser.objects.create(display_name='ProjectOfflinePal', owning_group=g); "
            f"print(g.uid, d.uid)"
        )
        project_id, dummy_id = ids.split()
        try:
            demo_pk = _shell(
                f"from feusers.models import FeUser; "
                f"print(FeUser.objects.get(email='{demo_ctx['email']}').pk)"
            )
            s = _http_session(real_ctx["email"], real_ctx["password"])
            csrf = _get_csrf(s, f"/projects/{project_id}/settings/")
            r = s.post(_url(f"/projects/{project_id}/dummy/{dummy_id}/merge/"), data={
                "csrfmiddlewaretoken": csrf,
                "target_key": f"f{demo_pk}",
            }, allow_redirects=True, timeout=10)
            assert "cannot be merge targets" in r.text.lower() or r.status_code in (403, 400)
            invite_exists = _shell(
                f"from buddies.models import DummyMergeInvite; "
                f"print(DummyMergeInvite.objects.filter(dummy_id={dummy_id}).exists())"
            )
            assert invite_exists == "False", "A merge invite was created targeting a demo account"
        finally:
            _shell(f"from buddies.models import Project; Project.objects.filter(uid={project_id}).delete()")

    def test_demo_user_cannot_send_merge_request_to_real_user(self, demo_ctx, real_ctx):
        """
        Service-layer defense in depth: request_merge_with_feuser must reject a
        demo sender on its own merits, not just rely on the view's early
        'if feuser.is_demo' redirect (buddies/views/buddies.py merge_dummy).
        Called directly so the guard is proven even with a real, valid target.
        """
        dummy_id = _shell(
            f"from feusers.models import FeUser; from buddies.models import DummyUser; "
            f"u = FeUser.objects.get(email='{demo_ctx['email']}'); "
            f"d = DummyUser.objects.create(display_name='DemoServiceLayerPal', owning_feuser=u); print(d.uid)"
        )
        try:
            outcome = _shell(
                f"from feusers.models import FeUser; from buddies.models import DummyUser; "
                f"from buddies.services import BuddyLifecycleService; "
                f"demo = FeUser.objects.get(email='{demo_ctx['email']}'); "
                f"real = FeUser.objects.get(email='{real_ctx['email']}'); "
                f"d = DummyUser.objects.get(uid={dummy_id}); "
                f"outcome, _ = BuddyLifecycleService.request_merge_with_feuser(demo, d, real); "
                f"print(outcome)"
            )
            assert outcome.strip() == "demo_restricted", f"Expected demo sender to be rejected, got: {outcome}"
            invite_exists = _shell(
                f"from buddies.models import DummyMergeInvite; "
                f"print(DummyMergeInvite.objects.filter(dummy_id={dummy_id}).exists())"
            )
            assert invite_exists == "False", "A merge invite was created by a demo sender"
        finally:
            _shell(f"from buddies.models import DummyUser; DummyUser.objects.filter(uid={dummy_id}).delete()")

    def test_demo_admin_cannot_send_merge_request_to_real_user_in_project(self, demo_ctx, real_ctx):
        """Same service-layer defense in depth as above, for the project-scoped
        request_group_merge_with_feuser (buddies/views/projects.py project_merge_dummy)."""
        ids = _shell(
            f"from feusers.models import FeUser; from buddies.services import ProjectService; "
            f"from buddies.models import DummyUser; "
            f"u = FeUser.objects.get(email='{demo_ctx['email']}'); "
            f"g = ProjectService.create_group(u, 'DemoAdminServiceLayerProject'); "
            f"d = DummyUser.objects.create(display_name='DemoServiceLayerProjectPal', owning_group=g); "
            f"print(g.uid, d.uid)"
        )
        project_id, dummy_id = ids.split()
        try:
            outcome = _shell(
                f"from feusers.models import FeUser; from buddies.models import Project, DummyUser; "
                f"from buddies.services import ProjectService; "
                f"demo = FeUser.objects.get(email='{demo_ctx['email']}'); "
                f"real = FeUser.objects.get(email='{real_ctx['email']}'); "
                f"g = Project.objects.get(uid={project_id}); "
                f"d = DummyUser.objects.get(uid={dummy_id}); "
                f"outcome, _ = ProjectService.request_group_merge_with_feuser(demo, g, d, real); "
                f"print(outcome)"
            )
            assert outcome.strip() == "demo_restricted", f"Expected demo admin to be rejected, got: {outcome}"
            invite_exists = _shell(
                f"from buddies.models import DummyMergeInvite; "
                f"print(DummyMergeInvite.objects.filter(dummy_id={dummy_id}).exists())"
            )
            assert invite_exists == "False", "A merge invite was created by a demo admin"
        finally:
            _shell(f"from buddies.models import Project; Project.objects.filter(uid={project_id}).delete()")



# ---------------------------------------------------------------------------
# special_ai_trial_budget
# ---------------------------------------------------------------------------

class TestSpecialAITrialBudget:

    @pytest.fixture(scope="class")
    def budget_ctx(self):
        """Create a demo user with a small special budget for these tests."""
        email = _fresh_email()
        # 1 cent budget so any AI call exhausts it.
        _create_demo_user(email, ai_trial_budget=1)
        yield {"email": email, "password": DEMO_PASSWORD}
        cleanup_user(email)

    def test_special_budget_displayed_in_express_ui(self, driver, w, budget_ctx):
        """The AI express UI must show the special limit, not the global one."""
        trial_available = _shell(
            "from django.conf import settings; from budget.ai_trial import trial_is_disabled; "
            "print(bool(settings.AI_TRIAL_API_KEY and settings.AI_TRIAL_USAGE_LIMIT and not trial_is_disabled()))"
        )
        if trial_available != "True":
            pytest.skip("AI trial not configured")

        _demo_login_and_accept(driver, w, budget_ctx)
        driver.get(_url("/budget/ai/express-creation/"))
        time.sleep(1)
        # The page must NOT show "Monthly AI limit reached" yet (spent is 0).
        assert "Monthly AI limit reached" not in driver.page_source

    def test_special_budget_enforced(self, driver, w, budget_ctx):
        """Set spent to equal the special limit and verify the UI blocks AI."""
        trial_available = _shell(
            "from django.conf import settings; from budget.ai_trial import trial_is_disabled; "
            "print(bool(settings.AI_TRIAL_API_KEY and settings.AI_TRIAL_USAGE_LIMIT and not trial_is_disabled()))"
        )
        if trial_available != "True":
            pytest.skip("AI trial not configured")

        email = budget_ctx["email"]
        # Set spent >= special_ai_trial_budget (1 cent).
        _shell(
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"u.ai_trial_budget_spent = 1; "
            f"u.save(update_fields=['ai_trial_budget_spent'])"
        )
        try:
            _demo_login_and_accept(driver, w, budget_ctx)
            driver.get(_url("/budget/ai/express-creation/"))
            time.sleep(1)
            assert "Monthly AI limit reached" in driver.page_source
            assert driver.find_elements(By.CSS_SELECTOR, ".trial-blocked")
        finally:
            _shell(
                f"from feusers.models import FeUser; "
                f"u = FeUser.objects.get(email='{email}'); "
                f"u.ai_trial_budget_spent = 0; "
                f"u.save(update_fields=['ai_trial_budget_spent'])"
            )


# ---------------------------------------------------------------------------
# Profile field restrictions
# ---------------------------------------------------------------------------

class TestDemoProfileFieldRestrictions:
    """
    Server-side and UI tests for allowed vs. forbidden profile fields.
    Allowed:  currency, month_start_day, month_start_prev, unspent_allowance_action
    Forbidden: first_name, last_name
    Blocked actions: notifications, email, password, ai (action=ai)
    """

    # -- Server: allowed fields are saved --

    def test_server_allows_currency_change(self, demo_ctx):
        s = _http_session(demo_ctx["email"], demo_ctx["password"])
        csrf = _get_csrf(s, "/profile/")
        s.post(_url("/profile/"), data={
            "csrfmiddlewaretoken": csrf,
            "action": "profile",
            "first_name": "HackedName",
            "last_name": "HackedLast",
            "currency": "$",
            "month_start_day": "1",
            "month_start_prev": "False",
            "unspent_allowance_action": "do_nothing",
        }, allow_redirects=True, timeout=10)
        currency = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{demo_ctx['email']}').currency)"
        )
        assert currency == "$", f"currency not saved: {currency!r}"

    def test_server_blocks_first_name_change(self, demo_ctx):
        original = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{demo_ctx['email']}').first_name)"
        )
        s = _http_session(demo_ctx["email"], demo_ctx["password"])
        csrf = _get_csrf(s, "/profile/")
        s.post(_url("/profile/"), data={
            "csrfmiddlewaretoken": csrf,
            "action": "profile",
            "first_name": "HackedFirstName",
            "last_name": "HackedLastName",
            "currency": original or "€",
            "month_start_day": "1",
            "month_start_prev": "False",
            "unspent_allowance_action": "do_nothing",
        }, allow_redirects=True, timeout=10)
        after = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{demo_ctx['email']}').first_name)"
        )
        assert after != "HackedFirstName", "Demo user's first_name was changed despite restriction"

    def test_server_blocks_last_name_change(self, demo_ctx):
        original = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{demo_ctx['email']}').last_name)"
        )
        s = _http_session(demo_ctx["email"], demo_ctx["password"])
        csrf = _get_csrf(s, "/profile/")
        s.post(_url("/profile/"), data={
            "csrfmiddlewaretoken": csrf,
            "action": "profile",
            "first_name": "Legit",
            "last_name": "HackedLastName",
            "currency": "€",
            "month_start_day": "1",
            "month_start_prev": "False",
            "unspent_allowance_action": "do_nothing",
        }, allow_redirects=True, timeout=10)
        after = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{demo_ctx['email']}').last_name)"
        )
        assert after != "HackedLastName", "Demo user's last_name was changed despite restriction"

    def test_server_blocks_notifications_action(self, demo_ctx):
        original = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{demo_ctx['email']}').email_notifications)"
        )
        # Force a known state: enable notifications first via shell, then try to disable via POST.
        _shell(
            f"from feusers.models import FeUser; "
            f"u = FeUser.objects.get(email='{demo_ctx['email']}'); "
            f"u.email_notifications = True; u.save(update_fields=['email_notifications'])"
        )
        s = _http_session(demo_ctx["email"], demo_ctx["password"])
        csrf = _get_csrf(s, "/profile/")
        s.post(_url("/profile/"), data={
            "csrfmiddlewaretoken": csrf,
            "action": "notifications",
            # Omitting email_notifications checkbox = False (unchecked)
        }, allow_redirects=True, timeout=10)
        after = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{demo_ctx['email']}').email_notifications)"
        )
        # Should still be True — POST was silently ignored.
        assert after == "True", "Demo user's notification preference was changed despite restriction"

    def test_server_blocks_email_change(self, demo_ctx):
        s = _http_session(demo_ctx["email"], demo_ctx["password"])
        csrf = _get_csrf(s, "/profile/")
        s.post(_url("/profile/"), data={
            "csrfmiddlewaretoken": csrf,
            "action": "email",
            "email": "hacked@example.com",
        }, allow_redirects=True, timeout=10)
        current_email = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{demo_ctx['email']}').email)"
        )
        assert current_email == demo_ctx["email"], "Demo user's email was changed despite restriction"

    def test_server_blocks_password_change(self, demo_ctx):
        s = _http_session(demo_ctx["email"], demo_ctx["password"])
        csrf = _get_csrf(s, "/profile/")
        s.post(_url("/profile/"), data={
            "csrfmiddlewaretoken": csrf,
            "action": "password",
            "current_password": demo_ctx["password"],
            "new_password": "H@ckedPw999!",
            "confirm_password": "H@ckedPw999!",
        }, allow_redirects=True, timeout=10)
        # Verify original password still works by logging in again.
        s2 = _http_session(demo_ctx["email"], demo_ctx["password"])
        r = s2.get(_url("/profile/"), timeout=10)
        assert r.status_code == 200, "Demo user's password was changed: original login no longer works"

    def test_server_blocks_ai_custom_instructions(self, demo_ctx):
        s = _http_session(demo_ctx["email"], demo_ctx["password"])
        csrf = _get_csrf(s, "/profile/")
        s.post(_url("/profile/"), data={
            "csrfmiddlewaretoken": csrf,
            "action": "ai",
            "anthropic_api_key": "",
            "ai_custom_instructions": "Hacked instructions",
        }, allow_redirects=True, timeout=10)
        instructions = _shell(
            f"from feusers.models import FeUser; "
            f"print(FeUser.objects.get(email='{demo_ctx['email']}').ai_custom_instructions)"
        )
        assert "Hacked" not in instructions, "Demo user's AI custom instructions were changed despite restriction"

    # -- UI: allowed fields are editable --

    def test_ui_currency_field_is_editable(self, driver, w, demo_ctx):
        _demo_login_and_accept(driver, w, demo_ctx)
        driver.get(_url("/profile/"))
        time.sleep(1)
        # Currency input must not be disabled.
        currency_inputs = driver.find_elements(By.CSS_SELECTOR, "input[name='currency']:not([disabled])")
        assert currency_inputs, "Currency field is disabled for demo user but should be editable"

    # -- UI: forbidden fields are disabled --

    def test_ui_first_name_field_is_disabled(self, driver, w, demo_ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        disabled = driver.find_elements(By.CSS_SELECTOR, "input[name='first_name'][disabled]")
        assert disabled, "first_name field is not disabled for demo user"

    def test_ui_last_name_field_is_disabled(self, driver, w, demo_ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        disabled = driver.find_elements(By.CSS_SELECTOR, "input[name='last_name'][disabled]")
        assert disabled, "last_name field is not disabled for demo user"

    def test_ui_notifications_section_is_disabled(self, driver, w, demo_ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        # The notifications form should be inside a disabled fieldset.
        form = driver.find_element(By.ID, "notifications-form")
        # Walk up to find a disabled fieldset ancestor.
        fs = driver.find_elements(By.XPATH,
            "//fieldset[@disabled]//form[@id='notifications-form']"
            " | //form[@id='notifications-form']/ancestor::fieldset[@disabled]")
        assert fs, "Notifications form is not inside a disabled fieldset for demo user"

    def test_ui_email_section_is_disabled(self, driver, w, demo_ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        fs = driver.find_elements(By.XPATH,
            "//div[@id='section-email']//fieldset[@disabled]")
        assert fs, "Email section does not have a disabled fieldset for demo user"

    def test_ui_password_section_is_disabled(self, driver, w, demo_ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        fs = driver.find_elements(By.XPATH,
            "//div[@id='section-password']//fieldset[@disabled]")
        assert fs, "Password section does not have a disabled fieldset for demo user"

    def test_ui_ai_section_is_disabled(self, driver, w, demo_ctx):
        driver.get(_url("/profile/"))
        time.sleep(1)
        fs = driver.find_elements(By.XPATH,
            "//div[@id='section-ai']//fieldset[@disabled]")
        assert fs, "AI section does not have a disabled fieldset for demo user"


# ---------------------------------------------------------------------------
# reset_demo_user only deletes demo accounts
# ---------------------------------------------------------------------------

class TestResetDemoUserSafety:
    """
    Verifies that reset_demo_user ONLY deletes is_demo=True accounts and
    never touches regular users, even when those users exist alongside demo
    accounts with an expired last_seen.
    """

    def test_real_user_survives_demo_reset(self):
        real_email = f"real.{uuid.uuid4().hex[:8]}@example.com"
        demo_email = f"demosafety.{uuid.uuid4().hex[:8]}@example.com"

        # Create a regular user and a demo user.
        _shell(
            f"from feusers.models import FeUser; from budget.fixtures import create_defaults; "
            f"u = FeUser(email='{real_email}', first_name='Real', last_name='User', "
            f"is_active=True, is_confirmed=True); u.set_password('S@feTest1!'); u.save(); "
            f"create_defaults(u)"
        )
        _shell(
            f"from feusers.models import FeUser; from budget.fixtures import create_defaults; "
            f"u = FeUser(email='{demo_email}', first_name='Dean', last_name='Demo', "
            f"is_active=True, is_confirmed=True, is_demo=True); u.set_password('demo'); u.save(); "
            f"create_defaults(u)"
        )

        # Push the demo user's last_seen back 8 days to trigger the reset condition.
        _shell(
            f"from feusers.models import FeUser; from django.utils import timezone; "
            f"from datetime import timedelta; "
            f"u = FeUser.objects.get(email='{demo_email}'); "
            f"u.last_seen = timezone.now() - timedelta(days=8); "
            f"u.save(update_fields=['last_seen'])"
        )

        try:
            # Monkey-patch settings (already loaded) so the command uses our test addresses.
            _shell(
                f"from django.conf import settings; "
                f"settings.ENABLE_DEMO_USERS = True; "
                f"settings.DEMO_USER_EMAIL = '{demo_email}'; "
                f"settings.DEMO_USER_PASSWORD = 'demo'; "
                f"settings.DEMO_USER_AI_BUDGET = 0; "
                f"from django.core.management import call_command; "
                f"call_command('reset_demo_user')"
            )

            # The real user must still exist and must NOT be flagged as demo.
            real_exists = _shell(
                f"from feusers.models import FeUser; "
                f"print(FeUser.objects.filter(email='{real_email}', is_demo=False).exists())"
            )
            assert real_exists == "True", "Real user was deleted or corrupted by reset_demo_user"

            # The demo account should have been wiped and recreated fresh:
            # last_seen must be None (the stale 8-day-old record is gone).
            demo_last_seen = _shell(
                f"from feusers.models import FeUser; "
                f"u = FeUser.objects.get(email='{demo_email}'); "
                f"print(u.last_seen)"
            )
            assert demo_last_seen == "None", (
                f"Demo user still has old last_seen={demo_last_seen!r} — was not actually reset"
            )

        finally:
            _shell(
                f"from feusers.models import FeUser; "
                f"FeUser.objects.filter(email__in=['{real_email}', '{demo_email}']).delete()"
            )

    def test_reset_does_not_touch_non_demo_users_at_all(self):
        """Even with many real users present, none should be deleted."""
        emails = [f"realuser{i}.{uuid.uuid4().hex[:6]}@example.com" for i in range(3)]
        demo_email = f"demosafety2.{uuid.uuid4().hex[:8]}@example.com"

        for email in emails:
            _shell(
                f"from feusers.models import FeUser; "
                f"u = FeUser(email='{email}', is_active=True, is_confirmed=True); "
                f"u.set_password('x'); u.save()"
            )
        _shell(
            f"from feusers.models import FeUser; "
            f"u = FeUser(email='{demo_email}', first_name='Dean', last_name='Demo', is_active=True, is_confirmed=True, is_demo=True); "
            f"u.set_password('x'); u.save(); "
            f"from django.utils import timezone; from datetime import timedelta; "
            f"u.last_seen = timezone.now() - timedelta(days=9); u.save(update_fields=['last_seen'])"
        )

        try:
            _shell(
                f"from django.conf import settings; "
                f"settings.ENABLE_DEMO_USERS = True; "
                f"settings.DEMO_USER_EMAIL = '{demo_email}'; "
                f"settings.DEMO_USER_PASSWORD = 'x'; "
                f"settings.DEMO_USER_AI_BUDGET = 0; "
                f"from django.core.management import call_command; "
                f"call_command('reset_demo_user')"
            )

            for email in emails:
                still_there = _shell(
                    f"from feusers.models import FeUser; "
                    f"print(FeUser.objects.filter(email='{email}', is_demo=False).exists())"
                )
                assert still_there == "True", f"Real user {email} was deleted by reset_demo_user"
        finally:
            _shell(
                f"from feusers.models import FeUser; "
                f"FeUser.objects.filter(email__in={emails + [demo_email]}).delete()"
            )
