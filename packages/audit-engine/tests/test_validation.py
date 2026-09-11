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

from validation import (
    evaluate_spot_verification,
    generate_spot_check_sample,
    validate_contract_matrix,
    validate_invoice_extraction,
    validate_rejection_reason_code,
)
from packages.schemas.models import (
    Accessorial,
    FSCEntry,
    InvoiceJSON,
    LineItem,
    RateMatrixJSON,
    RateMatrixRow,
    SpotCheckItem,
    SpotVerificationResult,
)



# ==============================================================================
# Phase 2.0.1: Extraction Self-Validation Tests
# ==============================================================================

def test_validate_invoice_extraction_clean():
    """A mathematically clean and fully formed invoice should achieve 1.0 confidence and pass validation."""
    invoice = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-9988112",
        invoice_number="ABF-2026-901",
        invoice_date="2026-08-15",
        origin_zip="60601",
        dest_zip="48201",
        billed_weight=1250.0,
        billed_class=70.0,
        line_items=[
            LineItem(description="Linehaul Base Freight", charge_code="400", amount=350.00),
            LineItem(description="Fuel Surcharge (33.5%)", charge_code="FSC", amount=117.25),
            LineItem(description="Liftgate Delivery", charge_code="LGT", amount=75.00),
        ],
        accessorials=[
            Accessorial(type="liftgate", amount=75.00, authorized=True)
        ],
        fsc_amount=117.25,
        fsc_pct=33.5,
        invoice_total=542.25,
    )

    result = validate_invoice_extraction(invoice)
    assert result.is_valid is True
    assert result.composite_confidence >= 0.95
    assert result.needs_calibration_queue is False
    assert result.arithmetic_sum_match is True
    assert result.linehaul_fsc_accessorial_match is True
    assert len(result.reconciliation_notes) == 0


def test_validate_invoice_extraction_arithmetic_mismatch():
    """Invoice where sum of line items does not equal total billed must drop confidence and route to calibration queue."""
    invoice = InvoiceJSON(
        carrier="XPO Logistics",
        pro_number="XPO-774411",
        invoice_number="XPO-INV-102",
        invoice_date="2026-08-10",
        origin_zip="30301",
        dest_zip="75201",
        billed_weight=2400.0,
        billed_class=85.0,
        line_items=[
            LineItem(description="Base Freight", charge_code="LH", amount=400.00),
            LineItem(description="Fuel Surcharge", charge_code="FSC", amount=132.00),
        ],
        invoice_total=650.00,  # Sum is 532.00, $118 mismatch!
    )

    result = validate_invoice_extraction(invoice)
    assert result.is_valid is False
    assert result.arithmetic_sum_match is False
    assert result.needs_calibration_queue is True
    assert result.composite_confidence < 0.80
    assert any("differs from invoice_total" in n for n in result.reconciliation_notes)


def test_validate_invoice_extraction_rounding_tolerance():
    """Penny rounding differences within tolerance should pass arithmetic validation."""
    invoice = InvoiceJSON(
        carrier="Roadrunner",
        pro_number="RR-889922",
        invoice_number="RR-INV-44",
        invoice_date="2026-08-20",
        origin_zip="90001",
        dest_zip="85001",
        billed_weight=800.0,
        line_items=[
            LineItem(description="Base Freight", amount=200.00),
            LineItem(description="Fuel Surcharge", amount=65.33),
        ],
        invoice_total=265.34,  # $0.01 rounding discrepancy
    )

    result = validate_invoice_extraction(invoice, rounding_tolerance=0.02)
    assert result.arithmetic_sum_match is True
    assert result.is_valid is True
    assert result.needs_calibration_queue is False


