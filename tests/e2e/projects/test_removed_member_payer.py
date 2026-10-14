"""
Kicking a real member replaces them completely with an offline member: every
project expense stays, with the same payer, shares, amounts and debts, and no
project data references the kicked feuser afterwards. After rejoining, merging
the offline member back restores the original state, apart from the kicked
member's own categories, tags and overlays, which leave with them.
"""
import json
import time

import pytest

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _login_as, _create_group, _add_group_member, _get_pk

TITLES = ["Kick Paid Rent", "Kick Admin Dinner", "Kick Recorded Taxi", "Kick Pending Fuel", "Kick Solo Lunch"]


def _setup_expenses(gid, admin, kicked, other):
    """Paid by the kicked member, paid by the admin with the kicked member as
    participant, recorded by the kicked member with an offline payer, a pending
    one and one fully their own paid by the kicked member; plus overlays and initiated_by."""
    _shell(f"""
from decimal import Decimal as D
from budget.models import Expense, ExpenseDataOverlay, Category
from buddies.models import Project, ProjectMember, DummyUser, BuddySpending, ProjectInvite
from feusers.models import FeUser
g = Project.objects.get(pk={gid})
a = FeUser.objects.get(email='{admin}')
k = FeUser.objects.get(email='{kicked}')
c = FeUser.objects.get(email='{other}')
d = DummyUser.objects.create(owning_group=g, display_name='Otto Offline')
ProjectMember.objects.create(group=g, dummy=d)

def exp(owner, title, value, rows, **kw):
    e = Expense.objects.create(owning_feuser=owner, title=title, type='expense', value=D(value),
                               settled=False, project=g, initiated_by_feuser=k, **kw)
    for who, pct in rows:
        key = 'participant_dummy' if isinstance(who, DummyUser) else 'participant_feuser'
        BuddySpending.objects.create(expense=e, share_percent=D(pct), **{{key: who}})
    return e

rent = exp(k, '{TITLES[0]}', '300', [(a, '30'), (c, '30')],
           category=Category.objects.filter(owning_feuser=k).first())
dinner = exp(a, '{TITLES[1]}', '90', [(k, '50'), (c, '25')])
exp(k, '{TITLES[2]}', '40', [(k, '40'), (c, '30')], is_dummy=True, upfront_payee_dummy=d)
exp(k, '{TITLES[3]}', '60', [(a, '50')], buddy_approved=False)
exp(k, '{TITLES[4]}', '50', [])
ExpenseDataOverlay.objects.create(expense=dinner, feuser=k, note='kicked note')
ExpenseDataOverlay.objects.create(expense=rent, feuser=a,
                                  category=Category.objects.filter(owning_feuser=a).first())
ProjectInvite.objects.create(group=g, inviting_feuser=k, invitee_email='kick.invitee@example.com')
""")


def _snapshot(gid, emails):
    """Breakdown, balances, debts and personal shared amounts per member, with
    the kicked member's name normalised so real and offline compare equal."""
    return json.loads(_shell(f"""
import json
from feusers.models import FeUser
from buddies.models import Project
from buddies.services import BuddyQueryService
from budget.views._sharing import build_shared_qs
g = Project.objects.get(pk={gid})
n = lambda name: name.replace(' (offline member)', '')
out = {{}}
for email in {emails!r}:
    u = FeUser.objects.get(email=email)
    b = BuddyQueryService.get_group_full_breakdown(u, g)
    out[email] = {{
        'expenses': sorted(
            [e['expense'].title, n(e['payer_name']), f"{{e['payer_amount']:.2f}}", e['expense'].buddy_approved,
             sorted([n(p['name']), f"{{p['amount']:.2f}}"] for p in e['participant_shares'] if p['amount'])]
            for e in b['expenses']),
        'balances': sorted([n(x['name']), str(x['net'])] for x in b['balances']),
        'debts': sorted([n(x['from_name']), n(x['to_name']), str(x['amount'])] for x in b['simplified']),
        'my_amounts': sorted([q.title, str(q.effective_value)]
                             for q in build_shared_qs(u, None, None).filter(project=g) if q.effective_value),
    }}
print(json.dumps(out))
"""))


