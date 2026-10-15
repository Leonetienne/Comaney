"""
Pure color tone of a shared expense card, from the viewer's side.
Importable from unit tests without a running Django/database setup.
"""
from decimal import Decimal

I_PAID = "i-paid"
OTHER_PAID = "other-paid"
NEUTRAL = "neutral"


def card_tone(payer_is_me: bool, participant_shares: list) -> str:
    """
    payer_is_me: the viewer paid upfront.
    participant_shares: dicts with "is_me" and "percent", one per BuddySpending row.

    Returns I_PAID, OTHER_PAID when the viewer holds a share above 0%, else NEUTRAL.
    """
    if payer_is_me:
        return I_PAID
    my_percent = sum((p["percent"] for p in participant_shares if p["is_me"]), Decimal("0"))
    return OTHER_PAID if my_percent > 0 else NEUTRAL
