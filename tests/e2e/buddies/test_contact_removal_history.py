"""
Removing a real contact gives each side an own copy of what the other paid,
holding only its own share, and turns the other into an offline contact in its
own expenses, so the two share no expense afterwards; amounts and balances stay,
third participants see no change. Merging back keeps both copies, so the merge
request and its acceptance warn with the list of expenses that exist on both sides.
Run with: pytest -v tests/e2e/buddies/test_contact_removal_history.py | tee logfile.log
"""
import json
import time

import pytest
from selenium.webdriver.common.by import By

from bhelpers import _create_contact_link, _login_as, _shell
from helpers import _url, cleanup_user, setup_user

TITLES = ["CR Dinner", "CR Cinema", "CR Trip", "CR Pending Fuel", "CR Payback"]
OVERLAPS = [["CR Cinema", "60.00"], ["CR Dinner", "100.00"], ["CR Payback", "20.00"], ["CR Trip", "90.00"]]
OVERLAP_LINES = "CR Cinema, €60.00\nCR Dinner, €100.00\nCR Payback, €20.00\nCR Trip, €90.00"


def _setup(a, b, c):
    """A paid alone with B, B paid with A, A paid with B and C, B paid pending,
    and a settlement A paid back to B; plus overlays both ways and initiated_by on A's."""
    _shell(f"""
from decimal import Decimal as D
from budget.models import Expense, ExpenseDataOverlay, Category, Tag
from budget.services import upsert_overlay
from buddies.models import BuddySpending
from feusers.models import FeUser
a = FeUser.objects.get(email='{a}')
b = FeUser.objects.get(email='{b}')
c = FeUser.objects.get(email='{c}')

def exp(owner, title, value, rows, **kw):
    kw.setdefault('settled', False)
    e = Expense.objects.create(owning_feuser=owner, title=title, type='expense', value=D(value), **kw)
    for who, pct in rows:
        BuddySpending.objects.create(expense=e, participant_feuser=who, share_percent=D(pct))
    return e

dinner = exp(a, '{TITLES[0]}', '100', [(b, '50')], initiated_by_feuser=b)
cinema = exp(b, '{TITLES[1]}', '60', [(a, '25')],
             category=Category.objects.create(owning_feuser=b, title='Bert Movies'))
exp(a, '{TITLES[2]}', '90', [(b, '30'), (c, '30')])
exp(b, '{TITLES[3]}', '40', [(a, '50')], buddy_approved=False)
exp(a, '{TITLES[4]}', '20', [(b, '100')], is_buddies_settlement=True, settled=True)
ExpenseDataOverlay.objects.create(expense=dinner, feuser=b, note='b note')
upsert_overlay(cinema, a, Category.objects.create(owning_feuser=a, title='Anna Fun'),
               [Tag.objects.create(owning_feuser=a, title='Anna Night')])
""")


def _snapshot(emails, connected):
    """Per feuser: balance with each counterpart (real contact while connected,
    else the offline contact of the same name), shared amounts and offline contacts."""
    return json.loads(_shell(f"""
import json
from feusers.models import FeUser
from buddies.models import DummyUser
from buddies.services import BuddyQueryService
from buddies.services._helpers import _display_name
from budget.views._sharing import build_shared_qs
users = {{e: FeUser.objects.get(email=e) for e in {emails!r}}}
out = {{}}
for email, u in users.items():
    balances = {{}}
    for other_email, other in users.items():
        if other == u:
            continue
        name = _display_name(other)
        ghosts = DummyUser.objects.filter(owning_feuser=u, display_name=name, is_archive=False)
        if {connected!r} and other_email in {connected!r}.get(email, []):
            balances[name] = str(BuddyQueryService.get_net_debt(u, contact_feuser=other))
        elif ghosts.count() == 1:
            balances[name] = str(BuddyQueryService.get_net_debt(u, contact_dummy=ghosts.get()))
        else:
            balances[name] = f'{{ghosts.count()}} offline contacts'
    out[email] = {{
        'balances': balances,
        'amounts': sorted([q.title, str(q.effective_value)]
                          for q in build_shared_qs(u, None, None).filter(project__isnull=True)
                          if q.effective_value),
    }}
print(json.dumps(out))
"""))


