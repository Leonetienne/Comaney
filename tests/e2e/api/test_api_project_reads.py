"""
projects_overview returns the whole project as the project pages show it, and
settlements_list reads back recorded settlements with their status.
Run with: pytest -v tests/e2e/api/test_api_project_reads.py | tee logfile.log
"""
import pytest

from bhelpers import _add_group_member, _create_group, _get_pk, _shell
from helpers import api, api_post, cleanup_user, setup_user


@pytest.fixture
def project():
    """Bea paid 100: Admin's share 20%, offline member Gernot's 50%, Bea keeps 30%."""
    admin = setup_user(None, None, "Admin", "Overview")
    bea = setup_user(None, None, "Bea", "Overview")
    gid = int(_create_group(admin["email"], "Overview Project"))
    _add_group_member(gid, bea["email"])
    gernot = int(_shell(f"""
from decimal import Decimal as D
from budget.models import Expense
from buddies.models import BuddySpending, DummyUser, ProjectMember
from feusers.models import FeUser
d = DummyUser.objects.create(owning_group_id={gid}, display_name='Gernot')
ProjectMember.objects.create(group_id={gid}, dummy=d)
e = Expense.objects.create(owning_feuser=FeUser.objects.get(email='{bea["email"]}'), title='Hut',
    type='expense', value=D('100'), settled=False, project_id={gid})
BuddySpending.objects.create(expense=e, share_percent=D('20'), participant_feuser=FeUser.objects.get(email='{admin["email"]}'))
BuddySpending.objects.create(expense=e, share_percent=D('50'), participant_dummy=d)
print(d.pk)
"""))
    yield {"gid": gid, "admin": admin, "bea": bea, "bea_id": int(_get_pk(bea["email"])),
           "admin_id": int(_get_pk(admin["email"])), "gernot_id": gernot}
    cleanup_user(admin["email"])
    cleanup_user(bea["email"])


def _pairs(rows):
    return sorted((r["from"]["name"], r["to"]["name"], r["amount"]) for r in rows)


def test_overview_has_every_member_share_and_balance(project):
    resp = api("GET", f"/api/v2/projects/{project['gid']}/overview/", project["admin"])
    assert resp.status_code == 200, resp.text
    data = resp.json()

    balances = {m["name"]: m["balance"] for m in data["members"]}
    assert balances == {"Admin Overview": "-20.00", "Bea Overview": "70.00", "Gernot": "-50.00"}

    [expense] = data["expenses"]
    assert expense["payer"]["name"] == "Bea Overview"
    assert expense["payer_share"] == {"amount": "30.00", "percent": 30.0}
    assert sorted((s["person"]["name"], s["amount"]) for s in expense["shares"]) == [
        ("Admin Overview", "20.00"), ("Gernot", "50.00"),
    ]
    assert data["total_spending"] == "100.00"
    assert _pairs(data["settle_up"]) == [("Admin Overview", "Bea Overview", "20.00"), ("Gernot", "Bea Overview", "50.00")]
    assert _pairs(data["expense_flows"]) == _pairs(data["settle_up"])


def test_settlements_list_shows_pending_then_confirmed(project):
    resp = api_post("/api/v2/settlements/", project["admin"], {
        "project_id": project["gid"], "creditor": {"type": "feuser", "id": project["bea_id"]}, "amount": "20",
    })
    assert resp.status_code == 201, resp.text

    resp = api("GET", "/api/v2/settlements/", project["admin"], params={"project_id": project["gid"]})
    assert resp.status_code == 200, resp.text
    [settlement] = resp.json()["settlements"]
    assert settlement["status"] == "pending"
    assert (settlement["payer"]["id"], settlement["recipient"]["id"], settlement["amount"]) == (
        project["admin_id"], project["bea_id"], "20.00",
    )

    resp = api_post("/api/v2/pending/decide/", project["bea"], {"kind": "settlement", "expense_id": settlement["id"], "approve": True})
    assert resp.status_code == 200, resp.text

    confirmed = api("GET", "/api/v2/settlements/", project["bea"], params={
        "status": "confirmed", "person_type": "feuser", "person_id": project["admin_id"],
    }).json()["settlements"]
    assert [s["id"] for s in confirmed] == [settlement["id"]]
    from_gernot = api("GET", "/api/v2/settlements/", project["bea"], params={
        "person_type": "offline", "person_id": project["gernot_id"],
    }).json()["settlements"]
    assert from_gernot == []

    overview = api("GET", f"/api/v2/projects/{project['gid']}/overview/", project["admin"]).json()
    assert _pairs(overview["settle_up"]) == [("Gernot", "Bea Overview", "50.00")]
