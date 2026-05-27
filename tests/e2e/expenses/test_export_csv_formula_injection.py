"""
Regression test for TICKET-03 — CSV formula injection, exercising the hand-rolled
CSV writer in budget/views/expenses.py::expenses_export.

The shared choke point (comaney.csv_export.write_model_csv) is covered by the pure
unit test tests/unit/test_csv_formula_injection.py. This e2e test covers the
*manual* writer used by the per-page expenses export, which the ticket also flags.

A user's own expense title beginning with a formula-trigger character must be
neutralised in the downloaded CSV (e.g. prefixed with a leading apostrophe) so the
spreadsheet treats it as text rather than a formula/DDE payload.

EXPECTED TO FAIL until expenses_export neutralises formula-triggering cells.

Run with (live stack at :8080 required):
    pytest tests/e2e/expenses/test_export_csv_formula_injection.py -sxv | tee logfile.log
"""
import csv
import io
import time

import pytest

from helpers import _url, http_session, form_login, create_confirmed_user, cleanup_user
from bhelpers import _shell

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


@pytest.fixture(scope="module")
def user():
    u = create_confirmed_user(first_name="Csv", last_name="Export")
    yield u
    cleanup_user(u["email"])


def _make_expense(email: str, title: str) -> None:
    """Create a settled personal expense dated today (so the default export
    window includes it)."""
    _shell(
        f"from datetime import date; from decimal import Decimal; "
        f"from feusers.models import FeUser; "
        f"from budget.expense_factory import create_expense; "
        f"from budget.models import TransactionType; "
        f"u = FeUser.objects.get(email='{email}'); "
        f"create_expense(owning_feuser=u, title={title!r}, type=TransactionType.EXPENSE, "
        f"value=Decimal('7.50'), date_due=date.today(), settled=True)"
    )


def _export_rows(session):
    resp = session.get(_url("/budget/expenses/export/"), timeout=10)
    assert resp.status_code == 200, f"export failed: {resp.status_code}"
    reader = csv.reader(io.StringIO(resp.text))
    rows = list(reader)
    header = rows[0]
    return header, rows[1:]


def _title_cell(header, row):
    return row[header.index("title")]


class TestExpensesExportFormulaInjection:

    def test_export_neutralises_formula_title(self, user):
        title = f'=HYPERLINK("https://evil.example/{int(time.time())}")'
        _make_expense(user["email"], title)

        s = http_session()
        assert form_login(s, user["email"], user["password"]).status_code in (301, 302)

        header, rows = _export_rows(s)
        cells = [_title_cell(header, r) for r in rows]
        matching = [c for c in cells if "evil.example" in c]
        assert matching, "test expense not found in export"
        for c in matching:
            assert c[0] not in FORMULA_PREFIXES, \
                f"formula title not neutralised in export: {c!r}"
