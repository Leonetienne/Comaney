"""
Project Settings "Add members": direct-buddy contact hints
(build/js/project_member_add.js).

- Invite by email: typing part of a direct buddy's first name, last name or
  email (any case) suggests them; clicking a suggestion fills their email.
  Existing members are never suggested. A green check + "This buddy is in your
  contacts" shows for a buddy's email, a gray "This buddy is not in your
  contact list" for any other email address.
- Add offline member: an email-like value, or a name matching a direct buddy
  (same matching rule), shows a warning; submitting anyway asks for
  confirmation first. Only one warning/dialog ever shows, email first.
- Hint lines are reserved, so showing a hint never shifts the layout.

Run: pytest tests/e2e/projects/test_member_add_contacts.py -v | tee logfile.log
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import (
    _shell, _login_as, _create_buddy_link, _create_group, _add_group_member,
)


def _type(driver, input_id: str, text: str) -> None:
    """Set an input's value and fire the input event the page listens to."""
    driver.execute_script(
        "const i = document.getElementById(arguments[0]);"
        "i.focus(); i.value = arguments[1];"
        "i.dispatchEvent(new Event('input', {bubbles: true}));",
        input_id, text,
    )
    time.sleep(0.4)


def _suggested_emails(driver) -> list:
    return [
        li.get_attribute("data-email")
        for li in driver.find_elements(By.CSS_SELECTOR, "#project-invite-suggestions .contact-suggestion")
        if li.is_displayed()
    ]


def _hint(driver, hint_id: str) -> str:
    return driver.find_element(By.ID, hint_id).text.strip()


def _offline_members(group_id: int) -> str:
    return _shell(
        f"from buddies.models import ProjectMember; "
        f"print(sorted(m.dummy.display_name for m in "
        f"ProjectMember.objects.filter(group_id={group_id}, dummy__isnull=False)))"
    )


def _section_top(driver) -> float:
    """Document offset of the "Project settings" heading below both forms."""
    return driver.execute_script(
        "const h = [...document.querySelectorAll('h2')].find(e => e.textContent.includes('Project settings'));"
        "return h.getBoundingClientRect().top + window.scrollY;"
    )


@pytest.fixture(scope="module")
def ctx(driver, w):
    admin = setup_user(driver, w, first_name="Ada", last_name="Admin")
    leon = setup_user(None, None, first_name="Leon", last_name="Etienne")
    sabine = setup_user(None, None, first_name="Sabine", last_name="Leonhardt")
    member = setup_user(None, None, first_name="Mia", last_name="Member")
    for u in (leon, sabine, member):
        _create_buddy_link(admin["email"], u["email"])
    group_id = int(_create_group(admin["email"], "Contacts Project"))
    _add_group_member(group_id, member["email"])
    _login_as(driver, admin)
    yield {"admin": admin, "leon": leon, "sabine": sabine, "member": member, "group_id": group_id}
    for u in (admin, leon, sabine, member):
        cleanup_user(u["email"])


class TestInviteSuggestions:

    def test_matches_first_name_case_insensitive(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['group_id']}/settings/"))
        time.sleep(1)
        _type(driver, "project-invite-email", "LEON")
        emails = _suggested_emails(driver)
        assert ctx["leon"]["email"] in emails
        assert ctx["sabine"]["email"] in emails, "'leon' is also part of the last name Leonhardt"

    def test_matches_last_name(self, driver, w, ctx):
        _type(driver, "project-invite-email", "etien")
        assert _suggested_emails(driver) == [ctx["leon"]["email"]]

    def test_matches_email(self, driver, w, ctx):
        _type(driver, "project-invite-email", ctx["sabine"]["email"][:10].upper())
        assert ctx["sabine"]["email"] in _suggested_emails(driver)

    def test_suggestion_shows_name_and_email(self, driver, w, ctx):
        _type(driver, "project-invite-email", "etien")
        li = driver.find_element(
            By.CSS_SELECTOR, f".contact-suggestion[data-email='{ctx['leon']['email']}']")
        assert "Leon Etienne" in li.text
        assert ctx["leon"]["email"] in li.text
        assert li.find_elements(By.CSS_SELECTOR, ".user-avatar"), "Suggestion must show the avatar"

    def test_existing_member_not_suggested(self, driver, w, ctx):
        _type(driver, "project-invite-email", "mia")
        assert _suggested_emails(driver) == []

    def test_click_fills_email(self, driver, w, ctx):
        _type(driver, "project-invite-email", "etien")
        driver.find_element(
            By.CSS_SELECTOR, f".contact-suggestion[data-email='{ctx['leon']['email']}']").click()
        time.sleep(0.4)
        value = driver.find_element(By.ID, "project-invite-email").get_attribute("value")
        assert value == ctx["leon"]["email"]
        assert _suggested_emails(driver) == []


