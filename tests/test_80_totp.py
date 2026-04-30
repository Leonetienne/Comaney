"""Two-factor authentication setup, login, and disable."""
import pyotp
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

from conftest import _url, fill, click, submit, wait_url, wait_text


class TestTotp:

    def test_43_setup_2fa(self, driver, w, ctx):
        driver.get(_url("/totp/setup/"))
        click(w, By.CSS_SELECTOR, ".totp-secret-details summary")
        secret_el = w.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "code.totp-secret")))
        ctx["totp_secret"] = secret_el.text.strip()

        code = pyotp.TOTP(ctx["totp_secret"]).now()
        fill(w, By.ID, "id_code", code)
        submit(w)

        recovery_el = w.until(EC.presence_of_element_located((By.ID, "recovery-code")))
        ctx["recovery_code"] = recovery_el.text.strip()
        click(w, By.CSS_SELECTOR, "a.btn")

    def test_44_login_with_totp(self, driver, w, ctx):
        click(w, By.CSS_SELECTOR, "button[type=submit]#logout-button")
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", ctx["email"])
        fill(w, By.ID, "id_password", ctx.get("password", "S3l3n!umTest"))
        submit(w)

        wait_url(w, "/totp/verify/")
        code = pyotp.TOTP(ctx["totp_secret"]).now()
        fill(w, By.ID, "id_code", code)
        submit(w)
        wait_url(w, "/budget/")

    def test_45_disable_2fa(self, driver, w, ctx):
        driver.get(_url("/totp/disable/"))
        code = pyotp.TOTP(ctx["totp_secret"]).now()
        fill(w, By.ID, "id_code", code)
        submit(w)
        wait_url(w, "/profile/")
        wait_text(driver, w, "Not enabled")

    def test_46_setup_2fa_again(self, driver, w, ctx):
        driver.get(_url("/totp/setup/"))
        click(w, By.CSS_SELECTOR, ".totp-secret-details summary")
        secret_el = w.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "code.totp-secret")))
        ctx["totp_secret"] = secret_el.text.strip()

        code = pyotp.TOTP(ctx["totp_secret"]).now()
        fill(w, By.ID, "id_code", code)
        submit(w)

        recovery_el = w.until(EC.presence_of_element_located((By.ID, "recovery-code")))
        ctx["recovery_code"] = recovery_el.text.strip()
        click(w, By.CSS_SELECTOR, "a.btn")

    def test_47_login_with_recovery_code(self, driver, w, ctx):
        click(w, By.CSS_SELECTOR, "button[type=submit]#logout-button")
        driver.get(_url("/login/"))
        fill(w, By.ID, "id_email", ctx["email"])
        fill(w, By.ID, "id_password", ctx.get("password", "S3l3n!umTest"))
        submit(w)

        wait_url(w, "/totp/verify/")
        click(w, By.LINK_TEXT, "Lost access to your app? Use a recovery code")
        wait_url(w, "/totp/verify/recovery/")
        fill(w, By.ID, "id_recovery", ctx["recovery_code"])
        submit(w)
        wait_url(w, "/")

    def test_48_setup_2fa_for_disable_recovery_test(self, driver, w, ctx):
        driver.get(_url("/totp/setup/"))
        click(w, By.CSS_SELECTOR, ".totp-secret-details summary")
        secret_el = w.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "code.totp-secret")))
        ctx["totp_secret"] = secret_el.text.strip()

        code = pyotp.TOTP(ctx["totp_secret"]).now()
        fill(w, By.ID, "id_code", code)
        submit(w)

        recovery_el = w.until(EC.presence_of_element_located((By.ID, "recovery-code")))
        ctx["recovery_code"] = recovery_el.text.strip()
        click(w, By.CSS_SELECTOR, "a.btn")

    def test_49_disable_2fa_with_recovery_code(self, driver, w, ctx):
        driver.get(_url("/totp/disable/"))
        click(w, By.LINK_TEXT, "Lost access to your app? Use a recovery code")
        wait_url(w, "/totp/disable/?recovery=1")
        fill(w, By.ID, "id_recovery", ctx["recovery_code"])
        submit(w)
        wait_url(w, "/profile/")
        wait_text(driver, w, "Not enabled")
