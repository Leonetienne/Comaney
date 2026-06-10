"""
Unit tests for budget/ai_service.py::_extract_json_object -- the shared
raw-AI-response JSON recovery used by express creation, dashboard card AI,
and partnership AI (via AIService._call_and_repair).

budget.ai_service has no module-level Django/DB imports, so unlike most
files under budget/ it imports cleanly without a configured Django settings
module -- this exercises the real function directly rather than a mirror.
Run with: venv/bin/pytest tests/unit/test_express_json_extraction.py -v
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from budget.ai_service import _extract_json_object as extract_json_object


class TestExtractJsonObject:

    def test_clean_response(self):
        raw = '{"result": "good", "items": []}'
        assert extract_json_object(raw) == {"result": "good", "items": []}

    def test_code_fence_stripped(self):
        raw = '```json\n{"result": "good", "items": []}\n```'
        assert extract_json_object(raw) == {"result": "good", "items": []}

    def test_leading_prose_skipped(self):
        raw = 'Sure, here you go!\n{"result": "good", "items": []}'
        assert extract_json_object(raw) == {"result": "good", "items": []}

    def test_trailing_sign_off_ignored(self):
        # The bug this test guards: a model that appends a closing remark
        # after the JSON despite being told not to used to make json.loads
        # raise "Extra data" and reject the whole (valid) response.
        raw = '{"result": "good", "items": []}\nHope that helps! ^_^'
        assert extract_json_object(raw) == {"result": "good", "items": []}

    def test_trailing_code_fence_after_valid_json(self):
        raw = '```json\n{"result": "good", "items": []}\n```\nLet me know if you need more!'
        assert extract_json_object(raw) == {"result": "good", "items": []}

    def test_multi_item_receipt_response_with_trailing_note(self):
        items = [
            {"title": "Grillen Drinks", "value": 48.45},
            {"title": "Grillen Food", "value": 68.46},
        ]
        raw = json.dumps({"result": "good", "items": items}) + "\nI grouped the Pfand into Drinks."
        parsed = extract_json_object(raw)
        assert parsed["result"] == "good"
        assert len(parsed["items"]) == 2

    def test_raw_line_break_inside_string_tolerated(self):
        # strict=False: a literal, unescaped newline inside a string value
        # (e.g. an OCR'd multi-line note) is accepted instead of raising
        # "Invalid control character".
        raw = '{"result": "good", "msg": "line one\nline two"}'
        parsed = extract_json_object(raw)
        assert parsed["msg"] == "line one\nline two"

    def test_empty_response_raises(self):
        with pytest.raises(json.JSONDecodeError):
            extract_json_object("")

    def test_no_json_object_raises(self):
        with pytest.raises(json.JSONDecodeError):
            extract_json_object("this is not json at all")

    def test_fail_envelope_still_parses(self):
        raw = '{"result": "fail", "msg": "ahh i cannot tell >.<"}'
        assert extract_json_object(raw) == {"result": "fail", "msg": "ahh i cannot tell >.<"}
