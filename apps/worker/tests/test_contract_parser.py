"""
Unit tests for RateGuard AI Contract Parser (Phase 2.2).
Tests Quality Ladder Rungs A, B, and C, layout extraction, RateMatrixJSON parsing,
spot-check sampling, and database row materialization.
"""
import sys
from pathlib import Path
import pytest

root_dir = Path(__file__).resolve().parents[3]
worker_dir = root_dir / "apps" / "worker"
engine_dir = root_dir / "packages" / "audit-engine"
for p in [str(root_dir), str(worker_dir), str(engine_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from contract_parser import (
    _CONTRACT_PARSE_CACHE,
    parse_contract_document,
    persist_parsed_contract,
)
from packages.schemas.models import RateMatrixJSON, RateMatrixRow


def test_parse_contract_rung_a_clean():
    """Parses Rung A Clean Master Pricing Agreement with rates, AMC, and discount."""
    raw_agreement = """
    ABF FREIGHT SYSTEM — MASTER PRICING AGREEMENT #2026-FSTD
    EFFECTIVE: 2026-01-01 THROUGH 2026-12-31
    LANE: ORIGIN ZIP 606 (CHICAGO) TO DESTINATION ZIP 482 (DETROIT)
    DISCOUNT: 65.0% OFF BASE TARIFF
    ABSOLUTE MINIMUM CHARGE: $85.00
    WEIGHT BREAK MATRIX ($/CWT):
    L5C (0-499 lbs): $45.00
    M5C (500-999 lbs): $38.00
    M1M (1000-1999 lbs): $30.00
    M2M (2000-4999 lbs): $24.00
    M5M (5000+ lbs): $18.00
    Item 100: Deficit weight bumping authorized.
    """
    matrix, val_result, meta = parse_contract_document(
        raw_agreement,
        carrier_hint="ABF Freight",
        rung="A",
        use_cache=False
    )

    assert matrix.carrier == "ABF Freight"
    assert matrix.discount_pct == 65.0
    assert matrix.absolute_min_charge == 85.0
    assert len(matrix.rates) >= 5
    assert matrix.rates[0].origin_zip_prefix == "606"
    assert matrix.rates[0].dest_zip_prefix == "482"
    assert val_result.is_valid is True
    assert val_result.status == "valid"
    assert len(val_result.spot_checks) == 5
    assert meta["status"] == "valid"


def test_parse_contract_rung_b_email_digest():
    """Parses Rung B Email Chain Digest into RateMatrixJSON."""
    raw_email = """
    From: rep@xpo.com
    To: shipper@company.com
    Subject: Re: 2026 LTL Rate Agreement

    Hi team, attached is your confirmed pricing for the Chicago to Detroit lane:
    Effective: 2026-01-01
    Origin 606 to Dest 482
    AMC: $90.00
    Discount: 60.0%
    L5C: $48.00
    M5C: $40.00
    M1M: $32.00
    M2M: $26.00
    """
    matrix, val_result, meta = parse_contract_document(
        raw_email,
        carrier_hint="XPO Logistics",
        rung="B",
        use_cache=False
    )

    assert matrix.carrier == "XPO Logistics"
    assert matrix.discount_pct == 60.0
    assert matrix.absolute_min_charge == 90.0
    assert len(matrix.rates) >= 4
    assert meta["rung"] == "B"
    assert val_result.is_valid is True


def test_parse_contract_rung_c_tariff():
    """Parses Rung C Published Tariff baseline with claimed discount note."""
    raw_note = """
    Carrier: Roadrunner Freight
    Origin 900 to Dest 850
    Shipper notes: CzarLite baseline tariff with verbal 55.0% discount. AMC $80.00.
    Effective: 2026-01-01
    """
    matrix, val_result, meta = parse_contract_document(
        raw_note,
        carrier_hint="Roadrunner",
        rung="C",
        use_cache=False
    )

    assert matrix.carrier == "Roadrunner"
    assert matrix.discount_pct == 55.0
    assert matrix.absolute_min_charge == 80.0
    assert meta["rung"] == "C"
    assert any("Rung C" in ex for ex in matrix.exceptions)
    assert val_result.is_valid is True


def test_contract_parse_sha256_caching():
    """Verifies SHA-256 caching on contract documents."""
    raw_agreement = """
    ABF FREIGHT PRICING AGREEMENT
    EFFECTIVE: 2026-01-01
    ORIGIN: 606 DEST: 482
    DISCOUNT: 65.0%
    AMC: $85.00
    """
    m1, val1, meta1 = parse_contract_document(raw_agreement, carrier_hint="ABF Freight", use_cache=True)
    assert meta1["cache_hit"] is False

    m2, val2, meta2 = parse_contract_document(raw_agreement, carrier_hint="ABF Freight", use_cache=True)
    assert meta2["cache_hit"] is True
    assert m2.carrier == m1.carrier
    assert val2.status == val1.status


def test_persist_parsed_contract_materialization():
    """Verifies that persisting a contract creates payload and materializes individual lane rows."""
    matrix = RateMatrixJSON(
        carrier="ABF Freight",
        contract_id="test-cntr-001",
        effective_dates={"start": "2026-01-01", "end": "2026-12-31"},
        discount_pct=65.0,
        absolute_min_charge=85.0,
        rates=[
            RateMatrixRow(
                origin_zip_prefix="606",
                dest_zip_prefix="482",
                weight_break="L5C",
                min_weight=0.0,
                rate=45.0,
                min_charge=85.0,
                effective_date_start="2026-01-01",
                effective_date_end="2026-12-31"
            ),
            RateMatrixRow(
                origin_zip_prefix="606",
                dest_zip_prefix="482",
                weight_break="M5C",
                min_weight=500.0,
                rate=38.0,
                min_charge=85.0,
                effective_date_start="2026-01-01",
                effective_date_end="2026-12-31"
            )
        ]
    )
    from validation import validate_contract_matrix
    val = validate_contract_matrix(matrix)

    result = persist_parsed_contract(None, "test-cntr-001", matrix, val)
    assert result["contract_id"] == "test-cntr-001"
    assert result["materialized_rows_count"] == 2
    assert "rate_matrix_json" in result["contract_payload"]
    assert "contract_validation_json" in result["contract_payload"]
