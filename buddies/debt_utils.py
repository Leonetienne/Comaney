"""
Pure debt simplification logic with no Django dependencies.
Importable from unit tests without a running Django/database setup.
"""
from decimal import Decimal


def simplify_balances(balances: dict) -> list:
    """
    Greedy minimum-transaction debt simplification.

    balances: mapping of {key: Decimal-compatible} where positive means the
              person is a net creditor and negative means a net debtor.

    Returns a list of (debtor_key, creditor_key, Decimal amount) tuples
    representing the minimum set of transfers that clears all debts.
    """
    bal = {k: Decimal(str(v)) for k, v in balances.items()}
    transactions = []
    while True:
        creditors = [(k, v) for k, v in bal.items() if v > Decimal("0.005")]
        debtors = [(k, v) for k, v in bal.items() if v < Decimal("-0.005")]
        if not creditors or not debtors:
            break
        creditors.sort(key=lambda x: -x[1])
        debtors.sort(key=lambda x: x[1])
        ck, cv = creditors[0]
        dk, dv = debtors[0]
        amount = min(cv, -dv)
        transactions.append((dk, ck, amount))
        bal[ck] -= amount
        bal[dk] += amount
    return transactions
