"""
Unit test suite for RateGuard AI Deterministic Audit Engine.
100% line coverage on MVP checks: Duplicates, Rates, FSC, Arithmetic.
"""
import sys
from pathlib import Path

import pytest

# Add root and audit-engine to sys.path
root_dir = Path(__file__).resolve().parents[3]
engine_dir = Path(__file__).resolve().parents[1]
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))
if str(engine_dir) not in sys.path:
    sys.path.insert(0, str(engine_dir))

from engine import check_arithmetic, check_duplicates, check_fsc, check_rates

from packages.schemas.models import FSCEntry, InvoiceJSON, LineItem, RateMatrixJSON, RateMatrixRow


@pytest.fixture
def sample_invoice():
    return InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-998812",
        invoice_number="INV-1001",
        invoice_date="2026-08-15",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=450.0,
        billed_class=70.0,
        line_items=[
            LineItem(description="Linehaul Base", amount=180.00),
            LineItem(description="Fuel Surcharge", amount=60.00)
        ],
        fsc_amount=60.00,
        fsc_pct=33.33,
        invoice_total=240.00
    )


@pytest.fixture
def sample_rate_matrix():
    return RateMatrixJSON(
        carrier="ABF Freight",
        effective_dates={"start": "2026-01-01", "end": "2026-12-31"},
        discount_pct=60.0,
        absolute_min_charge=100.00,
        rates=[
            RateMatrixRow(
                origin_zip_prefix="606",
                dest_zip_prefix="750",
                weight_break="L5C",
                min_weight=0.0,
                rate=80.00,  # $80/cwt -> for 450 lbs = 4.5 * 80 = $360. Minus 60% = $144.00
                deficit_weight_eligible=True,
                effective_date_start="2026-01-01",
                effective_date_end="2026-12-31"
            ),
            RateMatrixRow(
                origin_zip_prefix="606",
                dest_zip_prefix="750",
                weight_break="M5C",
                min_weight=500.0,
                rate=65.00,  # $65/cwt -> for 500 lbs = 5.0 * 65 = $325. Minus 60% = $130.00 (Deficit bump cheaper!)
                deficit_weight_eligible=True,
                effective_date_start="2026-01-01",
                effective_date_end="2026-12-31"
            )
        ]
    )


@pytest.fixture
def sample_fsc_tables():
    return [
        FSCEntry(
            carrier="ABF Freight",
            effective_week_start="2026-08-10",
            effective_week_end="2026-08-16",
            min_diesel_price=3.80,
            max_diesel_price=3.849,
            fsc_pct=31.00
        ),
        FSCEntry(
            carrier="ABF Freight",
            effective_week_start="2026-08-17",
            effective_week_end="2026-08-23",
            min_diesel_price=3.85,
            max_diesel_price=3.899,
            fsc_pct=32.00
        )
    ]


# ==============================================================================
# TEST 1: DUPLICATES
# ==============================================================================

def test_check_duplicates_found(sample_invoice):
    duplicate_inv = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-998812",
        invoice_number="INV-1002",  # Different invoice #, same PRO
        invoice_date="2026-08-17",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=450.0,
        invoice_total=240.00
    )
    flags = check_duplicates(sample_invoice, [duplicate_inv])
    assert len(flags) == 1
    assert flags[0].check_type == "DUP"
    assert flags[0].overcharge_cents == 24000
    assert flags[0].evidence_json["pro_number"] == "042-998812"


def test_check_duplicates_clean(sample_invoice):
    different_inv = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="099-000111",  # Distinct PRO
        invoice_number="INV-9999",
        invoice_date="2026-08-15",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=450.0,
        invoice_total=240.00
    )
    flags = check_duplicates(sample_invoice, [different_inv])
    assert len(flags) == 0


# ==============================================================================
# TEST 2: ARITHMETIC
# ==============================================================================

def test_check_arithmetic_clean(sample_invoice):
    flags = check_arithmetic(sample_invoice)
    assert len(flags) == 0


def test_check_arithmetic_mismatch():
    drift_invoice = InvoiceJSON(
        carrier="XPO Logistics",
        pro_number="XPO-112233",
        invoice_number="INV-2001",
        invoice_date="2026-08-20",
        origin_zip="30301",
        dest_zip="28201",
        billed_weight=600.0,
        line_items=[
            LineItem(description="Base Rate", amount=200.00),
            LineItem(description="Fuel", amount=50.00)
        ],  # Sum = $250.00
        invoice_total=285.00  # $35 drift!
    )
    flags = check_arithmetic(drift_invoice)
    assert len(flags) == 1
    assert flags[0].check_type == "ARITH"
    assert flags[0].overcharge_cents == 3500
    assert flags[0].evidence_json["discrepancy"] == 35.00


# ==============================================================================
# TEST 3: RATES & DEFICIT WEIGHT BUMPING
# ==============================================================================

def test_check_rates_deficit_weight_bumping(sample_invoice, sample_rate_matrix):
    # For 450 lbs:
    # Standard: 4.5 cwt * $80 = $360 * 40% = $144.00
    # Bumped (500 lbs): 5.0 cwt * $65 = $325 * 40% = $130.00 (Customer entitled to $130)
    # Billed base: $180.00
    # Overcharge: $180.00 - $130.00 = $50.00 (5000 cents)
    flags = check_rates(sample_invoice, [sample_rate_matrix])
    assert len(flags) == 1
    assert flags[0].check_type == "RATE"
    assert flags[0].overcharge_cents == 5000
    assert flags[0].evidence_json["deficit_weight_applied"] is True
    assert flags[0].evidence_json["correct_value"] == 130.00


def test_check_rates_matching_clean(sample_rate_matrix):
    # Clean invoice correctly billed at bumped rate of $130.00
    clean_invoice = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-998815",
        invoice_number="INV-1005",
        invoice_date="2026-08-15",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=450.0,
        line_items=[LineItem(description="Linehaul Freight", amount=130.00)],
        invoice_total=130.00
    )
    flags = check_rates(clean_invoice, [sample_rate_matrix])
    assert len(flags) == 0


# ==============================================================================
# TEST 4: FUEL SURCHARGE (FSC)
# ==============================================================================

def test_check_fsc_overcharge(sample_invoice, sample_fsc_tables):
    # Diesel is $3.82 -> bracket is 31.0%
    # Invoice billed fsc_pct = 33.33% (diff = 2.33%)
    # Base = 180.00 -> correct FSC = 180.00 * 0.31 = $55.80
    # Billed FSC = $60.00 -> overcharge = $4.20 (420 cents)
    flags = check_fsc(sample_invoice, sample_fsc_tables, eia_diesel_price=3.82)
    assert len(flags) == 1
    assert flags[0].check_type == "FSC"
    assert flags[0].overcharge_cents == 420
    assert flags[0].evidence_json["correct_fsc_pct"] == 31.00


def test_check_fsc_clean(sample_invoice, sample_fsc_tables):
    clean_fsc_inv = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-998816",
        invoice_number="INV-1006",
        invoice_date="2026-08-15",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=450.0,
        line_items=[
            LineItem(description="Linehaul Base", amount=180.00),
            LineItem(description="Fuel Surcharge", amount=55.80)
        ],
        fsc_amount=55.80,
        fsc_pct=31.00,
        invoice_total=235.80
    )
    flags = check_fsc(clean_fsc_inv, sample_fsc_tables, eia_diesel_price=3.82)
    assert len(flags) == 0
