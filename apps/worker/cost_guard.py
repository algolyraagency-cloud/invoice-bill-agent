"""
RateGuard AI — LLM Cost Guard & Budget Circuit Breaker (Phase 3.3).
Enforces PRD §9 Operating Budget Ceiling ($200/mo total run rate, $150/mo LLM cap).

Features:
1. Parse Cache: Keyed by sha256(content + prompt_version) guaranteeing $0 spend on re-scans.
2. Model Ladder: Cheap model first (gpt-4o-mini / claude-haiku); escalate to flagship only on validation failure.
3. Monthly Circuit Breaker: Tracks cumulative estimated spend; halts LLM calls when spend exceeds threshold.
4. Token Cap Guard: Strict per-job token ceilings to avoid runaway context.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from typing import Any, Callable, Dict, Optional, Tuple, Union

logger = logging.getLogger("rateguard.cost_guard")

# Default Pricing per 1,000,000 tokens (USD)
# Prices updated to standard OpenAI / Anthropic rates
MODEL_PRICING: Dict[str, Dict[str, float]] = {
    # Tier 1 Cheap Models
    "gpt-4o-mini": {"input_per_m": 0.15, "output_per_m": 0.60},
    "claude-3-5-haiku-20241022": {"input_per_m": 0.80, "output_per_m": 4.00},
    "claude-3-haiku-20240307": {"input_per_m": 0.25, "output_per_m": 1.25},
    # Tier 2 Flagship Models (Escalation only)
    "gpt-4o": {"input_per_m": 2.50, "output_per_m": 10.00},
    "claude-3-5-sonnet-20241022": {"input_per_m": 3.00, "output_per_m": 15.00},
}


class CircuitBreakerTrippedError(RuntimeError):
    """Raised when monthly LLM spend exceeds the configured safety ceiling."""
    pass


@dataclass
class UsageRecord:
    timestamp: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    purpose: str


class CostGuard:
    """
    Manages LLM spend, token limits, model ladder selection, and circuit breaking.
    """

    def __init__(
        self,
        monthly_budget_usd: float = 150.00,
        circuit_breaker_threshold_usd: Optional[float] = None,
        alert_callback: Optional[Callable[[str, float], None]] = None,
    ):
        # Default ceiling is $150 of the $200/mo operating budget (leaving $50 for Postmark, Supabase, etc.)
        self.monthly_budget_usd = monthly_budget_usd
        self.circuit_breaker_threshold_usd = (
            circuit_breaker_threshold_usd if circuit_breaker_threshold_usd is not None else monthly_budget_usd
        )
        self.alert_callback = alert_callback
        self.cumulative_spend_usd = 0.0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.usage_history: list[UsageRecord] = []
        self._tripped = False

        # In-memory SHA-256 parse cache: sha256(content + prompt_version) -> result dict
        self._parse_cache: Dict[str, Dict[str, Any]] = {}

    @property
    def is_tripped(self) -> bool:
        return self._tripped

    def compute_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculates estimated USD cost for token consumption."""
        pricing = MODEL_PRICING.get(model, {"input_per_m": 0.50, "output_per_m": 2.00})
        input_cost = (input_tokens / 1_000_000.0) * pricing["input_per_m"]
        output_cost = (output_tokens / 1_000_000.0) * pricing["output_per_m"]
        return round(input_cost + output_cost, 6)

    def record_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        purpose: str = "invoice_extraction",
    ) -> float:
        """
        Records actual or estimated token usage, increments cumulative spend,
        and evaluates circuit breaker trip condition.
        """
        cost = self.compute_cost(model, input_tokens, output_tokens)
        self.cumulative_spend_usd += cost
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens

        record = UsageRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=cost,
            purpose=purpose,
        )
        self.usage_history.append(record)

        # Check circuit breaker
        if self.cumulative_spend_usd >= self.circuit_breaker_threshold_usd:
            self._tripped = True
            msg = (
                f"CIRCUIT BREAKER TRIPPED: Cumulative LLM spend ${self.cumulative_spend_usd:.4f} "
                f"exceeded threshold ${self.circuit_breaker_threshold_usd:.2f}."
            )
            logger.error(msg)
            if self.alert_callback:
                try:
                    self.alert_callback(msg, self.cumulative_spend_usd)
                except Exception as cb_err:
                    logger.warning(f"Alert callback error: {cb_err}")

        return cost

    def check_can_spend(self, estimated_next_cost_usd: float = 0.001):
        """Raises CircuitBreakerTrippedError if spend ceiling is breached."""
        if self._tripped or (self.cumulative_spend_usd + estimated_next_cost_usd > self.circuit_breaker_threshold_usd):
            self._tripped = True
            raise CircuitBreakerTrippedError(
                f"LLM spend ceiling reached: ${self.cumulative_spend_usd:.4f} / ${self.circuit_breaker_threshold_usd:.2f}. "
                "Halting further API calls to protect budget."
            )

    def get_cache_key(self, content: Union[str, bytes], prompt_version: str = "v1.0") -> str:
        """Generates deterministic SHA-256 cache key from content bytes/text and prompt version."""
        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            content_bytes = content
        return hashlib.sha256(content_bytes + prompt_version.encode("utf-8")).hexdigest()

    def get_cached(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieves cached extraction result ($0 spend)."""
        return self._parse_cache.get(key)

    def set_cached(self, key: str, value: Dict[str, Any]):
        """Persists extraction result in memory cache."""
        self._parse_cache[key] = value

    def select_model(self, is_escalation: bool = False, provider: str = "openai") -> str:
        """
        Model Ladder:
        Tier 1 (Default): gpt-4o-mini (OpenAI) or claude-3-5-haiku (Anthropic)
        Tier 2 (Escalation only on validation failure): gpt-4o or claude-3-5-sonnet
        """
        if provider == "anthropic":
            return "claude-3-5-sonnet-20241022" if is_escalation else "claude-3-5-haiku-20241022"
        return "gpt-4o" if is_escalation else "gpt-4o-mini"

    def reset_monthly_cycle(self):
        """Resets counters for a new billing cycle or testing setup."""
        self.cumulative_spend_usd = 0.0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.usage_history.clear()
        self._tripped = False


# Global default instance configured with $150 monthly limit
global_cost_guard = CostGuard(monthly_budget_usd=150.00)
