"""
Pure unit tests for the buddy debt simplification algorithm.
No Django, no database, no running server required.
Run with: pytest tests/unit/
"""
from decimal import Decimal

import pytest

from buddies.debt_utils import simplify_balances

D = Decimal


def _amounts_by_debtor(transactions):
    return {dk: amt for dk, ck, amt in transactions}


def _amounts_by_creditor(transactions):
    result = {}
    for _, ck, amt in transactions:
        result[ck] = result.get(ck, D("0")) + amt
    return result


class TestSimplifyBalancesBasic:

    def test_empty_returns_empty(self):
        assert simplify_balances({}) == []

    def test_all_zero_returns_empty(self):
        assert simplify_balances({"A": D("0"), "B": D("0"), "C": D("0")}) == []

    def test_near_zero_treated_as_settled(self):
        # values within 0.005 threshold are ignored
        assert simplify_balances({"A": D("0.004"), "B": D("-0.004")}) == []

    def test_single_debt(self):
        result = simplify_balances({"A": D("10"), "B": D("-10")})
        assert result == [("B", "A", D("10"))]

    def test_single_debt_reversed_map_order(self):
        # dict ordering should not affect correctness
        # each tuple is: (debtor_key, creditor_key, amount)
        # meaning: B owes A 10
        result = simplify_balances({"B": D("-10"), "A": D("10")})
        assert result == [("B", "A", D("10"))]


class TestSimplifyBalancesMultiParty:

    def test_two_debtors_one_creditor(self):
        # A is owed by B and C equally
        balances = {"A": D("10"), "B": D("-5"), "C": D("-5")}
        result = simplify_balances(balances)
        assert len(result) == 2
        by_debtor = _amounts_by_debtor(result)
        assert by_debtor["B"] == D("5")
        assert by_debtor["C"] == D("5")
        assert all(ck == "A" for _, ck, _ in result)

    def test_one_debtor_two_creditors(self):
        # C owes both A and B
        balances = {"A": D("5"), "B": D("5"), "C": D("-10")}
        result = simplify_balances(balances)
        assert len(result) == 2
        assert sum(amt for _, _, amt in result) == D("10")
        assert all(dk == "C" for dk, _, _ in result)

    def test_partial_amounts(self):
        balances = {"A": D("25"), "B": D("-15"), "C": D("-10")}
        result = simplify_balances(balances)
        by_debtor = _amounts_by_debtor(result)
        assert by_debtor["B"] == D("15")
        assert by_debtor["C"] == D("10")

    def test_unequal_split(self):
        balances = {"A": D("10"), "B": D("-6.5"), "C": D("-3.5")}
        result = simplify_balances(balances)
        by_debtor = _amounts_by_debtor(result)
        assert by_debtor["B"] == D("6.5")
        assert by_debtor["C"] == D("3.5")
        assert all(ck == "A" for _, ck, _ in result)


class TestSimplifyBalancesChaining:

    def test_chain_resolves_directly(self):
        # A owes B 5, B owes C 5 -> net: A=-5, B=0, C=+5
        # Optimal: A pays C directly (one transaction)
        balances = {"A": D("-5"), "B": D("0"), "C": D("5")}
        result = simplify_balances(balances)
        assert result == [("A", "C", D("5"))]

    def test_pass_through(self):
        # B owes A 5, C owes B 5 -> net: A=+5, B=0, C=-5
        # Optimal: C pays A directly
        balances = {"A": D("5"), "B": D("0"), "C": D("-5")}
        result = simplify_balances(balances)
        assert result == [("C", "A", D("5"))]

    def test_three_way_cycle_simplifies(self):
        # A owes B 3, B owes C 5, C owes A 2
        # Net: A=-3+2=-1, B=+3-5=-2, C=-2+5=+3
        # Simplified: A pays C 1, B pays C 2 (2 transactions instead of 3)
        balances = {"A": D("-1"), "B": D("-2"), "C": D("3")}
        result = simplify_balances(balances)
        assert len(result) == 2
        by_debtor = _amounts_by_debtor(result)
        assert by_debtor["A"] == D("1")
        assert by_debtor["B"] == D("2")
        assert all(ck == "C" for _, ck, _ in result)


class TestSimplifyBalancesUserExample:
    """
    B owes A 5, C owes A 5.
    C pays 3 for an expense split 50/50 between B and C.
    After balance computation: A=+10, B=-6.5, C=-3.5
    Expected: B pays A 6.5, C pays A 3.5 (both direct, two transactions).
    """

    def test_bca_scenario(self):
        balances = {"A": D("10"), "B": D("-6.5"), "C": D("-3.5")}
        result = simplify_balances(balances)
        assert len(result) == 2
        by_debtor = _amounts_by_debtor(result)
        assert by_debtor["B"] == D("6.5")
        assert by_debtor["C"] == D("3.5")
        assert all(ck == "A" for _, ck, _ in result)

    def test_bca_balance_computation(self):
        """Verify the balance numbers that feed into the above scenario."""
        # Expense 1: A pays 5, B owes 100%
        # Expense 2: A pays 5, C owes 100%
        # Expense 3: C pays 3, B 50% and C 50%
        balances = {"A": D("0"), "B": D("0"), "C": D("0")}

        # Expense 1
        balances["A"] += D("5")
        balances["B"] -= D("5")

        # Expense 2
        balances["A"] += D("5")
        balances["C"] -= D("5")

        # Expense 3: C is payer, B and C each 50% of 3
        for participant, share_pct in [("B", D("50")), ("C", D("50"))]:
            amount = D("3") * share_pct / D("100")
            balances["C"] += amount       # payer gets reimbursed
            balances[participant] -= amount  # participant owes

        assert balances["A"] == D("10")
        assert balances["B"] == D("-6.5")
        assert balances["C"] == D("-3.5")


class TestSimplifyBalancesConservation:
    """Money is conserved: total credits == total debits in every case."""

    def _check_conservation(self, balances):
        result = simplify_balances(balances)
        credits = {}
        debits = {}
        for dk, ck, amt in result:
            credits[ck] = credits.get(ck, D("0")) + amt
            debits[dk] = debits.get(dk, D("0")) + amt
        for k, v in balances.items():
            if v > D("0.005"):
                assert credits.get(k, D("0")) == v, f"creditor {k}: got {credits.get(k)}, expected {v}"
            elif v < D("-0.005"):
                assert debits.get(k, D("0")) == -v, f"debtor {k}: got {debits.get(k)}, expected {-v}"

    def test_conservation_two_party(self):
        self._check_conservation({"A": D("7"), "B": D("-7")})

    def test_conservation_four_party(self):
        self._check_conservation({"A": D("8"), "B": D("2"), "C": D("-6"), "D": D("-4")})

    def test_conservation_complex(self):
        self._check_conservation({
            "A": D("100"),
            "B": D("-30"),
            "C": D("-40"),
            "D": D("-20"),
            "E": D("-10"),
        })

    def test_conservation_mixed_creditors(self):
        self._check_conservation({
            "A": D("50"),
            "B": D("30"),
            "C": D("-45"),
            "D": D("-35"),
        })
