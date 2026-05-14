"""
Shared helpers specific to the buddies e2e test suite.
Import alongside the standard helpers.py from tests/e2e/.
"""
import subprocess
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from helpers import _url, DOCKER_WEB, PASSWORD


def _shell(code: str) -> str:
    """Run a Python snippet inside the container's Django shell."""
    r = subprocess.run(
        ["docker", "exec", DOCKER_WEB, "python", "manage.py", "shell", "-c", code],
        capture_output=True, text=True, timeout=20,
    )
    assert r.returncode == 0, f"Shell command failed:\n{r.stderr}\nCode: {code}"
    return r.stdout.strip()


def _login_as(driver, ctx_user: dict) -> None:
    """Switch the browser session to ctx_user (clears cookies first)."""
    driver.delete_all_cookies()
    driver.execute_script("sessionStorage.clear(); localStorage.clear();")
    driver.get(_url("/login/"))
    time.sleep(1)
    driver.find_element(By.ID, "id_email").send_keys(ctx_user["email"])
    driver.find_element(By.ID, "id_password").send_keys(ctx_user["password"])
    driver.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
    time.sleep(2)


def _confirm(driver) -> None:
    """Click OK in the in-DOM cdialog confirmation modal."""
    time.sleep(0.5)
    driver.find_element(By.ID, "cdialog-ok").click()
    time.sleep(1)


def _create_buddy_link(email_a: str, email_b: str) -> str:
    """Create a BuddyLink between two users; return link pk as string."""
    return _shell(
        f"from feusers.models import FeUser; from buddies.models import BuddyLink; "
        f"a = FeUser.objects.get(email='{email_a}'); "
        f"b = FeUser.objects.get(email='{email_b}'); "
        f"lo, hi = sorted([a, b], key=lambda u: u.pk); "
        f"lnk, _ = BuddyLink.objects.get_or_create(user_a=lo, user_b=hi); "
        f"print(lnk.pk)"
    )


def _get_pk(email: str) -> str:
    """Return the pk of the FeUser with the given email as a string."""
    return _shell(
        f"from feusers.models import FeUser; "
        f"print(FeUser.objects.get(email='{email}').pk)"
    )


def _create_group(admin_email: str, name: str) -> str:
    """Create a BuddyGroup via the service layer; return group pk as string."""
    return _shell(
        f"from buddies.services import BuddyGroupService; "
        f"from feusers.models import FeUser; "
        f"a = FeUser.objects.get(email='{admin_email}'); "
        f"g = BuddyGroupService.create_group(a, '{name}'); "
        f"print(g.pk)"
    )


def _add_group_member(group_id: int, member_email: str) -> None:
    """Add a feuser to a group as a regular member (no invite flow)."""
    _shell(
        f"from buddies.models import BuddyGroupMember, BuddyGroup; "
        f"from feusers.models import FeUser; "
        f"g = BuddyGroup.objects.get(pk={group_id}); "
        f"u = FeUser.objects.get(email='{member_email}'); "
        f"BuddyGroupMember.objects.get_or_create(group=g, feuser=u)"
    )


def _create_group_expense(admin_email: str, participant_email: str,
                           group_id: int, title: str = "Group Expense",
                           value: str = "100.00", share: str = "50.0") -> str:
    """Create an approved group expense; return expense pk as string."""
    return _shell(
        f"from budget.models import Expense; "
        f"from buddies.models import BuddySpending, BuddyGroup; "
        f"from feusers.models import FeUser; from decimal import Decimal; "
        f"a = FeUser.objects.get(email='{admin_email}'); "
        f"b = FeUser.objects.get(email='{participant_email}'); "
        f"g = BuddyGroup.objects.get(pk={group_id}); "
        f"e = Expense.objects.create(owning_feuser=a, title='{title}', "
        f"  type='expense', value=Decimal('{value}'), settled=False, "
        f"  buddy_approved=True, buddy_group=g); "
        f"BuddySpending.objects.create(expense=e, participant_feuser=b, "
        f"  share_percent=Decimal('{share}')); "
        f"print(e.pk)"
    )


def _create_personal_expense_with_buddy(
    owner_email: str, participant_pk: int, participant_type: str = "feuser",
    title: str = "Buddy Expense", value: str = "100.00",
    share: str = "50.0", approved: bool = True,
) -> str:
    """Create a personal buddy expense (no group); return pk as string."""
    approved_val = "True" if approved else "False"
    if participant_type == "feuser":
        participant_arg = f"participant_feuser_id={participant_pk}"
    else:
        participant_arg = f"participant_dummy_id={participant_pk}"
    return _shell(
        f"from budget.models import Expense; "
        f"from buddies.models import BuddySpending; "
        f"from feusers.models import FeUser; from decimal import Decimal; "
        f"o = FeUser.objects.get(email='{owner_email}'); "
        f"e = Expense.objects.create(owning_feuser=o, title='{title}', "
        f"  type='expense', value=Decimal('{value}'), settled=False, "
        f"  buddy_approved={approved_val}); "
        f"BuddySpending.objects.create(expense=e, {participant_arg}, "
        f"  share_percent=Decimal('{share}')); "
        f"print(e.pk)"
    )
