"""
Unit tests for partnership AI response parsing.
No Django, no database.
Run with: venv/bin/pytest tests/unit/test_partnership_ai_parsing.py -v
"""
import json
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def _parse_mappings(raw: str) -> list[dict]:
    """Mirror the parsing logic from partnership_ai._suggest_mappings, which
    now delegates JSON recovery to express_service.extract_json_object via
    call_ai_for_json (see test_express_json_extraction.py for that helper's
    own tests)."""
    cleaned = raw
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    idx = cleaned.find("{")
    if idx != -1:
        cleaned = cleaned[idx:]
    parsed, _end = json.JSONDecoder(strict=False).raw_decode(cleaned)
    return parsed["mappings"]


class TestAIMappingParsing:

    def test_clean_json(self):
        raw = '{"mappings": [{"source": "beer", "target": "alcohol"}, {"source": "wine", "target": "alcohol"}]}'
        result = _parse_mappings(raw)
        assert result == [
            {"source": "beer", "target": "alcohol"},
            {"source": "wine", "target": "alcohol"},
        ]

    def test_null_target(self):
        raw = '{"mappings": [{"source": "outdoors", "target": null}]}'
        result = _parse_mappings(raw)
        assert result[0]["target"] is None

    def test_code_fence_stripped(self):
        raw = '```json\n{"mappings": [{"source": "food", "target": "groceries"}]}\n```'
        result = _parse_mappings(raw)
        assert result[0]["source"] == "food"

    def test_trailing_sign_off_ignored(self):
        raw = '{"mappings": [{"source": "food", "target": "groceries"}]}\nHope that helps!'
        result = _parse_mappings(raw)
        assert result[0]["source"] == "food"

    def test_empty_mappings_list(self):
        raw = '{"mappings": []}'
        assert _parse_mappings(raw) == []

    def test_invalid_json_raises(self):
        with pytest.raises((json.JSONDecodeError, KeyError)):
            _parse_mappings("this is not json")

    def test_missing_mappings_key_raises(self):
        with pytest.raises(KeyError):
            _parse_mappings('{"result": "good"}')

    def test_n_to_1_multiple_sources_same_target(self):
        raw = json.dumps({"mappings": [
            {"source": "bier", "target": "alcohol"},
            {"source": "wein", "target": "alcohol"},
            {"source": "schnaps", "target": "alcohol"},
        ]})
        result = _parse_mappings(raw)
        assert all(m["target"] == "alcohol" for m in result)
        assert len(result) == 3

    def test_unicode_tags(self):
        raw = json.dumps({"mappings": [{"source": "essen", "target": "food"}]})
        result = _parse_mappings(raw)
        assert result[0]["source"] == "essen"
