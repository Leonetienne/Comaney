"""
Unit tests for the AI usage-cost computation in
budget/ai_service.py::_compute_usage_cost.

budget.ai_service has no module-level Django/DB imports, so unlike most
files under budget/ it imports cleanly without a configured Django settings
module -- this exercises the real function directly rather than a mirror.
Run with: venv/bin/pytest tests/unit/test_express_usage_cost.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from budget.ai_service import _compute_usage_cost as compute_usage_cost


def test_typical_request_cost():
    usage = compute_usage_cost(input_tok=4000, output_tok=300, cache_write_tok=0, cache_read_tok=0)
    assert usage["cost_usd"] == round((4000 / 1_000_000) * 3.00 + (300 / 1_000_000) * 15.00, 6)
    assert usage["cost_cents"] == round(usage["cost_usd"] * 100, 4)
    assert usage["cost_cents"] > 0


def test_cache_heavy_tiny_request_not_rounded_to_zero():
    """A cheap, cache-heavy request (a handful of output tokens plus a cache
    read) must keep a nonzero cost_cents at 4-decimal precision, even though
    it would round to 0.0 at 1-decimal precision (the bug this guards
    against: such requests would silently escape trial-budget accounting)."""
    usage = compute_usage_cost(input_tok=0, output_tok=5, cache_write_tok=0, cache_read_tok=100)
    assert usage["cost_cents"] > 0
    assert round(usage["cost_cents"], 1) == 0.0, (
        "This case is only meaningful if it would have rounded to 0.0 cents at 1-decimal precision"
    )


def test_zero_usage_is_zero_cost():
    usage = compute_usage_cost(0, 0, 0, 0)
    assert usage["cost_usd"] == 0.0
    assert usage["cost_cents"] == 0.0


def test_cache_write_and_read_priced_independently():
    write_only = compute_usage_cost(0, 0, cache_write_tok=1_000_000, cache_read_tok=0)
    read_only = compute_usage_cost(0, 0, cache_write_tok=0, cache_read_tok=1_000_000)
    assert write_only["cost_usd"] == 3.75
    assert read_only["cost_usd"] == 0.30
