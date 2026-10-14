"""
Removing a real contact deletes pending project, partnership and offline
contact merge invitations between the two feusers; others stay.
"""
import json

import pytest

from helpers import setup_user, cleanup_user
from bhelpers import _shell, _create_contact_link, _create_group


class TestKickExpiresInvites:

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Kicker", last_name="Invites")
        b = setup_user(driver, w, first_name="Kicked", last_name="Invites")
        c = setup_user(driver, w, first_name="Bystander", last_name="Invites")
        _create_contact_link(a["email"], b["email"])
        _create_contact_link(a["email"], c["email"])
        a_project = _create_group(a["email"], "Kick Invite Project A")
        b_project = _create_group(b["email"], "Kick Invite Project B")
        _shell(f"""
from buddies.models import Project, ProjectInvite, CatalogPartnership, CatalogPartnershipInvite, DummyUser, DummyMergeInvite
from feusers.models import FeUser
a = FeUser.objects.get(email='{a['email']}')
b = FeUser.objects.get(email='{b['email']}')
ProjectInvite.objects.create(group=Project.objects.get(pk={a_project}), inviting_feuser=a, invitee_email='{b['email']}')
ProjectInvite.objects.create(group=Project.objects.get(pk={b_project}), inviting_feuser=b, invitee_email='{a['email']}')
ProjectInvite.objects.create(group=Project.objects.get(pk={a_project}), inviting_feuser=a, invitee_email='{c['email']}')
CatalogPartnershipInvite.objects.create(partnership=CatalogPartnership.objects.create(), inviter=a, invitee_email='{b['email']}')
DummyMergeInvite.objects.create(inviting_feuser=a, invited_feuser=b,
    dummy=DummyUser.objects.create(owning_feuser=a, display_name='Kick Merge Dummy'))
""")
        _shell(
            f"from buddies.services import contact_actions; from buddies.models import ContactLink; "
            f"from feusers.models import FeUser; "
            f"a = FeUser.objects.get(email='{a['email']}'); b = FeUser.objects.get(email='{b['email']}'); "
            f"contact_actions.remove_contact(a, ContactLink.between(a, b))"
        )
        yield {"a": a, "b": b, "c": c}
        for u in (a, b, c):
            cleanup_user(u["email"])

    def _counts(self, ctx):
        return json.loads(_shell(f"""
import json
from buddies.models import ProjectInvite, CatalogPartnershipInvite, DummyMergeInvite
a, b, c = '{ctx['a']['email']}', '{ctx['b']['email']}', '{ctx['c']['email']}'
print(json.dumps({{
    'project_a_to_b': ProjectInvite.objects.filter(inviting_feuser__email=a, invitee_email=b).count(),
    'project_b_to_a': ProjectInvite.objects.filter(inviting_feuser__email=b, invitee_email=a).count(),
    'project_a_to_c': ProjectInvite.objects.filter(inviting_feuser__email=a, invitee_email=c).count(),
    'partnership': CatalogPartnershipInvite.objects.filter(inviter__email=a, invitee_email=b).count(),
    'merge': DummyMergeInvite.objects.filter(inviting_feuser__email=a, invited_feuser__email=b).count(),
}}))
"""))

    def test_invites_between_them_are_gone(self, ctx):
        counts = self._counts(ctx)
        for key in ("project_a_to_b", "project_b_to_a", "partnership", "merge"):
            assert counts[key] == 0, key

    def test_invite_to_someone_else_stays(self, ctx):
        assert self._counts(ctx)["project_a_to_c"] == 1
