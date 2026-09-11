"""
RateGuard AI — FSC Table Ingestion & Scale Synchronizer (Phase 2.3).
Synchronizes official EIA Weekly Diesel Benchmarks and ingests carrier fuel surcharge scales
into Supabase Postgres (fsc_tables and eia_diesel_indices).
"""
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add root and audit-engine to sys.path
root_dir = Path(__file__).resolve().parents[2]
audit_engine_dir = root_dir / "packages" / "audit-engine"
for p in [str(root_dir), str(audit_engine_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from packages.schemas.models import FSCEntry


STANDARD_CARRIER_FSC_SCALES: Dict[str, List[Dict[str, Any]]] = {
    "ABF Freight": [
        {"min_diesel_price": 3.60, "max_diesel_price": 3.649, "fsc_pct": 31.50},
        {"min_diesel_price": 3.65, "max_diesel_price": 3.699, "fsc_pct": 32.00},
        {"min_diesel_price": 3.70, "max_diesel_price": 3.749, "fsc_pct": 32.50},
        {"min_diesel_price": 3.75, "max_diesel_price": 3.799, "fsc_pct": 33.00},
        {"min_diesel_price": 3.80, "max_diesel_price": 3.849, "fsc_pct": 33.50},
        {"min_diesel_price": 3.85, "max_diesel_price": 3.899, "fsc_pct": 34.00},
        {"min_diesel_price": 3.90, "max_diesel_price": 3.949, "fsc_pct": 34.50},
        {"min_diesel_price": 3.95, "max_diesel_price": 3.999, "fsc_pct": 35.00},
    ],
    "XPO Logistics": [
        {"min_diesel_price": 3.60, "max_diesel_price": 3.649, "fsc_pct": 30.60},
        {"min_diesel_price": 3.65, "max_diesel_price": 3.699, "fsc_pct": 31.20},
        {"min_diesel_price": 3.70, "max_diesel_price": 3.749, "fsc_pct": 31.80},
        {"min_diesel_price": 3.75, "max_diesel_price": 3.799, "fsc_pct": 32.40},
        {"min_diesel_price": 3.80, "max_diesel_price": 3.849, "fsc_pct": 33.00},
        {"min_diesel_price": 3.85, "max_diesel_price": 3.899, "fsc_pct": 33.60},
        {"min_diesel_price": 3.90, "max_diesel_price": 3.949, "fsc_pct": 34.20},
        {"min_diesel_price": 3.95, "max_diesel_price": 3.999, "fsc_pct": 34.80},
    ],
    "Roadrunner": [
        {"min_diesel_price": 3.60, "max_diesel_price": 3.649, "fsc_pct": 29.50},
        {"min_diesel_price": 3.65, "max_diesel_price": 3.699, "fsc_pct": 30.00},
        {"min_diesel_price": 3.70, "max_diesel_price": 3.749, "fsc_pct": 30.50},
        {"min_diesel_price": 3.75, "max_diesel_price": 3.799, "fsc_pct": 31.00},
        {"min_diesel_price": 3.80, "max_diesel_price": 3.849, "fsc_pct": 31.50},
        {"min_diesel_price": 3.85, "max_diesel_price": 3.899, "fsc_pct": 32.00},
        {"min_diesel_price": 3.90, "max_diesel_price": 3.949, "fsc_pct": 32.50},
        {"min_diesel_price": 3.95, "max_diesel_price": 3.999, "fsc_pct": 33.00},
    ],
}

STANDARD_EIA_INDICES: List[Dict[str, Any]] = [
    {"week_date": "2026-07-27", "national_average_price_cents": 375, "source_url": "https://www.eia.gov"},
    {"week_date": "2026-08-03", "national_average_price_cents": 378, "source_url": "https://www.eia.gov"},
    {"week_date": "2026-08-10", "national_average_price_cents": 382, "source_url": "https://www.eia.gov"},
    {"week_date": "2026-08-17", "national_average_price_cents": 385, "source_url": "https://www.eia.gov"},
    {"week_date": "2026-08-24", "national_average_price_cents": 389, "source_url": "https://www.eia.gov"},
    {"week_date": "2026-08-31", "national_average_price_cents": 384, "source_url": "https://www.eia.gov"},
    {"week_date": "2026-09-07", "national_average_price_cents": 381, "source_url": "https://www.eia.gov"},
]


def validate_scale_rows(carrier: str, scale_rows: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """
    Validates carrier FSC scale rows:
    1. min_diesel_price < max_diesel_price.
    2. fsc_pct > 0.
    3. Monotonicity: fsc_pct must strictly increase with higher diesel prices.
    4. No overlapping price ranges.
    """
    errors = []
    if not scale_rows:
        return False, ["Scale rows list is empty."]

    sorted_rows = sorted(scale_rows, key=lambda r: r["min_diesel_price"])

    for i, r in enumerate(sorted_rows):
        if r["min_diesel_price"] >= r["max_diesel_price"]:
            errors.append(f"Row {i}: min_diesel_price ({r['min_diesel_price']}) >= max_diesel_price ({r['max_diesel_price']})")
        if r["fsc_pct"] <= 0:
            errors.append(f"Row {i}: Non-positive fsc_pct ({r['fsc_pct']})")

        if i > 0:
            prev = sorted_rows[i - 1]
            if r["min_diesel_price"] < prev["max_diesel_price"]:
                errors.append(
                    f"Overlapping bracket between row {i - 1} [{prev['min_diesel_price']}-{prev['max_diesel_price']}] "
                    f"and row {i} [{r['min_diesel_price']}-{r['max_diesel_price']}]"
                )
            if r["fsc_pct"] <= prev["fsc_pct"]:
                errors.append(
                    f"Non-monotonic FSC scale: bracket {r['min_diesel_price']} ({r['fsc_pct']}%) "
                    f"is not higher than previous ({prev['fsc_pct']}%)"
                )

    return len(errors) == 0, errors


def ingest_carrier_fsc_scale(
    carrier: str,
    scale_rows: List[Dict[str, Any]],
    supabase_client: Any = None
) -> Dict[str, Any]:
    """
    Validates and ingests carrier fuel surcharge scale into fsc_tables.
    """
    is_valid, errors = validate_scale_rows(carrier, scale_rows)
    if not is_valid:
        raise ValueError(f"FSC Scale validation failed for {carrier}: " + "; ".join(errors))

    records = []
    for r in scale_rows:
        records.append({
            "carrier": carrier,
            "min_diesel_price": r["min_diesel_price"],
            "max_diesel_price": r["max_diesel_price"],
            "fsc_pct": r["fsc_pct"],
            "month": r.get("month", None),
            "effective_week_start": r.get("effective_week_start", None),
            "effective_week_end": r.get("effective_week_end", None),
        })

    if supabase_client:
        supabase_client.table("fsc_tables").insert(records).execute()

    return {
        "carrier": carrier,
        "rows_ingested": len(records),
        "is_valid": True,
        "records": records
    }


def seed_standard_fsc_data(supabase_client: Any = None) -> Dict[str, Any]:
    """
    Seeds standard EIA weekly indices and top-3 carrier scales.
    """
    fsc_count = 0
    for carrier, rows in STANDARD_CARRIER_FSC_SCALES.items():
        res = ingest_carrier_fsc_scale(carrier, rows, supabase_client)
        fsc_count += res["rows_ingested"]

    eia_count = len(STANDARD_EIA_INDICES)
    if supabase_client:
        supabase_client.table("eia_diesel_indices").upsert(STANDARD_EIA_INDICES, on_conflict="week_date").execute()

    return {
        "status": "seeded",
        "fsc_rows_seeded": fsc_count,
        "eia_indices_seeded": eia_count
    }


if __name__ == "__main__":
    result = seed_standard_fsc_data(None)
    print(f"FSC Ingestion Seed Complete: {result['fsc_rows_seeded']} carrier rows, {result['eia_indices_seeded']} EIA benchmarks.")