def test_validate_invoice_extraction_malformed_headers():
    """Missing or invalid headers (malformed dates, short zips, missing carrier) must penalize confidence."""
    invoice = InvoiceJSON(
        carrier="X",  # Carrier name too short (<2 chars)
        pro_number="",  # Empty PRO
        invoice_number="1",
        invoice_date="Aug 15 2026",  # Invalid date format
        origin_zip="1",  # Invalid zip (<3 chars)
        dest_zip="2",
        billed_weight=0.0,  # Zero weight (penalized by validation layer)
        line_items=[
            LineItem(description="Base Freight", amount=100.00),
        ],
        invoice_total=100.00,
    )

    result = validate_invoice_extraction(invoice)
    assert result.is_valid is False
    assert result.needs_calibration_queue is True
    assert result.composite_confidence <= 0.65



# ==============================================================================
# Phase 2.0.2: Contract Sanity Suite Tests
# ==============================================================================

@pytest.fixture
def clean_rate_matrix():
    """Returns a well-formed RateMatrixJSON for ABF."""
    return RateMatrixJSON(
        carrier="ABF Freight",
        contract_id="cntr-abf-2026",
        effective_dates={"start": "2026-01-01", "end": "2026-12-31"},
        discount_pct=65.0,
        absolute_min_charge=85.00,
        rates=[
            RateMatrixRow(
                origin_zip_prefix="606",
                dest_zip_prefix="482",
                weight_break="L5C",
                min_weight=0.0,
                rate=42.50,
                min_charge=85.00,
                effective_date_start="2026-01-01",
                effective_date_end="2026-12-31",
            ),
            RateMatrixRow(
                origin_zip_prefix="606",
                dest_zip_prefix="482",
                weight_break="M5C",
                min_weight=500.0,
                rate=38.00,
                min_charge=85.00,
                effective_date_start="2026-01-01",
                effective_date_end="2026-12-31",
            ),
            RateMatrixRow(
                origin_zip_prefix="606",
                dest_zip_prefix="482",
                weight_break="M1M",
                min_weight=1000.0,
                rate=32.00,
                min_charge=85.00,
                effective_date_start="2026-01-01",
                effective_date_end="2026-12-31",
            ),
            RateMatrixRow(
                origin_zip_prefix="606",
                dest_zip_prefix="482",
                weight_break="M2M",
                min_weight=2000.0,
                rate=28.00,
                min_charge=85.00,
                effective_date_start="2026-01-01",
                effective_date_end="2026-12-31",
            ),
            RateMatrixRow(
                origin_zip_prefix="606",
                dest_zip_prefix="482",
                weight_break="M5M",
                min_weight=5000.0,
                rate=22.00,
                min_charge=85.00,
                effective_date_start="2026-01-01",
                effective_date_end="2026-12-31",
            ),
        ]
    )


def test_validate_contract_matrix_clean(clean_rate_matrix):
    """Clean matrix with monotonic rates should pass all sanity checks."""
    result = validate_contract_matrix(clean_rate_matrix)
    assert result.is_valid is True
    assert result.status == "valid"
    assert len(result.issues) == 0
    assert len(result.spot_checks) == 5
    assert result.contract_validation_json["is_valid"] is True


def test_validate_contract_matrix_duplicate_lanes(clean_rate_matrix):
    """Duplicate lane entries with identical break and dates must be flagged."""
    # Duplicate the L5C row
    clean_rate_matrix.rates.append(clean_rate_matrix.rates[0])

    result = validate_contract_matrix(clean_rate_matrix)
    assert result.is_valid is False
    assert result.status == "rejected"
    dup_issues = [i for i in result.issues if i.issue_type == "duplicate_lane"]
    assert len(dup_issues) == 1
    assert "Duplicate matrix row detected" in dup_issues[0].message


def test_validate_contract_matrix_monotonicity_violation(clean_rate_matrix):
    """Non-monotonic rate where higher weight break is charged higher $/cwt must be flagged as an error."""
    # Modify M1M (1000 lbs) rate to be $45.00, higher than M5C ($38.00)
    clean_rate_matrix.rates[2].rate = 45.00

    result = validate_contract_matrix(clean_rate_matrix)
    assert result.is_valid is False
    assert result.status == "rejected"
    mono_issues = [i for i in result.issues if i.issue_type == "monotonicity_violation"]
    assert len(mono_issues) >= 1
    assert "Non-monotonic rate" in mono_issues[0].message


