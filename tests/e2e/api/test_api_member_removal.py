"""
Removing people through REST and MCP hands their history to an offline member
or the Achim Archive exactly like the web app does.
Run with: pytest -v tests/e2e/api/test_api_member_removal.py | tee logfile.log
"""
import json

import pytest
import requests

from bhelpers import _add_group_member, _create_contact_link, _create_group, _shell
from helpers import BASE_URL, api, api_post, cleanup_user, setup_user


def _expense(owner, gid, rows, title):
    """Shared expense paid by owner; rows are (email or dummy pk, percent)."""
    return int(_shell(f"""
from decimal import Decimal as D
from budget.models import Expense
from buddies.models import BuddySpending
from feusers.models import FeUser
e = Expense.objects.create(owning_feuser=FeUser.objects.get(email='{owner}'), title='{title}',
    type='expense', value=D('100'), settled=False, project_id={gid or 'None'})
for who, pct in {rows!r}:
    key = {{'participant_dummy_id': who}} if isinstance(who, int) else {{'participant_feuser': FeUser.objects.get(email=who)}}
    BuddySpending.objects.create(expense=e, share_percent=D(pct), **key)
print(e.pk)
"""))


def _offline_member(gid, name):
    return json.loads(_shell(
        f"import json; from buddies.models import DummyUser, ProjectMember; "
        f"d = DummyUser.objects.create(owning_group_id={gid}, display_name='{name}'); "
        f"m = ProjectMember.objects.create(group_id={gid}, dummy=d); "
        f"print(json.dumps({{'dummy': d.pk, 'member': m.pk}}))"
    ))


def _member_id(gid, email):
    return int(_shell(
        f"from buddies.models import ProjectMember; "
        f"print(ProjectMember.objects.get(group_id={gid}, feuser__email='{email}').pk)"
    ))


def _state(expense_id, email):
    """Payer, owner and whether anything on the expense still points at email."""
    return json.loads(_shell(f"""
import json
from budget.models import Expense
e = Expense.objects.get(pk={expense_id})
print(json.dumps({{
    'owner': e.owning_feuser.email,
    'payer_dummy': e.upfront_payee_dummy.display_name if e.is_dummy else None,
    'dummies': sorted([bs.participant_dummy.display_name, bs.participant_dummy.is_archive]
                      for bs in e.buddy_spendings.filter(participant_dummy__isnull=False)),
    'references': e.buddy_spendings.filter(participant_feuser__email='{email}').count()
                  + (e.owning_feuser.email == '{email}') + (e.initiated_by_feuser is not None
                  and e.initiated_by_feuser.email == '{email}'),
}}))
"""))


def _mcp_key(email):
    return _shell(
        "from feusers.models import FeUser; from mcp_server.models import AgentKey; "
        f"k, raw = AgentKey.create(FeUser.objects.get(email='{email}'), 'Removal'); print(raw)"
    )


def _mcp_call(key, name, arguments):
    resp = requests.post(
        f"{BASE_URL}/mcp", timeout=20,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json, text/event-stream"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["result"]


@pytest.fixture
def people():
    created = {}

    def make(*names):
        for name in names:
            created[name] = setup_user(None, None, name, "Removal")
        return created

    yield make
    for user in created.values():
        cleanup_user(user["email"])


def _project_with(people, *members):
    users = people("Admin", *members)
    gid = int(_create_group(users["Admin"]["email"], "Removal Project"))
    for name in members:
        _add_group_member(gid, users[name]["email"])
    return users, gid


def _assert_handed_to_offline_member(expense_id, users, name):
    state = _state(expense_id, users[name]["email"])
    assert state["owner"] == users["Admin"]["email"]
    assert state["payer_dummy"] == f"{name} Removal"
    assert state["references"] == 0


def test_rest_kick_member_hands_paid_expense_to_offline_member(people):
    users, gid = _project_with(people, "Kicked")
    eid = _expense(users["Kicked"]["email"], gid, [(users["Admin"]["email"], "50")], "REST kick")
    resp = api("DELETE", f"/api/v2/projects/{gid}/members/{_member_id(gid, users['Kicked']['email'])}/", users["Admin"])
    assert resp.status_code == 200, resp.text
    _assert_handed_to_offline_member(eid, users, "Kicked")


def test_rest_leave_hands_paid_expense_to_offline_member(people):
    users, gid = _project_with(people, "Leaver")
    eid = _expense(users["Leaver"]["email"], gid, [(users["Admin"]["email"], "50")], "REST leave")
    resp = api_post(f"/api/v2/projects/{gid}/leave/", users["Leaver"], {})
    assert resp.status_code == 200, resp.text
    _assert_handed_to_offline_member(eid, users, "Leaver")


def test_mcp_kick_member_hands_paid_expense_to_offline_member(people):
    users, gid = _project_with(people, "Kicked")
    eid = _expense(users["Kicked"]["email"], gid, [(users["Admin"]["email"], "50")], "MCP kick")
    result = _mcp_call(_mcp_key(users["Admin"]["email"]), "projects_remove_member",
                       {"id": gid, "member_id": _member_id(gid, users["Kicked"]["email"])})
    assert not result.get("isError"), result
    _assert_handed_to_offline_member(eid, users, "Kicked")


def test_rest_remove_offline_member_moves_history_to_achim(people):
    users, gid = _project_with(people)
    offline = _offline_member(gid, "Otto Removal")
    eid = _expense(users["Admin"]["email"], gid, [(offline["dummy"], "50")], "REST offline member")
    resp = api("DELETE", f"/api/v2/projects/{gid}/members/{offline['member']}/", users["Admin"])
    assert resp.status_code == 200 and resp.json()["archive_created"] is True, resp.text
    assert [d[1] for d in _state(eid, users["Admin"]["email"])["dummies"]] == [True]


def test_rest_remove_contact_copies_history_to_removed_contact(people):
    users = people("Owner", "Kicked")
    link = int(_create_contact_link(users["Owner"]["email"], users["Kicked"]["email"]))
    eid = _expense(users["Owner"]["email"], None, [(users["Kicked"]["email"], "50")], "REST contact")
    resp = api("DELETE", f"/api/v2/contacts/{link}/", users["Owner"])
    assert resp.status_code in (200, 204), resp.text
    assert _state(eid, users["Kicked"]["email"])["references"] == 0
    copy = _shell(
        f"from budget.models import Expense; "
        f"e = Expense.objects.get(owning_feuser__email='{users['Kicked']['email']}', title='REST contact'); "
        f"print(e.upfront_payee_dummy.display_name)"
    )
    assert copy == "Owner Removal"


def test_rest_remove_offline_contact_moves_history_to_achim(people):
    users = people("Owner")
    dummy = int(_shell(
        f"from buddies.models import DummyUser; from feusers.models import FeUser; "
        f"print(DummyUser.objects.create(owning_feuser=FeUser.objects.get(email='{users['Owner']['email']}'), "
        f"display_name='Olga Removal').pk)"
    ))
    eid = _expense(users["Owner"]["email"], None, [(dummy, "50")], "REST offline contact")
    resp = api("DELETE", f"/api/v2/contacts/offline/{dummy}/", users["Owner"], params={"accept_balance": "true"})
    assert resp.status_code == 200 and resp.json()["archive_created"] is True, resp.text
    assert [d[1] for d in _state(eid, users["Owner"]["email"])["dummies"]] == [True]