class TestInviteHint:

    def test_contact_email_shows_green_check(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['group_id']}/settings/"))
        time.sleep(1)
        ctx["top_empty"] = _section_top(driver)
        _type(driver, "project-invite-email", ctx["leon"]["email"].upper())
        assert _hint(driver, "project-invite-hint") == "This buddy is in your contacts"
        assert "input-hint--success" in driver.find_element(By.ID, "project-invite-hint").get_attribute("class")
        assert driver.find_element(By.ID, "project-invite-check").is_displayed()

    def test_hint_does_not_shift_layout(self, driver, w, ctx):
        assert abs(_section_top(driver) - ctx["top_empty"]) < 0.5

    def test_unknown_email_shows_gray_hint(self, driver, w, ctx):
        _type(driver, "project-invite-email", "stranger@example.com")
        assert _hint(driver, "project-invite-hint") == "This buddy is not in your contact list"
        cls = driver.find_element(By.ID, "project-invite-hint").get_attribute("class")
        assert "input-hint--success" not in cls
        assert not driver.find_element(By.ID, "project-invite-check").is_displayed()

    def test_empty_input_shows_no_hint(self, driver, w, ctx):
        _type(driver, "project-invite-email", "")
        assert _hint(driver, "project-invite-hint") == ""


class TestOfflineMemberNameCheck:

    WARNING = ("You already have a contact named {name}. "
               "You might want to invite their user instead of creating an offline record.")

    @pytest.mark.parametrize("typed", ["leon", "ETIENNE", "leon.", "Etienne"])
    def test_warns_on_first_name_last_name_or_email(self, driver, w, ctx, typed):
        driver.get(_url(f"/projects/{ctx['group_id']}/settings/"))
        time.sleep(1)
        if typed == "leon.":
            typed = ctx["leon"]["email"].split("@")[0][:6]  # part of the email
        _type(driver, "project-add-dummy-name", typed)
        assert _hint(driver, "project-add-dummy-hint") == self.WARNING.format(name="Leon Etienne")

    def test_no_warning_for_unknown_name(self, driver, w, ctx):
        _type(driver, "project-add-dummy-name", "Zacharias")
        assert _hint(driver, "project-add-dummy-hint") == ""

    def test_warning_does_not_shift_layout(self, driver, w, ctx):
        before = _section_top(driver)
        _type(driver, "project-add-dummy-name", "Etienne")
        assert abs(_section_top(driver) - before) < 0.5

    def test_add_asks_for_confirmation_and_cancel_keeps_nothing(self, driver, w, ctx):
        driver.find_element(By.ID, "btn-group-add-dummy").click()
        time.sleep(0.5)
        msg = driver.find_element(By.ID, "cdialog-msg").text
        assert self.WARNING.format(name="Leon Etienne") in msg
        assert driver.find_element(By.ID, "cdialog-ok").text == "Add"
        driver.find_element(By.ID, "cdialog-cancel").click()
        time.sleep(1)
        assert _offline_members(ctx["group_id"]) == "[]"

    def test_ok_creates_offline_member(self, driver, w, ctx):
        driver.find_element(By.ID, "btn-group-add-dummy").click()
        time.sleep(0.5)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(2)
        assert _offline_members(ctx["group_id"]) == "['Etienne']"

    def test_unknown_name_adds_without_dialog(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['group_id']}/settings/"))
        time.sleep(1)
        _type(driver, "project-add-dummy-name", "Zacharias")
        driver.find_element(By.ID, "btn-group-add-dummy").click()
        time.sleep(2)
        assert _offline_members(ctx["group_id"]) == "['Etienne', 'Zacharias']"


class TestOfflineMemberEmailCheck:

    EMAIL_WARNING = ('This looks like an email address. Offline members are only placeholders: '
                     'nobody gets invited or emailed. To invite someone, use "Invite by email" above.')

    def test_email_shows_email_warning(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['group_id']}/settings/"))
        time.sleep(1)
        _type(driver, "project-add-dummy-name", "someone@example.com")
        assert _hint(driver, "project-add-dummy-hint") == self.EMAIL_WARNING

    def test_buddy_email_shows_only_the_email_warning(self, driver, w, ctx):
        # A buddy's email matches both checks; only the email warning may show.
        _type(driver, "project-add-dummy-name", ctx["leon"]["email"])
        hint = _hint(driver, "project-add-dummy-hint")
        assert hint == self.EMAIL_WARNING
        assert "You already have a contact" not in hint

    def test_not_an_email_without_dot_after_at(self, driver, w, ctx):
        _type(driver, "project-add-dummy-name", "Zed@home")
        assert _hint(driver, "project-add-dummy-hint") == ""

    def test_email_warning_does_not_shift_layout(self, driver, w, ctx):
        _type(driver, "project-add-dummy-name", "")
        before = _section_top(driver)
        _type(driver, "project-add-dummy-name", "someone@example.com")
        assert abs(_section_top(driver) - before) < 0.5

    def test_submit_opens_single_dialog_and_cancel_keeps_nothing(self, driver, w, ctx):
        before = _offline_members(ctx["group_id"])
        _type(driver, "project-add-dummy-name", ctx["leon"]["email"])
        driver.find_element(By.ID, "btn-group-add-dummy").click()
        time.sleep(0.5)
        msg = driver.find_element(By.ID, "cdialog-msg").text
        assert msg == self.EMAIL_WARNING + " Add the offline member anyway?"
        driver.find_element(By.ID, "cdialog-cancel").click()
        time.sleep(1)
        assert not driver.find_element(By.ID, "cdialog-backdrop").is_displayed(), \
            "No second dialog may follow the first one"
        assert _offline_members(ctx["group_id"]) == before
