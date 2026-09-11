"""
Unit tests for RateGuard AI Invoice Parser (Phase 2.1).
Tests layout extraction, Instructor structured output, carrier hints,
SHA-256 parse caching, and Phase 2.0 self-validation integration.
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

from invoice_parser import (
    _INVOICE_PARSE_CACHE,
    parse_invoice_document,
    persist_parsed_invoice,
)
from packages.schemas.models import InvoiceJSON


def test_parse_abf_invoice_text():
    """Extracts ABF Freight invoice accurately with carrier hints."""
    raw_doc = """
    ABF FREIGHT SYSTEM, INC.
    INVOICE #: INV-ABF-88991
    PRO NUMBER: 042-8877112
    DATE: 2026-08-14
    ORIGIN: Chicago, IL 60601
    DESTINATION: Detroit, MI 48201
    BILLED WEIGHT: 1450 LBS
    CLASS: 70
    CHARGES:
    Linehaul Freight: $165.00
    Fuel Surcharge (33.5%): $55.28
    TOTAL AMOUNT DUE: $220.28
    """
    invoice, val_result, meta = parse_invoice_document(raw_doc, carrier_hint="ABF Freight", use_cache=False)

    assert invoice.carrier == "ABF Freight"
    assert invoice.pro_number == "042-8877112"
    assert invoice.invoice_number == "INV-ABF-88991"
    assert invoice.origin_zip == "60601"
    assert invoice.dest_zip == "48201"
    assert invoice.invoice_total == 220.28
    assert invoice.billed_weight == 1450.0
    assert val_result.is_valid is True
    assert val_result.composite_confidence >= 0.90
    assert val_result.arithmetic_sum_match is True
    assert meta["status"] == "parsed"


def test_parse_xpo_invoice_with_accessorial():
    """Extracts XPO Logistics invoice with liftgate accessorial."""
    raw_doc = """
    XPO LOGISTICS FREIGHT, INC.
    INVOICE NUMBER: XPO-99120
    PRO: 781-5500112
    DATE: 2026-08-16
    SHIP FROM: Atlanta, GA 30301
    SHIP TO: Dallas, TX 75201
    ACTUAL WEIGHT: 2200 LBS
    BILLED WEIGHT: 2200 LBS
    Linehaul: $240.00
    Fuel Surcharge: $79.20
    Liftgate: $75.00
    TOTAL: $394.20
    """
    invoice, val_result, meta = parse_invoice_document(raw_doc, carrier_hint="XPO Logistics", use_cache=False)

    assert invoice.carrier == "XPO Logistics"
    assert invoice.pro_number == "781-5500112"
    assert invoice.origin_zip == "30301"
    assert invoice.dest_zip == "75201"
    assert invoice.invoice_total == 394.20
    assert any(acc.type == "liftgate" for acc in invoice.accessorials)
    assert val_result.is_valid is True
    assert val_result.arithmetic_sum_match is True


def test_invoice_parse_sha256_caching():
    """Verifies that re-parsing identical document content hits the SHA-256 cache ($0 token cost)."""
    raw_doc = """
    Roadrunner Freight
    Invoice: RR-1002
    PRO#: 552-990011
    Date: 2026-08-18
    From: 90001 To: 85001
    Weight: 950 lbs
    Base Freight: $120.00
    Fuel: $37.80
    Total: $157.80
    """
    # 1. First parse (cache miss)
    inv1, val1, meta1 = parse_invoice_document(raw_doc, carrier_hint="Roadrunner", use_cache=True)
    assert meta1["cache_hit"] is False

    # 2. Second parse (cache hit)
    inv2, val2, meta2 = parse_invoice_document(raw_doc, carrier_hint="Roadrunner", use_cache=True)
    assert meta2["cache_hit"] is True
    assert inv2.invoice_number == inv1.invoice_number
    assert inv2.invoice_total == inv1.invoice_total
    assert val2.composite_confidence == val1.composite_confidence


def test_invoice_parser_validation_failure_handling():
    """Corrupt invoice failing arithmetic reconciliation is routed to calibration queue."""
    raw_doc = """
    ABF FREIGHT
    INVOICE #: INV-CORRUPT-01
    PRO: 042-111111
    DATE: 2026-08-10
    ORIGIN: 60601 DEST: 48201
    WEIGHT: 1000 LBS
    Linehaul: $100.00
    Fuel: $30.00
    TOTAL AMOUNT DUE: $250.00
    """
    invoice, val_result, meta = parse_invoice_document(raw_doc, use_cache=False)

    # Arithmetic mismatch: sum is $130 vs billed $250!
    assert val_result.arithmetic_sum_match is False
    assert val_result.needs_calibration_queue is True
    assert val_result.is_valid is False
    assert meta["status"] == "parse_failed"


def test_persist_parsed_invoice_payload():
    """Verifies database persistence payload formatting."""
    invoice = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-123456",
        invoice_number="INV-123",
        invoice_date="2026-08-10",
        origin_zip="60601",
        dest_zip="48201",
        billed_weight=1000.0,
        invoice_total=130.00,
        line_items=[],
    )
    from validation import validate_invoice_extraction
    val = validate_invoice_extraction(invoice)

    payload = persist_parsed_invoice(None, "dummy-invoice-id", invoice, val)
    assert payload["carrier"] == "ABF Freight"
    assert payload["invoice_number"] == "INV-123"
    assert "parsed_json" in payload
    assert payload["status"] in ["parsed", "parse_failed"]
