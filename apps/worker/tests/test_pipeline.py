"""
Unit tests for RateGuard AI Worker Pipeline Wiring & Orchestrator (Phase 3.2).
Verifies:
1. 'parse-invoice' job transitions valid invoices to 'parsed' and triggers audit.
2. Invoices failing arithmetic validation transition to 'parse_failed' (calibration queue).
3. 'run-audit-for-invoice' executes on arrival with idempotency keys and marks invoice 'audited'.
4. 'run-audit-batch' processes multi-invoice backfills unattended and produces complete stats.
5. Dead-letter queue captures crashes, prevents infinite loops, and alerts.
"""
from pathlib import Path
import sys
from unittest.mock import MagicMock
import pytest

root_dir = Path(__file__).resolve().parents[3]
worker_dir = Path(__file__).resolve().parents[1]
audit_engine_dir = root_dir / "packages" / "audit-engine"
for p in [str(root_dir), str(worker_dir), str(audit_engine_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from pipeline import (
    DeadLetterQueue,
    process_parse_invoice_job,
    process_run_audit_batch_job,
    process_run_audit_for_invoice_job,
)
from packages.schemas.models import (
    FSCEntry,
    InvoiceJSON,
    LineItem,
    RateMatrixJSON,
    RateMatrixRow,
)


@pytest.fixture
def mock_rate_matrix():
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
            )
        ],
    )


@pytest.fixture
def mock_fsc_tables():
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


def test_process_parse_invoice_job_success():
    """Valid invoice PDF text passes self-validation and enqueues the audit job."""
    enqueued_audit_jobs = []

    def mock_enqueue(payload):
        enqueued_audit_jobs.append(payload)

    raw_invoice_text = (
        "ABF Freight System\n"
        "PRO Number: 042-888999\n"
        "Invoice: INV-888999\n"
        "Date: 2026-08-12\n"
        "Origin: 60601 Destination: 75001\n"
        "Weight: 450 lbs\n"
        "Linehaul: $200.00\n"
        "Fuel Surcharge: $62.00\n"
        "Total: $262.00\n"
    )

    result = process_parse_invoice_job(
        job_data={
            "invoice_id": "inv_test_01",
            "customer_id": "cust_acme",
            "raw_text": raw_invoice_text,
            "carrier_hint": "ABF Freight",
        },
        enqueue_audit_fn=mock_enqueue,
    )

    assert result["status"] == "parsed"
    assert result["audit_enqueued"] is True
    assert len(enqueued_audit_jobs) == 1
    assert enqueued_audit_jobs[0]["invoice_id"] == "inv_test_01"
    assert enqueued_audit_jobs[0]["idempotency_key"] == "inv_test_01:audit"


def test_process_parse_invoice_job_failure_routes_to_calibration():
    """Invoice with arithmetic drift fails validation, receives parse_failed, and does not enqueue audit."""
    enqueued_audit_jobs = []

    def mock_enqueue(payload):
        enqueued_audit_jobs.append(payload)

    # Sum of items = $250.00, but Total = $350.00 ($100 drift)
    corrupt_text = (
        "Carrier: ABF Freight\n"
        "PRO Number: 042-CORRUPT\n"
        "Invoice: INV-CORRUPT\n"
        "Date: 2026-08-12\n"
        "Weight: 500 lbs\n"
        "Linehaul: $200.00\n"
        "Fuel: $50.00\n"
        "Total: $350.00\n"
    )

    result = process_parse_invoice_job(
        job_data={
            "invoice_id": "inv_corrupt_01",
            "customer_id": "cust_acme",
            "raw_text": corrupt_text,
            "carrier_hint": "ABF Freight",
        },
        enqueue_audit_fn=mock_enqueue,
    )

    assert result["status"] == "parse_failed"
    assert result["audit_enqueued"] is False
    assert len(enqueued_audit_jobs) == 0


def test_process_run_audit_for_invoice_job(mock_rate_matrix, mock_fsc_tables):
    """Single invoice audit job executes deterministically and outputs flags with idempotency."""
    # Billed $250 linehaul instead of contracted ($80 * 4.5 * 50% = $180) -> Overcharge $70
    invoice = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-AUDIT-01",
        invoice_number="INV-A01",
        invoice_date="2026-08-12",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=450.0,
        line_items=[
            LineItem(description="Linehaul Base", amount=250.00),
            LineItem(description="Fuel Surcharge", amount=55.80),
        ],
        fsc_amount=55.80,
        fsc_pct=31.00,
        invoice_total=305.80,
    )

    mock_db = MagicMock()

    result = process_run_audit_for_invoice_job(
        job_data={
            "invoice_id": "inv_audit_01",
            "customer_id": "cust_acme",
            "invoice_json": invoice.model_dump(),
        },
        rate_matrices=[mock_rate_matrix],
        fsc_tables=mock_fsc_tables,
        db_client=mock_db,
        eia_diesel_price=3.82,
    )

    assert result["status"] == "audited"
    assert result["flags_count"] == 1
    assert result["overcharge_cents"] == 7000
    # Verify idempotency: previous flags deleted and new flags inserted
    assert mock_db.table("flags").delete.called
    assert mock_db.table("flags").insert.called
    assert mock_db.table("invoices").update.called


def test_process_run_audit_batch_job_unattended(mock_rate_matrix, mock_fsc_tables):
    """Batch audit processes backfill unattended and transitions every invoice to audited."""
    inv1 = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-BATCH-01",
        invoice_number="INV-B01",
        invoice_date="2026-08-10",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=450.0,
        line_items=[LineItem(description="Linehaul", amount=180.00)],
        invoice_total=180.00,
    )
    inv2 = InvoiceJSON(
        carrier="ABF Freight",
        pro_number="042-BATCH-02",
        invoice_number="INV-B02",
        invoice_date="2026-08-12",
        origin_zip="60601",
        dest_zip="75001",
        billed_weight=450.0,
        line_items=[LineItem(description="Linehaul", amount=240.00)],  # Overcharge $60
        invoice_total=240.00,
    )

    mock_db = MagicMock()

    batch_result = process_run_audit_batch_job(
        job_data={
            "customer_id": "cust_acme",
            "audit_run_id": "run_backfill_6mo",
            "scope": {"month_range": "6 months"},
        },
        invoices=[inv1, inv2],
        rate_matrices=[mock_rate_matrix],
        fsc_tables=mock_fsc_tables,
        db_client=mock_db,
        eia_diesel_price=3.82,
    )

    assert batch_result.audit_run_id == "run_backfill_6mo"
    assert batch_result.stats.total_invoices_audited == 2
    assert batch_result.stats.clean_invoices_count == 1
    assert batch_result.stats.flagged_invoices_count == 1
    assert batch_result.stats.total_overcharge_cents == 6000
    assert mock_db.table("audit_runs").insert.called


def test_dead_letter_queue():
    """Dead-letter queue records failures, updates DB status, and triggers alerts."""
    alerts = []

    def on_alert(title, payload):
        alerts.append((title, payload))

    dlq = DeadLetterQueue(alert_callback=on_alert)
    mock_db = MagicMock()

    dlq.record_failure(
        queue_name="parse-invoice",
        job_id="job_999",
        job_data={"invoice_id": "inv_crash_01"},
        error_message="Simulated OCR engine segmentation fault",
        supabase_client=mock_db,
    )

    assert len(dlq.failed_jobs) == 1
    assert dlq.failed_jobs[0]["job_id"] == "job_999"
    assert len(alerts) == 1
    # Verify invoice status updated to 'error'
    assert mock_db.table("invoices").update.called
