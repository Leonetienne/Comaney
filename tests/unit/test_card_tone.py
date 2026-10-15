"""
Shared expense card color (buddies/card_tone.py), same rule for contacts and projects.
Run with: venv/bin/pytest tests/unit/test_card_tone.py -v
"""
from decimal import Decimal

import pytest

from buddies.card_tone import I_PAID, NEUTRAL, OTHER_PAID, card_tone


def _share(percent, is_me=True):
    return {"is_me": is_me, "percent": Decimal(percent)}


@pytest.mark.parametrize("payer_is_me, shares, expected", [
    (True, [_share("50", is_me=False)], I_PAID),
    (False, [_share("30"), _share("70", is_me=False)], OTHER_PAID),
    (False, [_share("0"), _share("100", is_me=False)], NEUTRAL),
    (False, [_share("100", is_me=False)], NEUTRAL),
])
def test_card_tone(payer_is_me, shares, expected):
    assert card_tone(payer_is_me, shares) == expected
