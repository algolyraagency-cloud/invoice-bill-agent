"""
Unit tests for RateGuard AI Audit Run Orchestrator (Phase 3.1).
Tests single-invoice auditing, batch backfill execution, metric aggregation,
scope handling, and persistence formatting.
"""
from pathlib import Path
import sys
from unittest.mock import MagicMock
import pytest

root_dir = Path(__file__).resolve().parents[3]
engine_dir = Path(__file__).resolve().parents[1]
for p in [str(root_dir), str(engine_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from orchestrator import audit_batch, audit_invoice, persist_audit_run_result
from packages.schemas.models import (
    FSCEntry,
    InvoiceJSON,
    LineItem,
    RateMatrixJSON,
    RateMatrixRow,
)


@pytest.fixture
def test_rate_matrix():
    return RateMatrixJSON(
        carrier="ABF Freight",
        effective_dates={"start": "2026-01-01", "end": "2026-12-31"},
        discount_pct=50.0,
        absolute_min_charge=100.00,
        rates=[
            RateMatrixRow(
                origin_zip_prefix="606",
                dest_zip_prefix="750",
                weight_break="L5C",
                min_weight=0.0,
                rate=80.00,
                deficit_weight_eligible=True,
                effective_date_start="2026-01-01",
                effective_date_end="2026-12-31",
            ),
            RateMatrixRow(
                origin_zip_prefix="606",
                dest_zip_prefix="750",
                weight_break="M5C",
                min_weight=500.0,
                rate=60.00,
                deficit_weight_eligible=True,
                effective_date_start="2026-01-01",
                effective_date_end="2026-12-31",
            ),
        ],
    )


@pytest.fixture
def test_fsc_tables():
    return [
        FSCEntry(
            carrier="ABF Freight",
            effective_week_start="2026-08-10",
            effective_week_end="2026-08-16",
            min_diesel_price=3.80,
            max_diesel_price=3.849,
            fsc_pct=31.00,
        )
    ]


def test_audit_invoice_clean(test_rate_matrix, test_fsc_tables):
    """Clean invoice matching contracted rates, FSC, and arithmetic produces zero flags."""
    # 500 lbs @ $60/cwt = $300.00. 50% discount = $150.00 linehaul.
    # FSC 31% on $150.00 = $46.50. Total = $196.50.
    clean_inv = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-CLN01",
        invoice_number="INV-CLN01",
        invoice_date="2026-08-12",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=500.0,
        line_items=[
            LineItem(description="Linehaul Base", amount=150.00),
            LineItem(description="Fuel Surcharge", amount=46.50),
        ],
        fsc_amount=46.50,
        fsc_pct=31.00,
        invoice_total=196.50,
    )
    flags = audit_invoice(
        invoice=clean_inv,
        rate_matrices=[test_rate_matrix],
        fsc_tables=test_fsc_tables,
        eia_diesel_price=3.82,
    )
    assert len(flags) == 0


def test_audit_invoice_multiple_findings(test_rate_matrix, test_fsc_tables):
    """An invoice with multiple discrepancies returns distinct flags for each finding."""
    # 1. Billed linehaul $250 instead of contracted $150 (RATE)
    # 2. Billed FSC 35% instead of 31% (FSC)
    # 3. Sum of items ($250 + $70 = $320) does not match total $340 ($20 drift) (ARITH)
    bad_inv = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-BAD01",
        invoice_number="INV-BAD01",
        invoice_date="2026-08-12",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=500.0,
        line_items=[
            LineItem(description="Linehaul Base", amount=250.00),
            LineItem(description="Fuel Surcharge", amount=70.00),
        ],
        fsc_amount=70.00,
        fsc_pct=35.00,
        invoice_total=340.00,
    )
    flags = audit_invoice(
        invoice=bad_inv,
        rate_matrices=[test_rate_matrix],
        fsc_tables=test_fsc_tables,
        eia_diesel_price=3.82,
    )
    assert len(flags) >= 2
    check_types = {f.check_type for f in flags}
    assert "RATE" in check_types
    assert "FSC" in check_types
    assert "ARITH" in check_types


