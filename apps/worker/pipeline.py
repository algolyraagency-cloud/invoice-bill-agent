"""
RateGuard AI — End-to-End Pipeline Wiring & Worker Orchestrator (Phase 3.2).
Handles asynchronous job execution across the pipeline:
1. 'parse-invoice': PDF extraction -> LLM understanding -> validation -> triggers audit.
2. 'run-audit-for-invoice': Deterministic audit engine execution on arrival with idempotency keys.
3. 'run-audit-batch': Unattended historical backfill execution (e.g. 6-month, 2,500+ invoices).
4. Dead-letter queue & failure alerting to protect against unhandled crashes.

Guarantees every invoice terminates in a canonical state:
'parsed', 'parse_failed', 'audited', or 'error'.
"""
from datetime import datetime, timezone
import json
import logging
from typing import Any, Callable, Dict, List, Optional, Union
import uuid

from packages.schemas.models import (
    AuditRunResult,
    Flag,
    FSCEntry,
    InvoiceJSON,
    InvoiceValidationResult,
    RateMatrixJSON,
)

try:
    from invoice_parser import parse_invoice, persist_parsed_invoice
    from cost_guard import global_cost_guard
except ImportError:
    from apps.worker.invoice_parser import parse_invoice, persist_parsed_invoice
    from apps.worker.cost_guard import global_cost_guard

try:
    from orchestrator import audit_batch, audit_invoice, persist_audit_run_result
except ImportError:
    from packages.audit_engine.orchestrator import audit_batch, audit_invoice, persist_audit_run_result

logger = logging.getLogger("rateguard.pipeline")


class DeadLetterQueue:
    """In-memory and DB dead-letter tracker for failed jobs."""

    def __init__(self, alert_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None):
        self.failed_jobs: List[Dict[str, Any]] = []
        self.alert_callback = alert_callback

    def record_failure(
        self,
        queue_name: str,
        job_id: str,
        job_data: Dict[str, Any],
        error_message: str,
        supabase_client: Any = None,
    ):
        failure_record = {
            "id": str(uuid.uuid4()),
            "job_id": job_id,
            "queue_name": queue_name,
            "job_data": job_data,
            "error_message": error_message,
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }
        self.failed_jobs.append(failure_record)
        logger.error(f"DLQ RECORDED [{queue_name}:{job_id}]: {error_message}")

        if self.alert_callback:
            try:
                self.alert_callback(f"JOB FAILED [{queue_name}]", failure_record)
            except Exception as alert_err:
                logger.warning(f"DLQ Alert callback failed: {alert_err}")

        if supabase_client:
            try:
                # Update invoice status to error so it does not hang in pending
                inv_id = job_data.get("invoice_id") or job_data.get("invoiceId")
                if inv_id:
                    supabase_client.table("invoices").update({"status": "error"}).eq("id", inv_id).execute()
            except Exception as db_err:
                logger.warning(f"DLQ DB update error: {db_err}")


# Global DLQ instance
global_dlq = DeadLetterQueue()


def process_parse_invoice_job(
    job_data: Dict[str, Any],
    db_client: Any = None,
    enqueue_audit_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
    cost_guard_instance: Any = None,
) -> Dict[str, Any]:
    """
    Handler for 'parse-invoice' queue job.
    1. Extracts and structures PDF into InvoiceJSON.
    2. Runs Phase 2.0 self-validation.
    3. Persists result in DB ('parsed' or 'parse_failed').
    4. If valid, triggers 'run-audit-for-invoice' job.
    """
    invoice_id = job_data.get("invoice_id") or job_data.get("invoiceId") or f"inv_{uuid.uuid4().hex[:8]}"
    customer_id = job_data.get("customer_id") or job_data.get("customerId", "default_customer")
    file_path = job_data.get("file_path") or job_data.get("filePath")
    content_bytes = job_data.get("content_bytes")
    raw_text = job_data.get("raw_text")
    carrier_hint = job_data.get("carrier_hint") or job_data.get("carrier")

    # Determine input source
    source = content_bytes or file_path or raw_text
    if source is None:
        raise ValueError(f"Job {invoice_id} missing content_bytes, file_path, or raw_text")

    # Parse invoice with cost guard and validation
    invoice_json, val_result, metadata = parse_invoice(
        document_input=source,
        carrier_hint=carrier_hint,
        use_cache=job_data.get("use_cache", True),
    )

    # Persist in Supabase
    if db_client:
        persist_parsed_invoice(db_client, invoice_id, invoice_json, val_result)

    # Route based on validation outcome
    if not val_result.is_valid:
        logger.info(f"Invoice {invoice_id} failed validation -> status=parse_failed (routed to calibration queue)")
        return {
            "invoice_id": invoice_id,
            "customer_id": customer_id,
            "status": "parse_failed",
            "confidence": val_result.composite_confidence,
            "audit_enqueued": False,
            "metadata": metadata,
        }

    # Invoice successfully parsed -> enqueue audit job
    audit_job_payload = {
        "invoice_id": invoice_id,
        "customer_id": customer_id,
        "invoice_json": invoice_json.model_dump(),
        "idempotency_key": f"{invoice_id}:audit",
    }

    audit_enqueued = False
    if enqueue_audit_fn:
        try:
            enqueue_audit_fn(audit_job_payload)
            audit_enqueued = True
        except Exception as q_err:
            logger.error(f"Failed to enqueue audit job for invoice {invoice_id}: {q_err}")

    return {
        "invoice_id": invoice_id,
        "customer_id": customer_id,
        "status": "parsed",
        "confidence": val_result.composite_confidence,
        "audit_enqueued": audit_enqueued,
        "pro_number": invoice_json.pro_number,
        "metadata": metadata,
    }


