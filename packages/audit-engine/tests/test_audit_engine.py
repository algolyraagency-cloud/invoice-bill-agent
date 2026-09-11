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
        invoice_date="2026-08-10",  # Billed earlier (Aug 10), so sample_invoice (Aug 15) is the duplicate rebill
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


# ==============================================================================
# ADDITIONAL EDGE CASE & RIGOR TESTS (PHASE 3.1)
# ==============================================================================

def test_check_duplicates_bol_match(sample_invoice):
    """Flags duplicate when same BOL is billed under a different PRO number."""
    inv1 = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-111111",
        invoice_number="INV-101",
        invoice_date="2026-08-10",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=450.0,
        bol_number="BOL-998877",
        invoice_total=240.00
    )
    inv2 = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-222222",  # Different PRO!
        invoice_number="INV-102",
        invoice_date="2026-08-14",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=450.0,
        bol_number="BOL-998877",  # Same BOL!
        invoice_total=240.00
    )
    flags = check_duplicates(inv2, [inv1])
    assert len(flags) == 1
    assert flags[0].check_type == "DUP"
    assert flags[0].evidence_json["bol_number"] == "BOL-998877"
    assert "BOL #BOL-998877" in flags[0].evidence_json["note"]


def test_check_duplicates_amount_window_match():
    """Flags duplicate when identical amount billed on same lane within ±3 days."""
    inv1 = InvoiceJSON(
        carrier="Roadrunner",
        pro_number="RR-100",
        invoice_number="INV-R1",
        invoice_date="2026-08-10",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=300.0,
        invoice_total=185.50
    )
    inv2 = InvoiceJSON(
        carrier="Roadrunner",
        pro_number="RR-101",
        invoice_number="INV-R2",
        invoice_date="2026-08-12",  # 2 days later
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=300.0,
        invoice_total=185.50  # Identical amount!
    )
    flags = check_duplicates(inv2, [inv1])
    assert len(flags) == 1
    assert flags[0].check_type == "DUP"
    assert flags[0].overcharge_cents == 18550


def test_check_duplicates_directionality():
    """Chronological directionality: the original invoice must NEVER be flagged as duplicate."""
    inv1 = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-998812",
        invoice_number="INV-1001",
        invoice_date="2026-08-10",  # Earlier
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=450.0,
        invoice_total=240.00
    )
    inv2 = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-998812",
        invoice_number="INV-1002",
        invoice_date="2026-08-15",  # Later
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=450.0,
        invoice_total=240.00
    )
    # Auditing the earlier invoice (inv1) against the later invoice (inv2) must NOT flag inv1!
    flags_inv1 = check_duplicates(inv1, [inv2])
    assert len(flags_inv1) == 0

    # Auditing the later invoice (inv2) against inv1 MUST flag inv2
    flags_inv2 = check_duplicates(inv2, [inv1])
    assert len(flags_inv2) == 1
    assert flags_inv2[0].evidence_json["duplicate_of_invoice"] == "INV-1001"


def test_check_arithmetic_penny_tolerance():
    """Arithmetic check ignores rounding drift <= $0.02."""
    inv = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-555555",
        invoice_number="INV-P1",
        invoice_date="2026-08-15",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=400.0,
        line_items=[
            LineItem(description="Linehaul", amount=100.01),
            LineItem(description="FSC", amount=33.33)
        ],  # Sum = 133.34
        invoice_total=133.35  # Diff = $0.01 (within tolerance)
    )
    flags = check_arithmetic(inv)
    assert len(flags) == 0


def test_check_arithmetic_underbilled():
    """Underbilled invoices (carrier under-billed) should NOT produce an overcharge flag."""
    inv = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-555556",
        invoice_number="INV-P2",
        invoice_date="2026-08-15",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=400.0,
        line_items=[
            LineItem(description="Linehaul", amount=150.00),
            LineItem(description="FSC", amount=50.00)
        ],  # Sum = 200.00
        invoice_total=180.00  # Total billed is less than line items
    )
    flags = check_arithmetic(inv)
    assert len(flags) == 0


