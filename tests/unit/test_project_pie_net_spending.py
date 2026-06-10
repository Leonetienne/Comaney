"""
Pure unit tests for compute_net_member_spending, which feeds the project
spending-breakdown pie chart. No Django, no database, no running server.
Run with: pytest tests/unit/test_project_pie_net_spending.py -v
"""
from decimal import Decimal

from buddies.debt_utils import compute_net_member_spending

D = Decimal


def _regular(payer_key, total):
    return {"is_settlement": False, "payer_key": payer_key, "total": D(total), "participant_shares": []}


def _settlement(debtor_key, creditor_key, amount):
    return {
        "is_settlement": True,
        "payer_key": debtor_key,
        "total": D(amount),
        "participant_shares": [{"key": creditor_key, "amount": D(amount)}],
    }


class TestNoSettlements:

    def test_empty_returns_empty(self):
        assert compute_net_member_spending([]) == {}

    def test_single_payer(self):
        result = compute_net_member_spending([_regular("A", "100")])
        assert result == {"A": D("100")}

    def test_multiple_expenses_same_payer_accumulate(self):
        result = compute_net_member_spending([_regular("A", "100"), _regular("A", "60")])
        assert result == {"A": D("160")}

    def test_multiple_payers(self):
        result = compute_net_member_spending([_regular("A", "100"), _regular("B", "60")])
        assert result == {"A": D("100"), "B": D("60")}


class TestSettlementsAdjustNet:

    def test_settlement_moves_amount_from_creditor_to_debtor(self):
        # A paid 100 upfront for a dinner split 50/50 with B.
        # B settles their 50 debt to A: B is debtor, A is creditor.
        expenses = [
            _regular("A", "100"),
            _settlement(debtor_key="B", creditor_key="A", amount="50"),
        ]
        result = compute_net_member_spending(expenses)
        assert result == {"A": D("50"), "B": D("50")}

    def test_settlement_alone_nets_debtor_positive_creditor_negative(self):
        result = compute_net_member_spending([_settlement("B", "A", "50")])
        assert result == {"B": D("50"), "A": D("-50")}

    def test_full_settlement_cycle_conserves_total(self):
        # A pays 100 upfront (split 50/50 with B), then B fully settles.
        expenses = [
            _regular("A", "100"),
            _settlement(debtor_key="B", creditor_key="A", amount="50"),
        ]
        result = compute_net_member_spending(expenses)
        assert sum(result.values(), D("0")) == D("100")

    def test_partial_settlement(self):
        # A pays 100 upfront (owed 50 by B), B only settles 20 of it.
        expenses = [
            _regular("A", "100"),
            _settlement(debtor_key="B", creditor_key="A", amount="20"),
        ]
        result = compute_net_member_spending(expenses)
        assert result == {"A": D("80"), "B": D("20")}

    def test_settlement_to_third_party_creditor(self):
        # A paid for something B owes; C independently settles a debt to A.
        expenses = [
            _regular("A", "100"),
            _settlement(debtor_key="C", creditor_key="A", amount="30"),
        ]
        result = compute_net_member_spending(expenses)
        assert result == {"A": D("70"), "C": D("30")}