def _records(gid, kicked):
    """Every project expense with owner (only where a member paid), payer, shares (without
    0% rows: the admin's owner row stays after a merge back), notes and the classification
    of everyone but the kicked member, plus the project roster."""
    return json.loads(_shell(f"""
import json
from budget.models import Expense
from buddies.models import ProjectMember
def who(bs):
    return bs.participant_feuser.first_name if bs.participant_feuser else 'offline:' + bs.participant_dummy.display_name
expenses = []
for e in Expense.objects.filter(project_id={gid}).order_by('title'):
    kicked_owns = e.owning_feuser.email == '{kicked}'
    expenses.append([
        e.title, None if e.is_dummy else e.owning_feuser.first_name,
        'offline:' + e.upfront_payee_dummy.display_name if e.is_dummy else e.owning_feuser.first_name,
        str(e.value), e.note, e.buddy_approved, e.settled,
        None if kicked_owns or not e.category else e.category.title,
        [] if kicked_owns else sorted(t.title for t in e.tags.all()),
        sorted([who(bs), str(bs.share_percent), bs.approval_state] for bs in e.buddy_spendings.all()
               if bs.share_percent),
        sorted([o.feuser.first_name, o.category.title if o.category else None,
                sorted(t.title for t in o.tags.all()), o.note]
               for o in e.data_overlays.exclude(feuser__email='{kicked}')),
    ])
print(json.dumps({{
    'expenses': expenses,
    'roster': sorted(m.feuser.first_name if m.feuser else 'offline:' + m.dummy.display_name
                     for m in ProjectMember.objects.filter(group_id={gid})),
}}))
"""))


def _kicked_references(gid, kicked):
    return json.loads(_shell(f"""
import json
from budget.models import Expense, ExpenseDataOverlay
from buddies.models import Project, ProjectMember, BuddySpending, ProjectInvite, DummyMergeInvite
from feusers.models import FeUser
from django.db.models import Q
g = Project.objects.get(pk={gid})
k = FeUser.objects.get(email='{kicked}')
print(json.dumps({{
    'members': ProjectMember.objects.filter(group=g, feuser=k).count(),
    'owned': Expense.objects.filter(project=g, owning_feuser=k).count(),
    'initiated': Expense.objects.filter(project=g, initiated_by_feuser=k).count(),
    'scheduled_source': Expense.objects.filter(project=g, source_scheduled__owning_feuser=k).count(),
    'categories': Expense.objects.filter(project=g, category__owning_feuser=k).count(),
    'tags': Expense.objects.filter(project=g, tags__owning_feuser=k).count(),
    'spendings': BuddySpending.objects.filter(expense__project=g, participant_feuser=k).count(),
    'overlays': ExpenseDataOverlay.objects.filter(expense__project=g, feuser=k).count(),
    'invites': ProjectInvite.objects.filter(group=g, inviting_feuser=k).count(),
    'merge_invites': DummyMergeInvite.objects.filter(dummy__owning_group=g).filter(
        Q(inviting_feuser=k) | Q(invited_feuser=k)).count(),
}}))
"""))