def _records(emails, pair):
    """Every expense the feusers own with payer, shares, classification, notes and
    overlays (except the pair's on each other's), plus offline contacts and links."""
    return json.loads(_shell(f"""
import json
from budget.models import Expense
from buddies.models import ContactLink, DummyUser
def who(bs):
    return bs.participant_feuser.first_name if bs.participant_feuser else 'offline:' + bs.participant_dummy.display_name
expenses = []
for e in Expense.objects.filter(owning_feuser__email__in={emails!r}).order_by('title', 'owning_feuser__first_name'):
    expenses.append([
        e.title, e.owning_feuser.first_name,
        'offline:' + e.upfront_payee_dummy.display_name if e.is_dummy else e.owning_feuser.first_name,
        str(e.value), e.note, e.buddy_approved, e.settled, e.is_buddies_settlement,
        e.category.title if e.category else None, sorted(t.title for t in e.tags.all()),
        sorted([who(bs), str(bs.share_percent), bs.approval_state] for bs in e.buddy_spendings.all()),
        sorted([o.feuser.first_name, o.category.title if o.category else None,
                sorted(t.title for t in o.tags.all()), o.note]
               for o in e.data_overlays.exclude(feuser__email__in={pair!r})),
    ])
print(json.dumps({{
    'expenses': expenses,
    'offline_contacts': sorted(DummyUser.objects.filter(owning_feuser__email__in={emails!r})
                               .values_list('display_name', flat=True)),
    'links': ContactLink.objects.filter(user_a__email__in={emails!r}, user_b__email__in={emails!r}).count(),
}}))
"""))


def _references(owner, other):
    """Anything on owner's expenses that still points at the other feuser."""
    return json.loads(_shell(f"""
import json
from budget.models import Expense, ExpenseDataOverlay
from buddies.models import BuddySpending
own = Expense.objects.filter(owning_feuser__email='{owner}')
print(json.dumps({{
    'spendings': BuddySpending.objects.filter(expense__in=own, participant_feuser__email='{other}').count(),
    'overlays': ExpenseDataOverlay.objects.filter(expense__in=own, feuser__email='{other}').count(),
    'initiated': own.filter(initiated_by_feuser__email='{other}').count(),
    'foreign_dummies': BuddySpending.objects.filter(expense__in=own, participant_dummy__isnull=False)
                       .exclude(participant_dummy__owning_feuser__email='{owner}').count(),
}}))
"""))


def _overlaps(keeper, real, ghost_name):
    return json.loads(_shell(f"""
import json
from buddies.models import DummyUser
from buddies.services import BuddyQueryService
from feusers.models import FeUser
keeper = FeUser.objects.get(email='{keeper}')
real = FeUser.objects.get(email='{real}')
ghost = DummyUser.objects.get(owning_feuser=keeper, display_name='{ghost_name}')
found = BuddyQueryService.offline_record_overlaps(keeper, [real]).get(ghost.pk, {{}}).get(real.pk, [])
print(json.dumps([[t, str(v)] for t, v in found]))
"""))


def _dialog_text(driver):
    return driver.find_element(By.ID, "cdialog-backdrop").text


