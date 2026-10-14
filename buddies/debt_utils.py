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


def compute_net_member_spending(expenses: list) -> dict:
    """
    Net per-member spending for the project spending-breakdown pie chart.

    Regular expenses contribute their upfront payment to the payer. A
    settlement moves its amount from the creditor's total to the debtor's
    (settling a debt from debtor A to creditor B adds the amount to A's net
    and subtracts it from B's), instead of being ignored, so the pie reflects
    who has effectively borne the cost after settlements even out.

    expenses: list of dicts, each with:
      is_settlement: bool
      payer_key: str -- the payer (debtor, for a settlement)
      total: Decimal-compatible
      participant_shares: list of {"key": str, "amount": Decimal-compatible}
        (only used for settlements, which have a single 100%-share creditor)

    Returns {member_key: Decimal net}.
    """
    spending: dict = {}
    for exp in expenses:
        if exp["is_settlement"]:
            debtor_key = exp["payer_key"]
            spending[debtor_key] = spending.get(debtor_key, Decimal("0")) + exp["total"]
            for share in exp["participant_shares"]:
                creditor_key = share["key"]
                spending[creditor_key] = spending.get(creditor_key, Decimal("0")) - share["amount"]
        else:
            pk = exp["payer_key"]
            spending[pk] = spending.get(pk, Decimal("0")) + exp["total"]
    return spending


def net_expense_flows(expenses: list) -> list:
    """
    Pairwise expense flows behind the project's "Expense flows" graph: every
    participant share points from the participant to the payer, and opposite
    flows between the same two people cancel out.

    expenses: list of dicts with payer_key and participant_shares
              ([{"key": str, "amount": Decimal-compatible}]), approved ones only.

    Returns a list of (from_key, to_key, Decimal amount) with amount > 0.005.
    """
    flows: dict = {}
    for exp in expenses:
        to = exp["payer_key"]
        for share in exp["participant_shares"]:
            frm = share["key"]
            if frm == to:
                continue
            amount = Decimal(str(share["amount"]))
            opposite = flows.pop((to, frm), Decimal("0"))
            if opposite > amount:
                flows[(to, frm)] = opposite - amount
            else:
                flows[(frm, to)] = flows.get((frm, to), Decimal("0")) + amount - opposite
    return [(f, t, a) for (f, t), a in flows.items() if a > Decimal("0.005")]