def test_validate_contract_matrix_overlapping_breaks(clean_rate_matrix):
    """Identical min_weights in the same lane must be flagged as overlapping breaks."""
    clean_rate_matrix.rates[1].min_weight = 0.0  # Same as L5C

    result = validate_contract_matrix(clean_rate_matrix)
    assert result.is_valid is False
    overlap_issues = [i for i in result.issues if i.issue_type == "overlapping_breaks"]
    assert len(overlap_issues) == 1


def test_validate_contract_matrix_fsc_coverage(clean_rate_matrix):
    """Missing FSC coverage for required audit months must be flagged."""
    fsc_tables = [
        FSCEntry(carrier="ABF Freight", month="2026-06", min_diesel_price=3.5, max_diesel_price=4.0, fsc_pct=31.0),
        FSCEntry(carrier="ABF Freight", month="2026-07", min_diesel_price=3.5, max_diesel_price=4.0, fsc_pct=32.0),
    ]
    required_months = ["2026-06", "2026-07", "2026-08"]  # August is missing

    result = validate_contract_matrix(clean_rate_matrix, fsc_tables=fsc_tables, in_scope_months=required_months)
    assert result.is_valid is False
    fsc_issues = [i for i in result.issues if i.issue_type == "missing_fsc_month"]
    assert len(fsc_issues) == 1
    assert fsc_issues[0].details["missing_month"] == "2026-08"


# ==============================================================================
# Spot Verification Protocol Tests
# ==============================================================================

def test_generate_and_evaluate_spot_verification_success(clean_rate_matrix):
    """5/5 spot checks matching must result in successful contract spot verification."""
    samples = generate_spot_check_sample(clean_rate_matrix, n=5, seed=42)
    assert len(samples) == 5

    user_verifications = [
        SpotVerificationResult(sample_index=item.sample_index, matched=True, actual_page_rate=item.matrix_rate)
        for item in samples
    ]

    passed, message = evaluate_spot_verification(samples, user_verifications)
    assert passed is True
    assert "5/5 match" in message


def test_evaluate_spot_verification_failure(clean_rate_matrix):
    """Even 1 mismatch in the N=5 spot check must reject the contract matrix."""
    samples = generate_spot_check_sample(clean_rate_matrix, n=5, seed=42)

    user_verifications = [
        SpotVerificationResult(sample_index=samples[0].sample_index, matched=True, actual_page_rate=samples[0].matrix_rate),
        SpotVerificationResult(sample_index=samples[1].sample_index, matched=False, actual_page_rate=99.00),  # Mismatch!
        SpotVerificationResult(sample_index=samples[2].sample_index, matched=True, actual_page_rate=samples[2].matrix_rate),
        SpotVerificationResult(sample_index=samples[3].sample_index, matched=True, actual_page_rate=samples[3].matrix_rate),
        SpotVerificationResult(sample_index=samples[4].sample_index, matched=True, actual_page_rate=samples[4].matrix_rate),
    ]

    passed, message = evaluate_spot_verification(samples, user_verifications)
    assert passed is False
    assert "Spot check failed" in message
    assert "Matrix has" in message


# ==============================================================================
# Phase 2.0.4: Reason-Code Taxonomy Enforcement Tests
# ==============================================================================

def test_validate_rejection_reason_code():
    """Ensures only standardized v1 taxonomy codes are accepted."""
    valid_codes = [
        "wrong-matrix-row",
        "misread-pdf-field",
        "contract-exception-misapplied",
        "not-an-error",
        "duplicate-false-positive",
        "fsc-table-wrong-month",
        "rate-effective-date-mismatch",
        "other",
    ]
    for code in valid_codes:
        assert validate_rejection_reason_code(code) is True

    invalid_codes = [
        "carrier-argued",
        "random-guess",
        "unknown",
        "not-sure",
        "",
    ]
    for code in invalid_codes:
        assert validate_rejection_reason_code(code) is False
