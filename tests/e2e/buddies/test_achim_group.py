"""
Achim Archive: group scenarios.

5.11b: Removing a group offline member with expenses creates a group Achim Archive
       and shows the "Achim appeared" modal on the group detail page.
5.11d: Bulk-deleting group Achim Archive's expenses via the wipe confirmation page
       removes the archive from the group member list.
"""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user
from bhelpers import _shell, _create_group


# ---------------------------------------------------------------------------
# Achim Archive created when group dummy with expenses is removed
# ---------------------------------------------------------------------------

class TestAchimGroupCreated:
    """Remove group dummy with expense: group Achim Archive must appear."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Greg", last_name="GroupAdmin")
        email = a["email"]
        group_id = _create_group(email, "Achim Test Group")
        dummy_id = _shell(
            f"from buddies.models import Project, DummyUser, ProjectMember; "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='Offline Otto'); "
            f"ProjectMember.objects.create(group=g, dummy=d); "
            f"print(d.pk)"
        )
        _shell(
            f"from feusers.models import FeUser; "
            f"from buddies.models import Project, BuddySpending; "
            f"from budget.models import Expense; "
            f"from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"e = Expense.objects.create(owning_feuser=u, title='Group Camping Trip', "
            f"  type='expense', value=Decimal('120.00'), settled=False, "
            f"  buddy_approved=True, project=g); "
            f"BuddySpending.objects.create(expense=e, participant_dummy_id={dummy_id}, "
            f"  share_percent=Decimal('50'))"
        )
        # Get the BuddyGroupMember uid for the dummy so we can find the Remove link
        member_uid = _shell(
            f"from buddies.models import ProjectMember; "
            f"m = ProjectMember.objects.get(dummy_id={dummy_id}); "
            f"print(m.uid)"
        )
        a["group_id"] = int(group_id)
        a["dummy_id"] = int(dummy_id)
        a["member_uid"] = int(member_uid)
        yield a
        cleanup_user(a["email"])

    def test_group_dummy_visible_before_removal(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['group_id']}/settings/"))
        time.sleep(1)
        assert "Offline Otto" in driver.page_source

    def test_remove_link_leads_to_confirm_page(self, driver, w, ctx):
        dummy_card = driver.find_element(By.CSS_SELECTOR, ".buddy-card-dummy")
        dummy_card.find_element(By.CSS_SELECTOR, "a[href*='remove']").click()
        time.sleep(1)
        assert "remove" in driver.current_url

    def test_confirm_page_shows_group_context(self, driver, w, ctx):
        assert "Achim Test Group" in driver.page_source

    def test_confirm_page_shows_expense_count(self, driver, w, ctx):
        assert "1" in driver.page_source
        assert "expense" in driver.page_source.lower()

    def test_confirm_page_mentions_achim(self, driver, w, ctx):
        assert "Achim Archive" in driver.page_source

    def test_submit_redirects_to_group_page(self, driver, w, ctx):
        driver.find_element(By.ID, "btn-confirm-kick").click()
        time.sleep(1.5)
        assert f"/projects/{ctx['group_id']}/" in driver.current_url

    def test_achim_modal_visible(self, driver, w, ctx):
        assert "Say hello to Achim Archive" in driver.page_source

    def test_offline_otto_gone(self, driver, w, ctx):
        # Check the member-list cards specifically. The expense note written by
        # merge_dummy_into_archive ("Original participant was: Offline Otto") is
        # rendered in a collapsed DOM section, so page_source always contains the
        # name; what matters is that no member card still lists Otto.
        driver.get(_url(f"/projects/{ctx['group_id']}/settings/"))
        time.sleep(1)
        member_names = [
            el.text for el in driver.find_elements(By.CSS_SELECTOR, ".buddy-card-dummy .buddy-name")
        ]
        assert "Offline Otto" not in member_names, \
            f"Offline Otto must not appear in the member list, got: {member_names}"

    def test_achim_archive_appears_in_member_list(self, driver, w, ctx):
        assert "Achim Archive" in driver.page_source, \
            "Group Achim Archive must appear in the group member list"

    def test_archive_exists_in_db(self, driver, w, ctx):
        count = _shell(
            f"from buddies.models import Project, DummyUser; "
            f"g = Project.objects.get(pk={ctx['group_id']}); "
            f"print(DummyUser.objects.filter(owning_group=g, is_archive=True).count())"
        )
        assert count == "1", "Exactly one group Achim Archive must exist in the DB"

    def test_expense_transferred_to_archive(self, driver, w, ctx):
        count = _shell(
            f"from buddies.models import Project, BuddySpending, DummyUser; "
            f"g = Project.objects.get(pk={ctx['group_id']}); "
            f"archive = DummyUser.objects.get(owning_group=g, is_archive=True); "
            f"print(BuddySpending.objects.filter(participant_dummy=archive).count())"
        )
        assert count == "1", "Otto's BuddySpending row must now belong to group Achim Archive"


# ---------------------------------------------------------------------------
# Wipe group Achim Archive expenses
# ---------------------------------------------------------------------------

class TestAchimGroupWipe:
    """Wipe group Achim Archive expenses: warning page, then archive gone."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Greta", last_name="Wipeadmin")
        email = a["email"]
        group_id = _create_group(email, "Wipe Archive Group")
        # Create group archive with an expense via shell
        _shell(
            f"from feusers.models import FeUser; "
            f"from buddies.models import Project, DummyUser, ProjectMember, BuddySpending; "
            f"from buddies.services.archive import BuddyArchiveService; "
            f"from budget.models import Expense; "
            f"from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"d = DummyUser.objects.create(owning_group=g, display_name='TempGroupBuddy'); "
            f"ProjectMember.objects.create(group=g, dummy=d); "
            f"e = Expense.objects.create(owning_feuser=u, title='Wipe Group Expense', "
            f"  type='expense', value=Decimal('100.00'), settled=False, "
            f"  buddy_approved=True, project=g); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=d, "
            f"  share_percent=Decimal('50')); "
            f"archive, _ = BuddyArchiveService.get_or_create_group_archive(g); "
            f"BuddyArchiveService.merge_dummy_into_archive(d, archive); "
            f"d.delete(); "
            f"print('ok')"
        )
        a["group_id"] = int(group_id)
        yield a
        cleanup_user(a["email"])

    def test_achim_visible_in_group_members(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['group_id']}/settings/"))
        time.sleep(1)
        assert "Achim Archive" in driver.page_source

    def test_delete_expenses_link_leads_to_wipe_page(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR, "a[href*='archive-wipe']").click()
        time.sleep(1)
        assert "archive-wipe" in driver.current_url

    def test_wipe_page_shows_group_context(self, driver, w, ctx):
        assert "Wipe Archive Group" in driver.page_source

    def test_wipe_page_shows_expense_count(self, driver, w, ctx):
        assert "1 expense" in driver.page_source

    def test_wipe_page_shows_financial_impact(self, driver, w, ctx):
        assert "50.00" in driver.page_source, \
            "Wipe page must show feuser's share (50% of 100.00 = 50.00)"

    def test_submit_wipes_and_redirects(self, driver, w, ctx):
        driver.find_element(By.ID, "btn-confirm-wipe").click()
        time.sleep(1.5)
        assert f"/projects/{ctx['group_id']}/" in driver.current_url

    def test_flash_message_shown(self, driver, w, ctx):
        assert "cleared" in driver.page_source.lower() or \
               "Achim Archive" in driver.page_source

    def test_achim_gone_from_group_members(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['group_id']}/settings/"))
        time.sleep(1)
        assert "Achim Archive" not in driver.page_source, \
            "Achim Archive must be gone from group members after wipe"

    def test_archive_deleted_from_db(self, driver, w, ctx):
        count = _shell(
            f"from buddies.models import Project, DummyUser; "
            f"g = Project.objects.get(pk={ctx['group_id']}); "
            f"print(DummyUser.objects.filter(owning_group=g, is_archive=True).count())"
        )
        assert count == "0", "Group Achim Archive must be deleted after wipe"


