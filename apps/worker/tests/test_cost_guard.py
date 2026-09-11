"""
Unit tests for RateGuard AI LLM Cost Guard & Budget Circuit Breaker (Phase 3.3).
Verifies:
1. Cache hit returns identical result with $0.00 spend.
2. Model ladder selects cheap model first, escalating to flagship only on failure.
3. Monthly circuit breaker trips at configurable threshold and halts API calls.
4. Token counting and cost computation accuracy.
"""
from pathlib import Path
import sys
import pytest

root_dir = Path(__file__).resolve().parents[3]
worker_dir = Path(__file__).resolve().parents[1]
audit_engine_dir = root_dir / "packages" / "audit-engine"
for p in [str(root_dir), str(worker_dir), str(audit_engine_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from cost_guard import (
    CircuitBreakerTrippedError,
    CostGuard,
    MODEL_PRICING,
)


def test_cost_calculation():
    """Verifies token pricing arithmetic against published pricing tiers."""
    guard = CostGuard(monthly_budget_usd=150.00)
    # gpt-4o-mini: $0.15 / 1M input, $0.60 / 1M output
    # 1,000 input tokens = $0.00015, 500 output tokens = $0.00030 -> Total = $0.00045
    cost = guard.compute_cost(model="gpt-4o-mini", input_tokens=1000, output_tokens=500)
    assert abs(cost - 0.00045) < 0.00001

    # gpt-4o: $2.50 / 1M input, $10.00 / 1M output
    cost_flagship = guard.compute_cost(model="gpt-4o", input_tokens=1000, output_tokens=500)
    assert abs(cost_flagship - 0.0075) < 0.0001


def test_model_ladder_selection():
    """Verifies that cheap model is selected by default and flagship only on escalation."""
    guard = CostGuard()

    # Default Tier 1 (cheap)
    assert guard.select_model(is_escalation=False, provider="openai") == "gpt-4o-mini"
    assert guard.select_model(is_escalation=False, provider="anthropic") == "claude-3-5-haiku-20241022"

    # Escalated Tier 2 (flagship)
    assert guard.select_model(is_escalation=True, provider="openai") == "gpt-4o"
    assert guard.select_model(is_escalation=True, provider="anthropic") == "claude-3-5-sonnet-20241022"


def test_parse_cache_zero_cost():
    """Verifies SHA-256 parse cache stores and retrieves extraction results with $0 cost."""
    guard = CostGuard()
    raw_content = b"%PDF-1.4 sample invoice bytes"
    cache_key = guard.get_cache_key(raw_content, prompt_version="v1.0")

    # Initial state: cache miss
    assert guard.get_cached(cache_key) is None

    # Populate cache
    mock_result = {"invoice_number": "INV-1234", "carrier": "ABF Freight", "total": 250.00}
    guard.set_cached(cache_key, mock_result)

    # Subsequent request: cache hit
    hit = guard.get_cached(cache_key)
    assert hit is not None
    assert hit["invoice_number"] == "INV-1234"
    assert guard.cumulative_spend_usd == 0.00  # $0.00 cost incurred!


def test_circuit_breaker_trips_at_threshold():
    """Verifies that the circuit breaker trips at the configured threshold and halts calls."""
    alert_events = []

    def on_alert(msg, spend):
        alert_events.append((msg, spend))

    # Staging test: small $0.01 threshold
    guard = CostGuard(monthly_budget_usd=150.00, circuit_breaker_threshold_usd=0.01, alert_callback=on_alert)

    # Initial state: healthy
    assert guard.is_tripped is False
    guard.check_can_spend(estimated_next_cost_usd=0.001)

    # Simulate heavy token call that pushes spend past $0.01
    # 20,000 output tokens on gpt-4o = 0.02 * $10 = $0.20
    guard.record_usage(model="gpt-4o", input_tokens=1000, output_tokens=20000)

    # Breaker must now be tripped
    assert guard.is_tripped is True
    assert len(alert_events) == 1
    assert "CIRCUIT BREAKER TRIPPED" in alert_events[0][0]

    # Subsequent spend check MUST raise CircuitBreakerTrippedError
    with pytest.raises(CircuitBreakerTrippedError):
        guard.check_can_spend(estimated_next_cost_usd=0.0001)
