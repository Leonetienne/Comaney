from buddies.share_bounds import SHARE_BOUNDS_MSG, share_bounds_error


def _s(*shares):
    return [{"type": "feuser", "id": i, "share_percent": v} for i, v in enumerate(shares)]


def test_shares_up_to_100_are_valid():
    assert share_bounds_error(_s(25, 75)) is None
    assert share_bounds_error(_s(33.333, 33.333, 33.334)) is None
    assert share_bounds_error([]) is None


def test_rounding_within_tolerance_is_valid():
    assert share_bounds_error(_s(50.0005, 50.0005)) is None


def test_sum_above_100_is_rejected():
    assert share_bounds_error(_s(60, 50)) == SHARE_BOUNDS_MSG


def test_share_out_of_range_is_rejected():
    assert share_bounds_error(_s(-5, 20)) == SHARE_BOUNDS_MSG
    assert share_bounds_error(_s(120)) == SHARE_BOUNDS_MSG


def test_missing_or_garbage_share_is_rejected():
    assert share_bounds_error([{"type": "feuser", "id": 1}]) == SHARE_BOUNDS_MSG
    assert share_bounds_error(_s("abc")) == SHARE_BOUNDS_MSG
    assert share_bounds_error(_s(float("nan"))) == SHARE_BOUNDS_MSG
