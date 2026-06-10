"""
Regression test: buddies/views/partnership.py must call
suggest_tag_mappings/suggest_category_mappings with all 4 required
positional arguments (feuser, master_feuser, sources, targets).

Found while migrating partnership AI onboarding to budget.ai_service.AIService:
a prior version of this file called suggest_tag_mappings(request.feuser,
unmatched, master_tags) -- 3 positional args against the service's 4-arg
required signature -- so master_feuser was actually unmatched and
target_tags was missing entirely. This raised TypeError on every real
onboarding "AI suggest" click, silently swallowed by the view's generic
except Exception into "AI suggestion failed. Please map manually." Same bug,
same fix, for suggest_category_mappings.

buddies/views/partnership.py can't be imported here without a configured
Django settings module (same constraint as the other tests in this
directory), so this parses the source directly and checks the call sites'
arity instead of importing and invoking them.
Run with: venv/bin/pytest tests/unit/test_partnership_ai_call_arity.py -v
"""
import ast
import os

_VIEW_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "buddies", "views", "partnership.py",
)


def _call_arg_counts(function_name: str) -> list[int]:
    tree = ast.parse(open(_VIEW_PATH, encoding="utf-8").read(), filename=_VIEW_PATH)
    return [
        len(node.args) for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == function_name
    ]


class TestPartnershipAiCallArity:

    def test_suggest_tag_mappings_called_with_all_four_args(self):
        counts = _call_arg_counts("suggest_tag_mappings")
        assert counts, "suggest_tag_mappings is not called anywhere in partnership.py"
        assert all(c == 4 for c in counts), (
            "suggest_tag_mappings must be called with (feuser, master_feuser, "
            f"source_tags, target_tags) -- found call(s) with {counts} positional args"
        )

    def test_suggest_category_mappings_called_with_all_four_args(self):
        counts = _call_arg_counts("suggest_category_mappings")
        assert counts, "suggest_category_mappings is not called anywhere in partnership.py"
        assert all(c == 4 for c in counts), (
            "suggest_category_mappings must be called with (feuser, master_feuser, "
            f"source_cats, target_cats) -- found call(s) with {counts} positional args"
        )