def test_audit_batch_comprehensive(test_rate_matrix, test_fsc_tables):
    """Batch audit correctly aggregates statistics and categorizes flags."""
    # Inv 1: Clean original bill
    inv1 = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-BATCH-01",
        invoice_number="INV-B01",
        invoice_date="2026-08-10",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=500.0,
        line_items=[
            LineItem(description="Linehaul Base", amount=150.00),
            LineItem(description="Fuel Surcharge", amount=46.50),
        ],
        fsc_amount=46.50,
        fsc_pct=31.00,
        invoice_total=196.50,
    )
    # Inv 2: Duplicate rebill of Inv 1
    inv2 = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-BATCH-01",
        invoice_number="INV-B02",
        invoice_date="2026-08-14",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=500.0,
        line_items=[
            LineItem(description="Linehaul Base", amount=150.00),
            LineItem(description="Fuel Surcharge", amount=46.50),
        ],
        invoice_total=196.50,
    )
    # Inv 3: Overcharged rate (billed $220.00 base instead of $150.00)
    inv3 = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-BATCH-03",
        invoice_number="INV-B03",
        invoice_date="2026-08-12",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=500.0,
        line_items=[
            LineItem(description="Linehaul Base", amount=220.00),
            LineItem(description="Fuel Surcharge", amount=46.50),
        ],
        fsc_amount=46.50,
        fsc_pct=31.00,
        invoice_total=266.50,
    )
    # Inv 4: Clean shipment (distinct date > 3 days away)
    inv4 = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-BATCH-04",
        invoice_number="INV-B04",
        invoice_date="2026-08-25",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=500.0,
        line_items=[
            LineItem(description="Linehaul Base", amount=150.00),
            LineItem(description="Fuel Surcharge", amount=46.50),
        ],
        fsc_amount=46.50,
        fsc_pct=31.00,
        invoice_total=196.50,
    )

    batch_invoices = [inv1, inv2, inv3, inv4]

    result = audit_batch(
        invoices=batch_invoices,
        rate_matrices=[test_rate_matrix],
        fsc_tables=test_fsc_tables,
        customer_id="cust_acme_corp",
        eia_diesel_price=3.82,
    )

    assert result.customer_id == "cust_acme_corp"
    assert result.stats.total_invoices_audited == 4
    assert result.stats.clean_invoices_count == 2
    assert result.stats.flagged_invoices_count == 2
    assert result.stats.flags_by_check_type.get("DUP") == 1
    assert result.stats.flags_by_check_type.get("RATE") == 1
    assert result.stats.total_overcharge_cents > 0
    assert result.stats.duration_seconds >= 0.0
    assert "INV-B02" in result.flags_by_invoice
    assert "INV-B03" in result.flags_by_invoice
    assert "INV-B01" not in result.flags_by_invoice  # Original is clean!


def test_audit_batch_empty():
    """Empty batch returns valid zero stats without error."""
    result = audit_batch(
        invoices=[],
        rate_matrices=[],
        fsc_tables=[],
        customer_id="cust_empty",
    )
    assert result.stats.total_invoices_audited == 0
    assert result.stats.clean_invoices_count == 0
    assert result.stats.flagged_invoices_count == 0
    assert len(result.all_flags) == 0


def test_persist_audit_run_result_mock(test_rate_matrix):
    """Verifies that persist_audit_run_result correctly calls Supabase tables."""
    inv = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-PERSIST",
        invoice_number="INV-P1",
        invoice_date="2026-08-12",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=500.0,
        line_items=[LineItem(description="Linehaul Base", amount=250.00)],
        invoice_total=250.00,
    )
    result = audit_batch(
        invoices=[inv],
        rate_matrices=[test_rate_matrix],
        customer_id="cust_test",
    )

    mock_client = MagicMock()
    res = persist_audit_run_result(mock_client, result)
    assert res["persisted"] is True
    assert mock_client.table.call_count >= 2
