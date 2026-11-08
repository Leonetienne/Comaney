from decimal import Decimal

# shares are stored with 3 decimals, so client-side rounding may overshoot 100 by this much
SHARE_SUM_TOLERANCE = Decimal("0.001")
SHARE_BOUNDS_MSG = "Each participant share must be between 0 % and 100 %, and all shares together at most 100 %."


def share_bounds_error(spendings) -> str | None:
    """SHARE_BOUNDS_MSG when a share is missing, outside 0..100, or the shares sum above 100; else None."""
    total = Decimal(0)
    for p in spendings or []:
        try:
            share = Decimal(str(p["share_percent"]))
        except (KeyError, TypeError, ArithmeticError):
            return SHARE_BOUNDS_MSG
        if not share.is_finite() or share < 0 or share > 100:
            return SHARE_BOUNDS_MSG
        total += share
    if total > 100 + SHARE_SUM_TOLERANCE:
        return SHARE_BOUNDS_MSG
    return None