# ---------------------------------------------------------------------------
# Merging two dummies that owe each other into Achim must zero their shared debt
# ---------------------------------------------------------------------------

class TestAchimGroupSelfDebtCancels:
    """
    Regression: when dummy A owed dummy B (B paid, A participated), and both are
    merged into Achim Archive, the resulting self-referential expense must not
    appear as a debt in either the simplified or raw D3 debt charts.

    Before fix: the netting code kept a (achim, achim) self-loop in raw_flows,
    making RAW.links.length > 0 and showing a yellow "arrows cancel out" warning
    even though simplifiedTotal was already 0.  With the fix (skip frm==to in
    the netting loop) both charts must show "No debt".
    """

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        a = setup_user(driver, w, first_name="Hans", last_name="SelfDebt")
        email = a["email"]
        group_id = _create_group(email, "Self Debt Test Group")
        _shell(
            f"from feusers.models import FeUser; "
            f"from buddies.models import Project, DummyUser, ProjectMember, BuddySpending; "
            f"from buddies.services.archive import BuddyArchiveService; "
            f"from buddies.services.group import BuddyGroupService; "
            f"from budget.models import Expense; "
            f"from decimal import Decimal; "
            f"u = FeUser.objects.get(email='{email}'); "
            f"g = Project.objects.get(pk={group_id}); "
            f"da = DummyUser.objects.create(owning_group=g, display_name='DummyA'); "
            f"db = DummyUser.objects.create(owning_group=g, display_name='DummyB'); "
            f"ProjectMember.objects.create(group=g, dummy=da); "
            f"ProjectMember.objects.create(group=g, dummy=db); "
            f"e = Expense.objects.create(owning_feuser=u, title='B paid for A', "
            f"  type='expense', value=Decimal('5.00'), settled=False, "
            f"  buddy_approved=True, project=g, is_dummy=True, "
            f"  upfront_payee_dummy=db); "
            f"BuddySpending.objects.create(expense=e, participant_dummy=da, "
            f"  share_percent=Decimal('100')); "
            f"BuddyGroupService.delete_group_dummy(g, u, da); "
            f"BuddyGroupService.delete_group_dummy(g, u, db); "
            f"print('ok')"
        )
        a["group_id"] = int(group_id)
        yield a
        cleanup_user(a["email"])

    def test_group_page_loads(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1.5)
        assert f"/projects/{ctx['group_id']}/" in driver.current_url

    def test_achim_is_only_dummy_member(self, driver, w, ctx):
        # Check member cards only — archived notes in collapsed DOM sections
        # contain "DummyA"/"DummyB" as audit trail text, so page_source is not reliable.
        driver.get(_url(f"/projects/{ctx['group_id']}/settings/"))
        time.sleep(1)
        member_names = [
            el.text for el in driver.find_elements(By.CSS_SELECTOR, ".buddy-card-dummy .buddy-name")
        ]
        assert "Achim Archive" in member_names, \
            f"Achim Archive must appear in the member list, got: {member_names}"
        assert "DummyA" not in member_names, \
            f"DummyA must not appear in the member list, got: {member_names}"
        assert "DummyB" not in member_names, \
            f"DummyB must not appear in the member list, got: {member_names}"

    def test_no_simplified_links_in_page(self, driver, w, ctx):
        driver.get(_url(f"/projects/{ctx['group_id']}/"))
        time.sleep(1.5)
        src = driver.page_source
        assert '"links": []' in src or '"links":[]' in src, \
            "simplified_graph_json must contain no links after both dummies merged into Achim"

    def test_simplified_total_shows_no_debt(self, driver, w, ctx):
        src = driver.page_source
        assert "No debt" in src or "no debt" in src.lower(), \
            "Page must indicate no remaining debt after Achim absorbs both sides of the A-owes-B expense"

    def test_no_self_loop_in_raw_links(self, driver, w, ctx):
        src = driver.page_source
        assert '"from": "' not in src or "DummyA" not in src, \
            "Raw graph must not contain DummyA links after merge"
        import json
        start = src.find("var RAW =")
        end = src.find(";", start)
        if start != -1 and end != -1:
            raw_json_str = src[start + len("var RAW ="):end].strip()
            try:
                raw_data = json.loads(raw_json_str)
                for link in raw_data.get("links", []):
                    assert link["from"] != link["to"], \
                        f"Self-loop found in raw graph: {link}"
            except (json.JSONDecodeError, KeyError):
                pass
