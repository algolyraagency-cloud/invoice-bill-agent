"""
RateGuard AI — Audit Run Orchestrator (Phase 3.1).
Batch execution engine over customer invoice scopes.
Tracks execution metrics, aggregates stats, and collects structured audit findings.

Zero LLM, zero network drift. Pure deterministic orchestration.
"""
from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional
import uuid

from packages.schemas.models import (
    AuditRunResult,
    AuditRunStats,
    Flag,
    FSCEntry,
    InvoiceJSON,
    RateMatrixJSON,
)

try:
    from engine import check_arithmetic, check_duplicates, check_fsc, check_rates, parse_date
except ImportError:
    try:
        from .engine import check_arithmetic, check_duplicates, check_fsc, check_rates, parse_date
    except ImportError:
        from packages.audit_engine.engine import (
            check_arithmetic,
            check_duplicates,
            check_fsc,
            check_rates,
            parse_date,
        )


def audit_invoice(
    invoice: InvoiceJSON,
    rate_matrices: List[RateMatrixJSON],
    fsc_tables: Optional[List[FSCEntry]] = None,
    all_invoices: Optional[List[InvoiceJSON]] = None,
    eia_diesel_price: Optional[float] = None,
    eia_indices: Optional[List[Dict[str, Any]]] = None,
) -> List[Flag]:
    """
    Executes the 4 deterministic audit checks on a single invoice:
    1. Duplicates (DUP)
    2. Rates & Deficit Weight Rating (RATE)
    3. Fuel Surcharge (FSC)
    4. Arithmetic Reconciliation (ARITH)
    """
    flags: List[Flag] = []
    comparison_invoices = all_invoices or [invoice]

    # Check 1: Duplicate Detection
    dup_flags = check_duplicates(invoice, comparison_invoices)
    flags.extend(dup_flags)

    # Check 2: Rate & Deficit Weight Check
    rate_flags = check_rates(invoice, rate_matrices)
    flags.extend(rate_flags)

    # Check 3: Fuel Surcharge Check
    fsc_flags = check_fsc(
        invoice,
        fsc_tables=fsc_tables,
        eia_diesel_price=eia_diesel_price,
        eia_indices=eia_indices,
    )
    flags.extend(fsc_flags)

    # Check 4: Arithmetic Reconciliation
    arith_flags = check_arithmetic(invoice)
    flags.extend(arith_flags)

    return flags


def audit_batch(
    invoices: List[InvoiceJSON],
    rate_matrices: List[RateMatrixJSON],
    fsc_tables: Optional[List[FSCEntry]] = None,
    customer_id: str = "default_customer",
    audit_run_id: Optional[str] = None,
    scope: Optional[Dict[str, Any]] = None,
    eia_indices: Optional[List[Dict[str, Any]]] = None,
    eia_diesel_price: Optional[float] = None,
) -> AuditRunResult:
    """
    Executes batch audit over a collection of invoices (e.g. 6-month historical backfill or periodic batch).

    1. Chronologically sorts invoices to preserve duplicate check causality.
    2. Runs all 4 checks on each invoice against the entire batch and contract versions.
    3. Aggregates execution metrics, overcharge sums, and category distributions.
    4. Returns structured AuditRunResult ready for DB persistence.
    """
    start_time = time.perf_counter()
    run_id = audit_run_id or f"run_{uuid.uuid4().hex[:12]}"
    started_at = datetime.now(timezone.utc).isoformat()

    fsc_tables = fsc_tables or []
    scope_info = scope or {
        "invoice_count": len(invoices),
        "earliest_date": min((inv.invoice_date for inv in invoices), default=None) if invoices else None,
        "latest_date": max((inv.invoice_date for inv in invoices), default=None) if invoices else None,
    }

    # Chronologically sort invoices: earlier invoices first
    sorted_invoices = sorted(
        invoices,
        key=lambda inv: (parse_date(inv.invoice_date), inv.invoice_number)
    )

    flags_by_invoice: Dict[str, List[Flag]] = {}
    all_flags: List[Flag] = []
    flags_by_check_type: Dict[str, int] = {}
    flags_by_carrier: Dict[str, int] = {}
    overcharge_by_check_type: Dict[str, int] = {}
    total_overcharge_cents = 0
    clean_invoices_count = 0
    flagged_invoices_count = 0

    for inv in sorted_invoices:
        inv_flags = audit_invoice(
            invoice=inv,
            rate_matrices=rate_matrices,
            fsc_tables=fsc_tables,
            all_invoices=sorted_invoices,
            eia_diesel_price=eia_diesel_price,
            eia_indices=eia_indices,
        )

        if inv_flags:
            flagged_invoices_count += 1
            flags_by_invoice[inv.invoice_number] = inv_flags
            all_flags.extend(inv_flags)

            for f in inv_flags:
                total_overcharge_cents += f.overcharge_cents

                # Breakdown by check type
                flags_by_check_type[f.check_type] = flags_by_check_type.get(f.check_type, 0) + 1
                overcharge_by_check_type[f.check_type] = overcharge_by_check_type.get(f.check_type, 0) + f.overcharge_cents

                # Breakdown by carrier
                carrier_key = inv.carrier
                flags_by_carrier[carrier_key] = flags_by_carrier.get(carrier_key, 0) + 1
        else:
            clean_invoices_count += 1

    elapsed = time.perf_counter() - start_time
    completed_at = datetime.now(timezone.utc).isoformat()

    stats = AuditRunStats(
        total_invoices_audited=len(sorted_invoices),
        clean_invoices_count=clean_invoices_count,
        flagged_invoices_count=flagged_invoices_count,
        total_flags_count=len(all_flags),
        total_overcharge_cents=total_overcharge_cents,
        flags_by_check_type=flags_by_check_type,
        flags_by_carrier=flags_by_carrier,
        overcharge_by_check_type=overcharge_by_check_type,
        duration_seconds=round(elapsed, 4),
    )

    return AuditRunResult(
        audit_run_id=run_id,
        customer_id=customer_id,
        scope=scope_info,
        started_at=started_at,
        completed_at=completed_at,
        stats=stats,
        flags_by_invoice=flags_by_invoice,
        all_flags=all_flags,
    )


def persist_audit_run_result(supabase_client, result: AuditRunResult) -> Dict[str, Any]:
    """
    Persists AuditRunResult into Supabase:
    1. Inserts audit_runs row.
    2. Bulk inserts flags rows with evidence_json.
    """
    if not supabase_client:
        return {"audit_run_id": result.audit_run_id, "persisted": False, "reason": "No client provided"}

    # Insert audit_runs record
    run_record = {
        "id": result.audit_run_id,
        "customer_id": result.customer_id,
        "scope": result.scope,
        "started_at": result.started_at,
        "completed_at": result.completed_at,
        "stats_json": result.stats.model_dump(),
    }
    supabase_client.table("audit_runs").insert(run_record).execute()

    # Bulk insert flags
    flag_records = []
    for flag in result.all_flags:
        flag_records.append({
            "audit_run_id": result.audit_run_id,
            "invoice_id": flag.invoice_id,
            "check_type": flag.check_type,
            "overcharge_cents": flag.overcharge_cents,
            "confidence": flag.confidence,
            "evidence_json": flag.evidence_json,
            "review_status": flag.review_status,
            "reject_reason_code": flag.reject_reason_code,
        })

    if flag_records:
        supabase_client.table("flags").insert(flag_records).execute()

    return {"audit_run_id": result.audit_run_id, "persisted": True, "flags_count": len(flag_records)}
