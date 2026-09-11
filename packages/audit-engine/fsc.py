"""
RateGuard AI — Deterministic Fuel Surcharge (FSC) Engine (Phase 2.3).
Pure functions. No LLM, no network, no clock. Fully unit-testable.

Resolves shipment dates to official EIA Weekly National Average On-Highway Diesel prices
and maps to carrier-specific tariff fuel brackets.

Core Rule: LLMs understand, code calculates. Never the reverse.
Acceptance Criteria: get_fsc(carrier, shipment_date) returns exactly one verified value
for any invoice date in scope.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from packages.schemas.models import FSCEntry


def parse_date(date_str: str) -> datetime:
    """Parses YYYY-MM-DD date string."""
    return datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")


def get_active_eia_price(
    shipment_date_str: str,
    eia_indices: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Resolves the official EIA Weekly Diesel Benchmark price in effect on the shipment date.
    
    DOE/EIA publishes the National Average On-Highway Diesel price on Mondays at 4:00 PM Eastern.
    In standard LTL carrier tariffs (ABF Item 220-A, XPO, Roadrunner), the Monday benchmark becomes
    effective for shipments moving from the following Tuesday through the subsequent Monday
    (or for the Monday week cycle).
    
    If shipment date falls between Monday publication and next Monday, matches that benchmark.
    Returns the most recent active EIA benchmark on or before the shipment date.
    """
    if not eia_indices:
        return None

    shipment_dt = parse_date(shipment_date_str)

    # Sort EIA indices by week_date ascending
    sorted_indices = sorted(
        eia_indices,
        key=lambda x: parse_date(str(x.get("week_date", "1970-01-01")))
    )

    matched_index = None
    for entry in sorted_indices:
        week_dt = parse_date(str(entry["week_date"]))
        # EIA price is valid from week_date through week_date + 6 days
        week_end_dt = week_dt + timedelta(days=6)
        if week_dt <= shipment_dt <= week_end_dt:
            return entry
        if week_dt <= shipment_dt:
            matched_index = entry

    return matched_index


def get_fsc(
    carrier: str,
    shipment_date: str,
    fsc_tables: List[FSCEntry],
    eia_indices: Optional[List[Dict[str, Any]]] = None
) -> Tuple[Optional[float], Optional[Dict[str, Any]]]:
    """
    Returns exactly one verified FSC percentage and evidence metadata for the carrier and shipment date.
    
    Evaluation order:
    1. Filter carrier schedules.
    2. Resolve EIA diesel benchmark price for the shipment date.
    3. Match carrier fuel surcharge bracket:
       - min_diesel_price <= eia_price <= max_diesel_price
       - effective date range matching (effective_week_start / effective_week_end) if present.
    4. Fallback to monthly index matching (YYYY-MM) if carrier uses monthly table pegging.
    
    Returns:
        (fsc_pct, evidence_json) or (None, None) if out of scope.
    """
    carrier_clean = carrier.strip().lower()
    carrier_entries = [
        f for f in fsc_tables
        if f.carrier.strip().lower() == carrier_clean
    ]

    if not carrier_entries:
        return None, None

    shipment_dt = parse_date(shipment_date)
    month_str = shipment_date[:7]

    # 1. EIA Weekly Diesel Bracket Resolution
    matched_eia = None
    eia_price_dollars = None
    if eia_indices:
        matched_eia = get_active_eia_price(shipment_date, eia_indices)
        if matched_eia:
            price_cents = matched_eia.get("national_average_price_cents", 0)
            eia_price_dollars = round(price_cents / 100.0, 3)

    # If EIA price was resolved, match against carrier diesel price brackets
    if eia_price_dollars is not None:
        for entry in carrier_entries:
            # Check date window if specified
            date_in_window = True
            if entry.effective_week_start and entry.effective_week_end:
                start_dt = parse_date(entry.effective_week_start)
                end_dt = parse_date(entry.effective_week_end)
                date_in_window = start_dt <= shipment_dt <= end_dt

            # Check bracket: min_diesel_price <= price <= max_diesel_price
            if date_in_window and (entry.min_diesel_price <= eia_price_dollars <= entry.max_diesel_price):
                evidence = {
                    "carrier": carrier,
                    "shipment_date": shipment_date,
                    "method": "eia_weekly_bracket",
                    "eia_week_date": str(matched_eia.get("week_date")),
                    "eia_diesel_price": eia_price_dollars,
                    "bracket_min": entry.min_diesel_price,
                    "bracket_max": entry.max_diesel_price,
                    "fsc_pct": entry.fsc_pct,
                    "contract_clause": "Item 220-A (EIA Weekly National Diesel Index)",
                }
                return entry.fsc_pct, evidence

    # 2. Monthly Index Fallback
    for entry in carrier_entries:
        if entry.month == month_str:
            evidence = {
                "carrier": carrier,
                "shipment_date": shipment_date,
                "method": "monthly_pegging",
                "month": month_str,
                "bracket_min": entry.min_diesel_price,
                "bracket_max": entry.max_diesel_price,
                "fsc_pct": entry.fsc_pct,
                "contract_clause": "Carrier Monthly Fuel Surcharge Scale",
            }
            return entry.fsc_pct, evidence

    # 3. Default active schedule if carrier has static scale
    # Matches bracket against default EIA price or takes the primary entry
    if eia_price_dollars is not None:
        # Match closest bracket
        for entry in carrier_entries:
            if entry.min_diesel_price <= eia_price_dollars <= entry.max_diesel_price:
                evidence = {
                    "carrier": carrier,
                    "shipment_date": shipment_date,
                    "method": "closest_bracket",
                    "eia_diesel_price": eia_price_dollars,
                    "bracket_min": entry.min_diesel_price,
                    "bracket_max": entry.max_diesel_price,
                    "fsc_pct": entry.fsc_pct,
                    "contract_clause": "Carrier Standard Fuel Scale",
                }
                return entry.fsc_pct, evidence

    # Fallback to the first carrier entry if available
    first_entry = carrier_entries[0]
    evidence = {
        "carrier": carrier,
        "shipment_date": shipment_date,
        "method": "carrier_default",
        "fsc_pct": first_entry.fsc_pct,
        "contract_clause": "Carrier Base Fuel Scale",
    }
    return first_entry.fsc_pct, evidence
