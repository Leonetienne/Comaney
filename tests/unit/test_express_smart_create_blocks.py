"""
Unit tests for the AI smart-create prompt block selection in
budget/express_service.py::_select_smart_create_blocks.

Django is not importable in the local venv, so (as with
test_express_project_participants.py) this mirrors the pure algorithm.
Run with: venv/bin/pytest tests/unit/test_express_smart_create_blocks.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ── Mirror of _select_smart_create_blocks (no Django needed) ───────────────

BASE = "BASE"
PROJECTS = "PROJECTS"
PROJECT_PARTICIPANTS = "PROJECT_PARTICIPANTS"
PROJECT_PAYER = "PROJECT_PAYER"
DIRECT_BUDDY = "DIRECT_BUDDY"


def select_blocks(projects_data, single_buddies):
    blocks = [BASE]
    if projects_data:
        blocks.append(PROJECTS)
        if any(len(p["members"]) > 1 for p in projects_data):
            blocks.append(PROJECT_PARTICIPANTS)
            blocks.append(PROJECT_PAYER)
    if single_buddies:
        blocks.append(DIRECT_BUDDY)
    return blocks


class TestSelectSmartCreateBlocks:

    def test_no_projects_no_buddies_only_base(self):
        assert select_blocks([], []) == [BASE]

    def test_solo_project_no_buddies_skips_participants_and_payer(self):
        projects_data = [{"id": 1, "members": [{"name": "Me"}]}]
        assert select_blocks(projects_data, []) == [BASE, PROJECTS]

    def test_multi_member_project_unlocks_participants_and_payer(self):
        projects_data = [{"id": 1, "members": [{"name": "Me"}, {"name": "Robbie"}]}]
        assert select_blocks(projects_data, []) == [
            BASE, PROJECTS, PROJECT_PARTICIPANTS, PROJECT_PAYER,
        ]

    def test_buddies_only_unlocks_direct_buddy_block(self):
        assert select_blocks([], [{"name": "Volker"}]) == [BASE, DIRECT_BUDDY]

    def test_mix_of_solo_and_multi_member_projects_unlocks_via_any(self):
        projects_data = [
            {"id": 1, "members": [{"name": "Me"}]},
            {"id": 2, "members": [{"name": "Me"}, {"name": "Robbie"}]},
        ]
        assert select_blocks(projects_data, []) == [
            BASE, PROJECTS, PROJECT_PARTICIPANTS, PROJECT_PAYER,
        ]

    def test_all_solo_projects_skip_participants_and_payer(self):
        projects_data = [
            {"id": 1, "members": [{"name": "Me"}]},
            {"id": 2, "members": [{"name": "Me"}]},
        ]
        assert select_blocks(projects_data, []) == [BASE, PROJECTS]

    def test_everything_present_keeps_declared_order(self):
        projects_data = [{"id": 1, "members": [{"name": "Me"}, {"name": "Robbie"}]}]
        single_buddies = [{"name": "Volker"}]
        assert select_blocks(projects_data, single_buddies) == [
            BASE, PROJECTS, PROJECT_PARTICIPANTS, PROJECT_PAYER, DIRECT_BUDDY,
        ]
