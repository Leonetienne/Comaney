"""
Unit tests for comaney.json_utils.safe_json.

Ensures JSON embedded in <script> blocks via |safe cannot break out of the
script element via </script> injection (Issue 1 from the security audit).

No Django/DB required. Run with: venv/bin/pytest tests/unit/test_safe_json.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from comaney.json_utils import safe_json


def test_angle_brackets_escaped():
    result = safe_json({"name": "<b>bold</b>"})
    assert "<" not in result
    assert ">" not in result
    assert "\\u003c" in result
    assert "\\u003e" in result


def test_script_breakout_escaped():
    payload = "</script><script>window.__xss=1</script>"
    result = safe_json({"name": payload})
    assert "</script>" not in result
    assert "<script>" not in result


def test_ampersand_escaped():
    result = safe_json({"q": "foo&bar"})
    assert "&" not in result
    assert "\\u0026" in result


def test_output_is_valid_json():
    import json
    obj = {"name": "</script>", "score": 42, "flag": True}
    result = safe_json(obj)
    parsed = json.loads(result)
    assert parsed["name"] == "</script>"
    assert parsed["score"] == 42
    assert parsed["flag"] is True


def test_nested_structures():
    obj = {"members": [{"key": "f1", "name": "Alice <Evil>"}]}
    result = safe_json(obj)
    assert "<" not in result
    assert ">" not in result
    import json
    parsed = json.loads(result)
    assert parsed["members"][0]["name"] == "Alice <Evil>"


def test_plain_strings_unaffected():
    result = safe_json({"name": "Alice"})
    assert "Alice" in result


def test_empty_object():
    assert safe_json({}) == "{}"


def test_empty_list():
    assert safe_json([]) == "[]"
