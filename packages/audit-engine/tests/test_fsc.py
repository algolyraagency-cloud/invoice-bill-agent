"""
Unit tests for RateGuard AI Deterministic Fuel Surcharge (FSC) Engine (Phase 2.3).
Validates EIA weekly index resolution, carrier bracket mapping, monthly fallback,
and scale monotonicity validation.
"""
import sys
from pathlib import Path
import pytest

root_dir = Path(__file__).resolve().parents[3]
engine_dir = root_dir / "packages" / "audit-engine"
worker_dir = root_dir / "apps" / "worker"
for p in [str(root_dir), str(engine_dir), str(worker_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from fsc import get_active_eia_price, get_fsc
from fsc_ingestion import (
    STANDARD_CARRIER_FSC_SCALES,
    STANDARD_EIA_INDICES,
    ingest_carrier_fsc_scale,
    validate_scale_rows,
)
from packages.schemas.models import FSCEntry


@pytest.fixture
def abf_fsc_tables():
    return [FSCEntry(carrier="ABF Freight", **row) for row in STANDARD_CARRIER_FSC_SCALES["ABF Freight"]]


@pytest.fixture
def xpo_fsc_tables():
    return [FSCEntry(carrier="XPO Logistics", **row) for row in STANDARD_CARRIER_FSC_SCALES["XPO Logistics"]]


@pytest.fixture
def roadrunner_fsc_tables():
    return [FSCEntry(carrier="Roadrunner", **row) for row in STANDARD_CARRIER_FSC_SCALES["Roadrunner"]]


def test_get_active_eia_price_resolution():
    """Resolves shipment date to active DOE/EIA Monday benchmark."""
    # Monday 2026-08-10 benchmark is $3.82
    # Tuesday 2026-08-11 shipment should match 2026-08-10 index
    idx = get_active_eia_price("2026-08-11", STANDARD_EIA_INDICES)
    assert idx is not None
    assert idx["week_date"] == "2026-08-10"
    assert idx["national_average_price_cents"] == 382

    # Friday 2026-08-14 shipment should also match 2026-08-10 index
    idx2 = get_active_eia_price("2026-08-14", STANDARD_EIA_INDICES)
    assert idx2 is not None
    assert idx2["week_date"] == "2026-08-10"

    # Next Monday 2026-08-17 benchmark is $3.85
    idx3 = get_active_eia_price("2026-08-18", STANDARD_EIA_INDICES)
    assert idx3 is not None
    assert idx3["week_date"] == "2026-08-17"
    assert idx3["national_average_price_cents"] == 385


def test_get_fsc_abf_weekly_bracket(abf_fsc_tables):
    """
    On 2026-08-18, EIA diesel average is $3.85/gal.
    ABF bracket for $3.85-$3.899 is 34.00%.
    """
    fsc_pct, evidence = get_fsc(
        carrier="ABF Freight",
        shipment_date="2026-08-18",
        fsc_tables=abf_fsc_tables,
        eia_indices=STANDARD_EIA_INDICES
    )

    assert fsc_pct == 34.00
    assert evidence is not None
    assert evidence["method"] == "eia_weekly_bracket"
    assert evidence["eia_diesel_price"] == 3.85
    assert evidence["bracket_min"] == 3.85
    assert evidence["bracket_max"] == 3.899


def test_get_fsc_xpo_weekly_bracket(xpo_fsc_tables):
    """
    On 2026-08-12, EIA diesel average is $3.82/gal.
    XPO bracket for $3.80-$3.849 is 33.00%.
    """
    fsc_pct, evidence = get_fsc(
        carrier="XPO Logistics",
        shipment_date="2026-08-12",
        fsc_tables=xpo_fsc_tables,
        eia_indices=STANDARD_EIA_INDICES
    )

    assert fsc_pct == 33.00
    assert evidence["eia_diesel_price"] == 3.82
    assert evidence["bracket_min"] == 3.80
    assert evidence["bracket_max"] == 3.849


def test_get_fsc_roadrunner_weekly_bracket(roadrunner_fsc_tables):
    """
    On 2026-08-05, EIA diesel average is $3.78/gal.
    Roadrunner bracket for $3.75-$3.799 is 31.00%.
    """
    fsc_pct, evidence = get_fsc(
        carrier="Roadrunner",
        shipment_date="2026-08-05",
        fsc_tables=roadrunner_fsc_tables,
        eia_indices=STANDARD_EIA_INDICES
    )

    assert fsc_pct == 31.00
    assert evidence["eia_diesel_price"] == 3.78


def test_get_fsc_monthly_pegging_fallback():
    """Fallback to monthly table matching if EIA index not provided."""
    monthly_tables = [
        FSCEntry(carrier="ABF Freight", month="2026-08", min_diesel_price=3.5, max_diesel_price=4.0, fsc_pct=33.5),
        FSCEntry(carrier="ABF Freight", month="2026-07", min_diesel_price=3.5, max_diesel_price=4.0, fsc_pct=32.0),
    ]

    fsc_pct, evidence = get_fsc(
        carrier="ABF Freight",
        shipment_date="2026-08-20",
        fsc_tables=monthly_tables,
        eia_indices=None
    )

    assert fsc_pct == 33.5
    assert evidence["method"] == "monthly_pegging"
    assert evidence["month"] == "2026-08"


def test_get_fsc_acceptance_single_verified_value(abf_fsc_tables, xpo_fsc_tables, roadrunner_fsc_tables):
    """
    ACCEPTANCE TEST (Phase 2.3):
    get_fsc(carrier, shipment_date) returns EXACTLY ONE verified value for any invoice date in scope.
    """
    combined_tables = abf_fsc_tables + xpo_fsc_tables + roadrunner_fsc_tables

    test_dates = [
        "2026-08-01",
        "2026-08-10",
        "2026-08-15",
        "2026-08-20",
        "2026-08-28",
        "2026-09-02",
    ]
    carriers = ["ABF Freight", "XPO Logistics", "Roadrunner"]

    for c in carriers:
        for d in test_dates:
            val, evidence = get_fsc(c, d, combined_tables, STANDARD_EIA_INDICES)
            assert val is not None, f"Failed for {c} on {d}"
            assert isinstance(val, (int, float))
            assert val > 20.0 and val < 50.0  # Normal FSC range
            assert evidence["carrier"] == c
            assert evidence["shipment_date"] == d


def test_validate_fsc_scale_monotonicity():
    """Rejects overlapping price brackets and non-monotonic scales."""
    invalid_overlap = [
        {"min_diesel_price": 3.60, "max_diesel_price": 3.70, "fsc_pct": 30.0},
        {"min_diesel_price": 3.65, "max_diesel_price": 3.80, "fsc_pct": 31.0},  # Overlap!
    ]
    is_valid, errors = validate_scale_rows("TestCarrier", invalid_overlap)
    assert is_valid is False
    assert any("Overlapping bracket" in e for e in errors)

    invalid_monotonicity = [
        {"min_diesel_price": 3.60, "max_diesel_price": 3.65, "fsc_pct": 32.0},
        {"min_diesel_price": 3.65, "max_diesel_price": 3.70, "fsc_pct": 31.0},  # Dropped!
    ]
    is_valid2, errors2 = validate_scale_rows("TestCarrier", invalid_monotonicity)
    assert is_valid2 is False
    assert any("Non-monotonic FSC scale" in e for e in errors2)