def test_check_rates_5digit_preference():
    """A 5-digit zip match takes precedence over a 3-digit zip prefix."""
    matrix = RateMatrixJSON(
        carrier="XPO Logistics",
        effective_dates={"start": "2026-01-01", "end": "2026-12-31"},
        discount_pct=50.0,
        absolute_min_charge=75.00,
        rates=[
            # 3-digit lane: $100/cwt
            RateMatrixRow(
                origin_zip_prefix="606",
                dest_zip_prefix="750",
                weight_break="L5C",
                min_weight=0.0,
                rate=100.00,
                effective_date_start="2026-01-01",
                effective_date_end="2026-12-31"
            ),
            # Specific 5-digit lane: $70/cwt (Specific lane discount)
            RateMatrixRow(
                origin_zip_prefix="60601",
                dest_zip_prefix="75001",
                weight_break="L5C",
                min_weight=0.0,
                rate=70.00,
                effective_date_start="2026-01-01",
                effective_date_end="2026-12-31"
            )
        ]
    )
    # For 400 lbs: 4.0 cwt * $70 = $280 * 50% = $140.00
    # Carrier billed 3-digit rate ($100 * 4.0 * 50% = $200.00)
    inv = InvoiceJSON(
        carrier="XPO Logistics",
        pro_number="XPO-777",
        invoice_number="INV-X7",
        invoice_date="2026-08-15",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=400.0,
        line_items=[LineItem(description="Linehaul Base", amount=200.00)],
        invoice_total=200.00
    )
    flags = check_rates(inv, [matrix])
    assert len(flags) == 1
    assert flags[0].check_type == "RATE"
    assert flags[0].evidence_json["correct_value"] == 140.00
    assert flags[0].overcharge_cents == 6000


def test_check_rates_amc_floor(sample_rate_matrix):
    """Absolute Minimum Charge floor is respected when discounted rate falls below AMC."""
    # sample_rate_matrix has AMC = $100.00
    # For small 50 lbs shipment: 0.5 cwt * $80 = $40 * 40% = $16.00 -> AMC raises to $100.00
    # If carrier bills $135.00, overcharge is $135 - $100 = $35.00
    inv = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-AMC01",
        invoice_number="INV-AMC1",
        invoice_date="2026-08-15",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=50.0,
        line_items=[LineItem(description="Linehaul Base", amount=135.00)],
        invoice_total=135.00
    )
    flags = check_rates(inv, [sample_rate_matrix])
    assert len(flags) == 1
    assert flags[0].check_type == "RATE"
    assert flags[0].evidence_json["correct_value"] == 100.00
    assert flags[0].overcharge_cents == 3500


def test_check_rates_effective_date_windowing():
    """Applies correct matrix version based on invoice date."""
    matrix_v1 = RateMatrixJSON(
        carrier="ABF Freight",
        effective_dates={"start": "2026-01-01", "end": "2026-06-30"},
        discount_pct=50.0,
        rates=[
            RateMatrixRow(
                origin_zip_prefix="606",
                dest_zip_prefix="750",
                weight_break="L5C",
                min_weight=0.0,
                rate=60.00,
                effective_date_start="2026-01-01",
                effective_date_end="2026-06-30"
            )
        ]
    )
    matrix_v2 = RateMatrixJSON(
        carrier="ABF Freight",
        effective_dates={"start": "2026-07-01", "end": "2026-12-31"},
        discount_pct=50.0,
        rates=[
            RateMatrixRow(
                origin_zip_prefix="606",
                dest_zip_prefix="750",
                weight_break="L5C",
                min_weight=0.0,
                rate=70.00,  # GRI price hike in July
                effective_date_start="2026-07-01",
                effective_date_end="2026-12-31"
            )
        ]
    )
    # Shipment in May 2026 -> should evaluate against matrix_v1 ($60 * 3.0 * 50% = $90)
    inv_may = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-MAY",
        invoice_number="INV-MAY",
        invoice_date="2026-05-15",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=300.0,
        line_items=[LineItem(description="Linehaul Base", amount=105.00)],  # Billed $105 (v2 rate without discount)
        invoice_total=105.00
    )
    flags = check_rates(inv_may, [matrix_v1, matrix_v2])
    assert len(flags) == 1
    assert flags[0].evidence_json["correct_value"] == 90.00


def test_check_fsc_on_net_freight_excluding_accessorials(sample_fsc_tables):
    """FSC should only be calculated on Net Linehaul, not on accessorial charges (e.g. Liftgate)."""
    # Net linehaul = $200.00, Liftgate = $75.00. Total = $275.00 + FSC
    # Carrier billed 31% FSC on $275.00 ($85.25) instead of 31% on $200.00 ($62.00)
    # Overcharge: $85.25 - $62.00 = $23.25
    inv = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-FSC-ACC",
        invoice_number="INV-FSC-ACC",
        invoice_date="2026-08-15",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=400.0,
        line_items=[
            LineItem(description="Linehaul Freight", amount=200.00),
            LineItem(description="Liftgate Service", amount=75.00),
            LineItem(description="Fuel Surcharge", amount=85.25)
        ],
        accessorials=[
            {"type": "liftgate", "amount": 75.00, "authorized": True}
        ],
        fsc_amount=85.25,
        fsc_pct=31.00,
        invoice_total=360.25
    )
    flags = check_fsc(inv, sample_fsc_tables, eia_diesel_price=3.82)
    assert len(flags) == 1
    assert flags[0].check_type == "FSC"
    assert flags[0].evidence_json["correct_value"] == 62.00
    assert flags[0].overcharge_cents == 2325

