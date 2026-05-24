"""
Management command tests: create_user, set_user_password, remove_user_2fa, delete_user.

create_user creates a confirmed, active account.
set_user_password updates the password for an existing account.
remove_user_2fa clears TOTP fields so the user can log in with password only.
delete_user permanently removes the account.
Both create_user and set_user_password accept -p for non-interactive use and
prompt via getpass otherwise. delete_user accepts --yes to skip confirmation.
"""
import subprocess
import time
import uuid

import pyotp
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from helpers import (
    _url, fill, click, submit, wait_url, wait_text,
    cleanup_user, browser_login,
    DOCKER_WEB, PASSWORD,
)

NEW_PASSWORD = "R41nerWinkl3rH0s3np1nkl3r"


def _run(args, *, stdin_input=None, expect_failure=False):
    result = subprocess.run(
        ["docker", "exec", "-i", DOCKER_WEB, "python", "manage.py", *args],
        input=stdin_input,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if expect_failure:
        assert result.returncode != 0, (
            f"Expected command failure but it succeeded.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    else:
        assert result.returncode == 0, (
            f"Management command failed.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def _fresh_email():
    return f"mgmt.{uuid.uuid4().hex[:8]}@example.com"


@pytest.fixture(scope="module")
def ctx():
    c = {}
    yield c
    for key in ("email", "email2", "email3", "email4"):
        if key in c:
            cleanup_user(c[key])


class TestCreateUser:

    def test_create_user_with_password_flag(self, driver, w, ctx):
        email = _fresh_email()
        ctx["email"] = email
        _run(["create_user", email, "-p", PASSWORD])

    def test_created_user_can_log_in(self, driver, w, ctx):
        driver.delete_all_cookies()
        browser_login(driver, w, ctx["email"], PASSWORD)
        assert "/budget/" in driver.current_url

    def test_default_records_created(self, driver, w, ctx):
        # Verify default categories, tags, and dashboard cards were applied.
        script = (
            f"from feusers.models import FeUser; "
            f"from budget.models import Category, Tag, DashboardCard; "
            f"u = FeUser.objects.get(email='{ctx['email']}'); "
            f"print(Category.objects.filter(owning_feuser=u).count()); "
            f"print(Tag.objects.filter(owning_feuser=u).count()); "
            f"print(DashboardCard.objects.filter(owning_feuser=u).count())"
        )
        result = subprocess.run(
            ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c", script],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0, result.stderr
        cat_count, tag_count, card_count = (int(x) for x in result.stdout.strip().splitlines())
        assert cat_count > 0, "No default categories created"
        assert tag_count > 0, "No default tags created"
        assert card_count > 0, "No default dashboard cards created"

    def test_create_user_duplicate_email_fails(self, driver, w, ctx):
        _run(["create_user", ctx["email"], "-p", PASSWORD], expect_failure=True)

    def test_create_user_interactive(self, driver, w, ctx):
        email = _fresh_email()
        ctx["email2"] = email
        # No -p flag: password and confirmation are read from stdin.
        # getpass falls back to stdin when /dev/tty is unavailable (no-TTY docker exec).
        _run(["create_user", email], stdin_input=f"{PASSWORD}\n{PASSWORD}\n")

    def test_interactive_user_can_log_in(self, driver, w, ctx):
        driver.delete_all_cookies()
        browser_login(driver, w, ctx["email2"], PASSWORD)
        assert "/budget/" in driver.current_url


class TestSetUserPassword:

    def test_set_password_nonexistent_user_fails(self, driver, w, ctx):
        _run(["set_user_password", "nobody@example.com", "-p", NEW_PASSWORD], expect_failure=True)

    def test_set_password_with_flag(self, driver, w, ctx):
        email = _fresh_email()
        ctx["email3"] = email
        _run(["create_user", email, "-p", PASSWORD])
        _run(["set_user_password", email, "-p", NEW_PASSWORD])

    def test_new_password_works(self, driver, w, ctx):
        driver.delete_all_cookies()
        browser_login(driver, w, ctx["email3"], NEW_PASSWORD)
        assert "/budget/" in driver.current_url

    def test_old_password_rejected(self, driver, w, ctx):
        driver.delete_all_cookies()
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", ctx["email3"])
        fill(w, By.ID, "id_password", PASSWORD)
        click(w, By.CSS_SELECTOR, "button[type=submit]")
        time.sleep(1)
        assert "/budget/" not in driver.current_url

    def test_set_password_interactive(self, driver, w, ctx):
        _run(
            ["set_user_password", ctx["email3"]],
            stdin_input=f"{PASSWORD}\n{PASSWORD}\n",
        )
        driver.delete_all_cookies()
        browser_login(driver, w, ctx["email3"], PASSWORD)
        assert "/budget/" in driver.current_url


class TestRemoveUser2FA:

    def _setup_totp(self, driver, w, ctx):
        driver.get(_url("/totp/setup/"))
        click(w, By.CSS_SELECTOR, ".totp-secret-details summary")
        secret_el = w.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "code.totp-secret")))
        ctx["totp_secret_2fa"] = secret_el.text.strip()
        fill(w, By.ID, "id_code", pyotp.TOTP(ctx["totp_secret_2fa"]).now())
        submit(w)
        # skip recovery code page
        click(w, By.CSS_SELECTOR, "a.btn")

    def test_setup(self, driver, w, ctx):
        email = _fresh_email()
        ctx["email4"] = email
        _run(["create_user", email, "-p", PASSWORD])
        driver.delete_all_cookies()
        browser_login(driver, w, email, PASSWORD)
        self._setup_totp(driver, w, ctx)

    def test_remove_2fa_nonexistent_user_fails(self, driver, w, ctx):
        _run(["remove_user_2fa", "nobody@example.com"], expect_failure=True)

    def test_remove_user_2fa(self, driver, w, ctx):
        _run(["remove_user_2fa", ctx["email4"]])

    def test_login_without_totp_after_removal(self, driver, w, ctx):
        # After 2FA removal, logging in must not redirect to the TOTP verify page.
        driver.delete_all_cookies()
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", ctx["email4"])
        fill(w, By.ID, "id_password", PASSWORD)
        click(w, By.CSS_SELECTOR, "button[type=submit]")
        time.sleep(1)
        assert "/totp/verify/" not in driver.current_url
        assert "/budget/" in driver.current_url

    def test_remove_2fa_idempotent(self, driver, w, ctx):
        # Running the command a second time when 2FA is already off must succeed (no error).
        _run(["remove_user_2fa", ctx["email4"]])


class TestDeleteUser:

    def test_delete_nonexistent_user_fails(self, driver, w, ctx):
        _run(["delete_user", "nobody@example.com", "--yes"], expect_failure=True)

    def test_delete_user(self, driver, w, ctx):
        email = _fresh_email()
        _run(["create_user", email, "-p", PASSWORD])
        _run(["delete_user", email, "--yes"])
        # After deletion the login attempt must stay on the login page.
        driver.delete_all_cookies()
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", email)
        fill(w, By.ID, "id_password", PASSWORD)
        click(w, By.CSS_SELECTOR, "button[type=submit]")
        time.sleep(1)
        assert "/budget/" not in driver.current_url

    def test_delete_user_interactive(self, driver, w, ctx):
        email = _fresh_email()
        _run(["create_user", email, "-p", PASSWORD])
        _run(["delete_user", email], stdin_input="yes\n")
        driver.delete_all_cookies()
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", email)
        fill(w, By.ID, "id_password", PASSWORD)
        click(w, By.CSS_SELECTOR, "button[type=submit]")
        time.sleep(1)
        assert "/budget/" not in driver.current_url

    def test_delete_user_aborted(self, driver, w, ctx):
        # Answering anything other than "yes" must abort without deleting.
        email = _fresh_email()
        _run(["create_user", email, "-p", PASSWORD])
        _run(["delete_user", email], stdin_input="no\n")
        # User still exists: login must succeed.
        driver.delete_all_cookies()
        browser_login(driver, w, email, PASSWORD)
        assert "/budget/" in driver.current_url
        # Clean up the surviving user.
        _run(["delete_user", email, "--yes"])

    def test_delete_admin_user_transfers_group_admin_to_member(self, driver, w, ctx):
        """
        delete_user must call handle_account_deletion so that a group where the
        deleted user is admin is NOT cascade-deleted: a remaining member becomes
        the new admin instead.
        """
        import subprocess
        admin_email = _fresh_email()
        member_email = _fresh_email()
        _run(["create_user", admin_email, "-p", PASSWORD])
        _run(["create_user", member_email, "-p", PASSWORD])

        # Create a group with admin_email as admin and member_email as member.
        r = subprocess.run(
            [
                "docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c",
                f"from feusers.models import FeUser; from buddies.services import ProjectService; "
                f"from buddies.models import ProjectMember; "
                f"admin = FeUser.objects.get(email='{admin_email}'); "
                f"member = FeUser.objects.get(email='{member_email}'); "
                f"g = ProjectService.create_group(admin, 'CmdDelGroup'); "
                f"ProjectMember.objects.get_or_create(group=g, feuser=member); "
                f"print(g.pk)",
            ],
            capture_output=True, text=True, timeout=15,
        )
        assert r.returncode == 0, f"Group creation failed:\n{r.stderr}"
        group_pk = r.stdout.strip()

        # Delete the admin via management command.
        _run(["delete_user", admin_email, "--yes"])

        # The group must still exist and member_email must now be admin.
        r2 = subprocess.run(
            [
                "docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c",
                f"from buddies.models import Project, BuddyGroupMember; "
                f"from feusers.models import FeUser; "
                f"g = Project.objects.filter(pk={group_pk}).first(); "
                f"member = FeUser.objects.filter(email='{member_email}').first(); "
                f"print('EXISTS' if g else 'GONE'); "
                f"print('admin_ok' if (g and member and g.admin_feuser_id == member.pk) else 'wrong_admin'); "
                f"print('member_ok' if (g and member and BuddyGroupMember.objects.filter(group=g, feuser=member).exists()) else 'member_gone')",
            ],
            capture_output=True, text=True, timeout=15,
        )
        assert r2.returncode == 0, f"Verification shell failed:\n{r2.stderr}"
        result = r2.stdout.strip()

        assert "GONE" not in result, "Group must not be deleted when admin is removed via delete_user"
        assert "admin_ok" in result, "Group admin must be transferred to remaining member"
        assert "member_ok" in result, "Remaining member must still be in the group"

        # Clean up.
        _run(["delete_user", member_email, "--yes"])