class TestContactRemovalHistory:

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, "Anna", "Remover")
        b = setup_user(None, None, "Bert", "Removed")
        c = setup_user(None, None, "Cleo", "Bystander")
        _create_contact_link(a["email"], b["email"])
        _create_contact_link(a["email"], c["email"])
        _setup(a["email"], b["email"], c["email"])
        emails = [a["email"], b["email"], c["email"]]
        connected = {a["email"]: [b["email"], c["email"]], b["email"]: [a["email"]], c["email"]: [a["email"]]}
        before = _snapshot(emails, connected)
        _shell(
            f"from buddies.services import contact_actions; from buddies.models import ContactLink; "
            f"from feusers.models import FeUser; "
            f"a = FeUser.objects.get(email='{a['email']}'); b = FeUser.objects.get(email='{b['email']}'); "
            f"contact_actions.remove_contact(a, ContactLink.between(a, b))"
        )
        after = _snapshot(emails, {a["email"]: [c["email"]], c["email"]: [a["email"]]})
        refs_after_removal = {o["email"]: _references(o["email"], x["email"]) for o, x in ((a, b), (b, a))}
        records_after_removal = _records(emails, [])
        _create_contact_link(a["email"], b["email"])
        overlaps = {"a": _overlaps(a["email"], b["email"], "Bert Removed"),
                    "b": _overlaps(b["email"], a["email"], "Anna Remover")}
        ghost_uid = _shell(
            f"from buddies.models import DummyUser; "
            f"print(DummyUser.objects.get(owning_feuser__email='{a['email']}', display_name='Bert Removed').uid)"
        )
        yield {"a": a, "b": b, "c": c, "before": before, "after": after, "overlaps": overlaps,
               "refs_after_removal": refs_after_removal, "records_after_removal": records_after_removal,
               "ghost_uid": ghost_uid}
        for u in (a, b, c):
            cleanup_user(u["email"])

    def test_each_side_keeps_its_amounts_without_pending_foreign_entries(self, ctx):
        a, b = ctx["a"]["email"], ctx["b"]["email"]
        assert ctx["after"][a]["amounts"] == [r for r in ctx["before"][a]["amounts"] if r[0] != "CR Pending Fuel"]
        assert ctx["after"][b]["amounts"] == ctx["before"][b]["amounts"]

    def test_balances_stay_with_the_offline_contacts(self, ctx):
        for email in (ctx["a"]["email"], ctx["b"]["email"]):
            assert ctx["after"][email]["balances"] == ctx["before"][email]["balances"], email

    def test_third_participant_sees_no_change(self, ctx):
        assert ctx["after"][ctx["c"]["email"]] == ctx["before"][ctx["c"]["email"]]

    def test_no_reference_to_the_other_side_left(self, ctx):
        for owner, refs in ctx["refs_after_removal"].items():
            assert refs == {k: 0 for k in refs}, owner

    def test_copy_holds_only_own_share_and_own_classification(self, ctx):
        copies = [e for e in ctx["records_after_removal"]["expenses"] if e[0] == "CR Cinema" and e[1] == "Anna"]
        assert len(copies) == 1
        title, owner, payer, value, note, approved, settled, settlement, cat, tags, rows, overlays = copies[0]
        assert payer == "offline:Bert Removed"
        assert (cat, tags, overlays) == ("Anna Fun", ["Anna Night"], [])
        assert [r[:2] for r in rows] == [["Anna", "25.000"]]

    def test_overlapping_records_are_found_on_both_sides(self, ctx):
        assert ctx["overlaps"] == {"a": OVERLAPS, "b": OVERLAPS}

    def test_merge_request_dialog_lists_overlaps(self, driver, w, ctx):
        _login_as(driver, ctx["a"])
        driver.get(_url("/buddies/contacts/"))
        time.sleep(1)
        uid, b_pk = ctx["ghost_uid"], _shell(
            f"from feusers.models import FeUser; print(FeUser.objects.get(email='{ctx['b']['email']}').pk)")
        driver.execute_script(
            "var f = document.getElementById(arguments[0]); f.style.display = 'flex';"
            "f.querySelector('select').value = arguments[1];"
            "f.querySelector('button[type=submit]').click();",
            f"merge-form-{uid}", f"f{b_pk}",
        )
        time.sleep(1)
        text = _dialog_text(driver)
        assert "same title and amount" in text
        assert "CR Dinner, €100.00" in text
        driver.find_element(By.ID, "cdialog-cancel").click()
        time.sleep(1)

    def test_accept_dialog_lists_overlaps_and_copies_them(self, driver, w, ctx):
        token = _shell(
            f"from buddies.models import DummyUser; from feusers.models import FeUser; "
            f"from buddies.services import BuddyLifecycleService; "
            f"a = FeUser.objects.get(email='{ctx['a']['email']}'); b = FeUser.objects.get(email='{ctx['b']['email']}'); "
            f"outcome, invite = BuddyLifecycleService.request_merge_with_feuser("
            f"a, DummyUser.objects.get(uid={ctx['ghost_uid']}), b); print(invite.token)"
        )
        _login_as(driver, ctx["b"])
        driver.get(_url(f"/buddies/merge/{token}/"))
        time.sleep(1)
        driver.execute_script(
            "window.__copied = null;"
            "Object.defineProperty(navigator, 'clipboard', {value: {writeText: function (t) {"
            "window.__copied = t; return Promise.resolve(); }}});"
        )
        driver.find_element(By.ID, "btn-accept-merge").click()
        time.sleep(1)
        assert "same title and amount" in _dialog_text(driver)
        driver.find_element(By.CSS_SELECTOR, "#cdialog-detail .merge-overlap-copy").click()
        time.sleep(1)
        assert driver.execute_script("return window.__copied;") == OVERLAP_LINES
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(2)
        kept = _shell(
            f"from budget.models import Expense; "
            f"print(Expense.objects.filter(owning_feuser__email='{ctx['b']['email']}', title='CR Cinema').count())"
        )
        assert kept == "2", "Merging keeps both copies"
