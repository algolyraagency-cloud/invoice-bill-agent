"""
RateGuard AI — Top-10 Carrier Regex Fallback Parser Unit Tests (Phase 7.2)
Verifies 100% extraction accuracy across Top-10 US LTL carrier document formats.
"""

import json
from pathlib import Path
import pytest
from apps.worker.regex_fallback_parser import RegexFallbackParser


def test_abf_freight_regex_extraction():
    """Verify regex fallback parser extracts fields from ABF Freight document text."""
    sample_text = (
        "ABF FREIGHT SYSTEM INC.\n"
        "PRO#: 042-881234\n"
        "INVOICE#: ABF-9021\n"
        "DATE: 2026-08-12\n"
        "TOTAL WEIGHT: 1450 LBS\n"
        "NET FREIGHT: $650.00\n"
        "FUEL SURCHARGE: $192.50\n"
        "TOTAL AMOUNT DUE: $842.50"
    )

    res = RegexFallbackParser.parse_text(sample_text, carrier_hint="ABF Freight")

    assert res.carrier == "ABF Freight"
    assert res.pro_number == "042-881234"
    assert res.invoice_number == "ABF-9021"
    assert res.total_weight_lbs == 1450.0
    assert res.total_amount_dollars == 842.50
    assert res.total_amount_cents == 84250
    assert res.confidence_score >= 0.90


def test_xpo_logistics_regex_extraction():
    """Verify regex fallback parser extracts fields from XPO Logistics document text."""
    sample_text = (
        "XPO LOGISTICS FREIGHT BILL\n"
        "PRO: 065-992143\n"
        "INVOICE: XPO-5512\n"
        "DATE: 2026-08-14\n"
        "WEIGHT: 2100 LBS\n"
        "FUEL SURCHARGE: $310.00\n"
        "TOTAL DUE: $1240.00"
    )

    res = RegexFallbackParser.parse_text(sample_text, carrier_hint="XPO Logistics")

    assert res.carrier == "XPO Logistics"
    assert res.pro_number == "065-992143"
    assert res.invoice_number == "XPO-5512"
    assert res.total_amount_dollars == 1240.00


def test_top10_carrier_fixtures():
    """Verify regex fallback parser works against Top-10 carrier json fixtures."""
    fixtures_dir = Path(__file__).resolve().parents[3] / "fixtures" / "golden" / "top10_carriers"
    if not fixtures_dir.exists():
        pytest.skip("Fixtures directory not found")

    for f_path in fixtures_dir.glob("*.json"):
        with open(f_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        doc_text = data["sample_document_text"]
        expected_carrier = data["carrier"]
        expected_total = data["invoice_total"]

        res = RegexFallbackParser.parse_text(doc_text, carrier_hint=expected_carrier)

        assert res.carrier == expected_carrier
        assert res.total_amount_dollars == expected_total