class TestKickRealMember:

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        admin = setup_user(driver, w, first_name="Sabine", last_name="Kickadmin")
        kicked = setup_user(driver, w, first_name="Gernot", last_name="Kicked")
        other = setup_user(driver, w, first_name="Leon", last_name="Stays")
        gid = int(_create_group(admin["email"], "Kick Member Project"))
        _add_group_member(gid, kicked["email"])
        _add_group_member(gid, other["email"])
        _setup_expenses(gid, admin["email"], kicked["email"], other["email"])
        emails = [admin["email"], other["email"]]
        before = _snapshot(gid, emails)
        before_all = _snapshot(gid, emails + [kicked["email"]])
        records_before = _records(gid, kicked["email"])
        assert _kicked_references(gid, kicked["email"])["owned"] == 4
        _shell(
            f"from buddies.models import Project, ProjectMember; from feusers.models import FeUser; "
            f"from buddies.services import project_actions; "
            f"g = Project.objects.get(pk={gid}); "
            f"project_actions.remove_member(g, FeUser.objects.get(email='{admin['email']}'), "
            f"ProjectMember.objects.get(group=g, feuser__email='{kicked['email']}'))"
        )
        after = _snapshot(gid, emails)
        refs_after_kick = _kicked_references(gid, kicked["email"])
        solo_after_kick = _shell(
            f"from budget.models import Expense; "
            f"e = Expense.objects.get(project_id={gid}, title='{TITLES[4]}'); "
            f"print(e.owning_feuser.first_name, e.upfront_payee_dummy.display_name, "
            f"[(bs.participant_feuser.first_name, str(bs.share_percent)) for bs in e.buddy_spendings.all()])"
        )
        ghost_members = _shell(
            f"from buddies.models import ProjectMember; "
            f"print(ProjectMember.objects.filter(group_id={gid}, dummy__display_name='Gernot Kicked').count())"
        )
        _login_as(driver, admin)
        driver.get(_url(f"/projects/{gid}/"))
        time.sleep(1)
        visible_after_kick = [t for t in TITLES if t in driver.page_source]
        _add_group_member(gid, kicked["email"])
        merged = _shell(
            f"from buddies.models import Project, DummyUser; from feusers.models import FeUser; "
            f"from buddies.services import BuddyGroupService, BuddyLifecycleService; "
            f"g = Project.objects.get(pk={gid}); "
            f"a = FeUser.objects.get(email='{admin['email']}'); k = FeUser.objects.get(email='{kicked['email']}'); "
            f"ghost = DummyUser.objects.get(owning_group=g, display_name='Gernot Kicked'); "
            f"outcome, invite = BuddyGroupService.request_group_merge_with_feuser(a, g, ghost, k); "
            f"print(outcome, BuddyLifecycleService.accept_merge(invite.token, k))"
        )
        yield {"admin": admin, "kicked": kicked, "gid": gid, "before": before, "after": after,
               "merged": merged, "before_all": before_all, "refs_after_kick": refs_after_kick,
               "solo_after_kick": solo_after_kick,
               "ghost_members": ghost_members, "visible_after_kick": visible_after_kick, "records_before": records_before,
               "restored": _snapshot(gid, emails + [kicked["email"]]),
               "records_restored": _records(gid, kicked["email"])}
        for u in (kicked, other, admin):
            cleanup_user(u["email"])

    def test_no_expense_disappears(self, ctx):
        for email, snap in ctx["after"].items():
            titles = [e[0] for e in snap["expenses"]]
            assert sorted(titles) == sorted(TITLES), email

    def test_payers_shares_and_amounts_unchanged(self, ctx):
        for email in ctx["before"]:
            assert ctx["after"][email]["expenses"] == ctx["before"][email]["expenses"], email

    def test_members_personal_amounts_unchanged(self, ctx):
        for email in ctx["before"]:
            assert ctx["after"][email]["my_amounts"] == ctx["before"][email]["my_amounts"], email

    def test_balances_and_debts_unchanged(self, ctx):
        for email in ctx["before"]:
            assert ctx["after"][email]["balances"] == ctx["before"][email]["balances"], email
            assert ctx["after"][email]["debts"] == ctx["before"][email]["debts"], email

    def test_admin_owns_paid_expense_with_zero_share(self, ctx):
        assert ctx["solo_after_kick"] == "Sabine Gernot Kicked [('Sabine', '0.000')]"

    def test_kicked_member_is_an_offline_member(self, ctx):
        names = [b[0] for b in ctx["after"][ctx["admin"]["email"]]["balances"]]
        assert "Gernot Kicked" in names
        assert ctx["ghost_members"] == "1"

    def test_no_reference_to_kicked_feuser_left(self, ctx):
        refs = ctx["refs_after_kick"]
        assert refs == {k: 0 for k in refs}

    def test_merging_back_restores_the_original_state(self, ctx):
        assert ctx["merged"] == "invite True"
        assert ctx["records_restored"] == ctx["records_before"]

    def test_merging_back_restores_amounts_balances_and_debts(self, ctx):
        assert ctx["restored"] == ctx["before_all"]

    def test_admin_sees_every_expense(self, ctx):
        assert ctx["visible_after_kick"] == TITLES
