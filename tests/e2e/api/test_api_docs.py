"""
The user manual's API page lists every REST v2 route the registry serves.
Run with: pytest -v tests/e2e/api/test_api_docs.py | tee logfile.log
"""
import json
import os
import re

from helpers import run_cmd

DOC = os.path.join(os.path.dirname(__file__), "..", "..", "..", "docs", "src", "docs", "user-manual", "api-access.md")


def test_every_route_is_documented():
    out = run_cmd(
        "shell", "-c",
        "import json; from api.operations import REGISTRY; "
        "print(json.dumps(sorted({(o.method, o.path) for o in REGISTRY.values()})))",
    )
    routes = json.loads(out.strip().splitlines()[-1])
    doc = open(DOC, encoding="utf-8").read()
    documented = {
        (m, re.sub(r"<(\w+)>", r"<int:\1>", p))
        for m, p in re.findall(r"\| (GET|POST|PATCH|PUT|DELETE) \| `/api/v2/([^`]*)` \|", doc)
    }
    missing = [f"{m} /api/v2/{p}" for m, p in routes if (m, p) not in documented]
    assert not missing, f"Undocumented routes: {missing}"
