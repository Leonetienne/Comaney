"""
A project's AI preprompt reaches AI Express through the catalog
(budget/express_service.py::_build_catalog) as the project's "instructions",
so it applies no matter where AI Express was started from. Projects without a
preprompt carry no "instructions" key at all.

Run with: venv/bin/pytest tests/e2e/projects/test_express_project_preprompt.py -v
"""
import json

import pytest

from helpers import setup_user, cleanup_user
from bhelpers import _shell, _create_group

PREPROMPT = "Put Robert and Mallory always at 0%, they're invited."


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w, first_name="Pia", last_name="Preprompt")
    with_pp = int(_create_group(c["email"], "Preprompt Project"))
    without_pp = int(_create_group(c["email"], "Plain Project"))
    _shell(
        "from buddies.models import Project; "
        f"Project.objects.filter(pk={with_pp}).update(ai_preprompt={PREPROMPT!r})"
    )
    yield {**c, "with_pp": with_pp, "without_pp": without_pp}
    cleanup_user(c["email"])


def _catalog_projects(email):
    out = _shell(
        "import json; "
        "from feusers.models import FeUser; "
        "from budget.express_service import _build_catalog; "
        f"cat = _build_catalog(FeUser.objects.get(email='{email}'), [], []); "
        "print(json.dumps(cat))"
    )
    catalog = json.loads(out.splitlines()[-1])
    projects_json = catalog.split("Projects (", 1)[1].split("\n", 2)[2].split("\n\n", 1)[0]
    return {p["uid"]: p for p in json.loads(projects_json)}


class TestExpressProjectPreprompt:

    def test_preprompt_sent_as_project_instructions(self, ctx):
        projects = _catalog_projects(ctx["email"])
        assert projects[ctx["with_pp"]]["instructions"] == PREPROMPT

    def test_project_without_preprompt_has_no_instructions(self, ctx):
        projects = _catalog_projects(ctx["email"])
        assert "instructions" not in projects[ctx["without_pp"]]

    def test_system_prompt_scopes_instructions_to_their_project(self, ctx):
        out = _shell(
            "from budget.express_service import _SMART_CREATE_PROJECTS; "
            "print(_SMART_CREATE_PROJECTS)"
        )
        assert '"instructions"' in out
        assert "never apply them to any other expense" in out
