"""
Unit tests for dashboard-card AI response parsing and the docs-reference builder.
No Django, no database.
Run with: venv/bin/pytest tests/unit/test_dashboard_card_ai_parsing.py -v
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from budget.dashboard_card_ai import _DOC_FILES, _DOCS_BASE_URL, _build_docs_reference


def _parse_envelope(raw: str) -> str:
    """Mirror the parsing logic from dashboard_card_ai._parse_response.
    Importing that function directly would pull in budget.express_service,
    which needs Django configured -- so this unit test mirrors the algorithm
    instead, same as test_partnership_ai_parsing.py does for partnership_ai.
    """
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    if not raw.startswith('{"result":'):
        idx = raw.find('{"result":')
        if idx == -1:
            idx = raw.find('{ "result":')
        if idx != -1:
            raw = raw[idx:]

    if not raw:
        raise ValueError("empty response")

    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("not a dict")

    if parsed.get("result") == "fail":
        raise LookupError(parsed.get("msg", ""))
    if parsed.get("result") != "good":
        raise ValueError("unexpected result value")

    yaml_str = parsed.get("yaml")
    if not isinstance(yaml_str, str) or not yaml_str.strip():
        raise ValueError("missing or empty yaml")

    return yaml_str


class TestEnvelopeParsing:

    def test_clean_success(self):
        raw = '{"result": "good", "yaml": "type: cell\\ntitle: Test\\n"}'
        assert _parse_envelope(raw) == "type: cell\ntitle: Test\n"

    def test_code_fence_stripped(self):
        raw = '```json\n{"result": "good", "yaml": "type: cell\\n"}\n```'
        assert _parse_envelope(raw) == "type: cell\n"

    def test_leading_prose_skipped(self):
        raw = 'Sure, here you go!\n{"result": "good", "yaml": "type: cell\\n"}'
        assert _parse_envelope(raw) == "type: cell\n"

    def test_fail_result_raises(self):
        raw = '{"result": "fail", "msg": "i cannot do that >.<"}'
        with pytest.raises(LookupError):
            _parse_envelope(raw)

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_envelope("this is not json")

    def test_missing_yaml_key_raises(self):
        with pytest.raises(ValueError):
            _parse_envelope('{"result": "good"}')

    def test_empty_yaml_raises(self):
        with pytest.raises(ValueError):
            _parse_envelope('{"result": "good", "yaml": "   "}')

    def test_unknown_result_value_raises(self):
        with pytest.raises(ValueError):
            _parse_envelope('{"result": "maybe", "yaml": "type: cell\\n"}')


class TestDocsReference:

    def test_builds_non_empty_reference(self):
        assert len(_build_docs_reference()) > 1000

    def test_cites_every_child_page_url(self):
        ref = _build_docs_reference()
        for _, slug in _DOC_FILES:
            url = f"{_DOCS_BASE_URL}/{slug}/" if slug else f"{_DOCS_BASE_URL}/"
            assert url in ref, f"missing citation for {url}"

    def test_includes_known_schema_keywords(self):
        ref = _build_docs_reference()
        for keyword in ("positioning", "color_breakpoints", "line-chart", "query"):
            assert keyword in ref