def process_run_audit_for_invoice_job(
    job_data: Dict[str, Any],
    rate_matrices: List[RateMatrixJSON],
    fsc_tables: Optional[List[FSCEntry]] = None,
    all_invoices: Optional[List[InvoiceJSON]] = None,
    db_client: Any = None,
    eia_diesel_price: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Handler for 'run-audit-for-invoice' queue job.
    Executes all 4 deterministic audit checks on arrival with audit idempotency keys.
    """
    invoice_id = job_data.get("invoice_id") or job_data.get("invoiceId")
    customer_id = job_data.get("customer_id") or job_data.get("customerId", "default_customer")
    inv_data = job_data.get("invoice_json")

    if isinstance(inv_data, InvoiceJSON):
        invoice = inv_data
    elif isinstance(inv_data, dict):
        invoice = InvoiceJSON(**inv_data)
    elif db_client and invoice_id:
        row = db_client.table("invoices").select("parsed_json").eq("id", invoice_id).single().execute()
        if row and row.data and row.data.get("parsed_json"):
            invoice = InvoiceJSON(**row.data["parsed_json"])
        else:
            raise ValueError(f"Could not load parsed invoice for id {invoice_id}")
    else:
        raise ValueError(f"Missing invoice data for audit job {invoice_id}")

    # Attach invoice id to model if missing
    invoice.id = invoice_id

    # Execute deterministic audit
    flags = audit_invoice(
        invoice=invoice,
        rate_matrices=rate_matrices,
        fsc_tables=fsc_tables or [],
        all_invoices=all_invoices or [invoice],
        eia_diesel_price=eia_diesel_price,
    )

    for f in flags:
        f.invoice_id = invoice_id

    # Persist flags idempotently
    if db_client and invoice_id:
        # 1. Delete previous flags for this invoice if re-auditing (Idempotency)
        db_client.table("flags").delete().eq("invoice_id", invoice_id).execute()

        # 2. Bulk insert new flags
        if flags:
            flag_rows = []
            for f in flags:
                flag_rows.append({
                    "invoice_id": invoice_id,
                    "check_type": f.check_type,
                    "overcharge_cents": f.overcharge_cents,
                    "confidence": f.confidence,
                    "evidence_json": f.evidence_json,
                    "review_status": f.review_status,
                    "reject_reason_code": f.reject_reason_code,
                })
            db_client.table("flags").insert(flag_rows).execute()

        # 3. Mark invoice status = 'audited'
        db_client.table("invoices").update({"status": "audited"}).eq("id", invoice_id).execute()

    overcharge_cents = sum(f.overcharge_cents for f in flags)

    return {
        "invoice_id": invoice_id,
        "customer_id": customer_id,
        "status": "audited",
        "flags_count": len(flags),
        "overcharge_cents": overcharge_cents,
        "flags": [f.model_dump() for f in flags],
    }


def process_run_audit_batch_job(
    job_data: Dict[str, Any],
    invoices: List[InvoiceJSON],
    rate_matrices: List[RateMatrixJSON],
    fsc_tables: Optional[List[FSCEntry]] = None,
    db_client: Any = None,
    eia_diesel_price: Optional[float] = None,
) -> AuditRunResult:
    """
    Handler for 'run-audit-batch' job (e.g. 6-month historical onboarding backfills).
    Processes thousands of invoices unattended and writes comprehensive stats and flags.
    """
    customer_id = job_data.get("customer_id") or job_data.get("customerId", "default_customer")
    audit_run_id = job_data.get("audit_run_id") or f"batch_{uuid.uuid4().hex[:12]}"
    scope = job_data.get("scope", {"batch_size": len(invoices)})

    logger.info(f"Starting unattended batch audit run {audit_run_id} for {len(invoices)} invoices")

    result = audit_batch(
        invoices=invoices,
        rate_matrices=rate_matrices,
        fsc_tables=fsc_tables or [],
        customer_id=customer_id,
        audit_run_id=audit_run_id,
        scope=scope,
        eia_diesel_price=eia_diesel_price,
    )

    if db_client:
        persist_audit_run_result(db_client, result)
        # Update all processed invoices to 'audited'
        for inv in invoices:
            inv_id = getattr(inv, "id", None) or inv.invoice_number
            db_client.table("invoices").update({"status": "audited"}).eq("invoice_number", inv.invoice_number).execute()

    logger.info(
        f"Batch audit {audit_run_id} finished: {result.stats.total_invoices_audited} audited, "
        f"{result.stats.total_flags_count} flags, ${result.stats.total_overcharge_cents / 100:.2f} overcharge in {result.stats.duration_seconds}s"
    )

    return result
