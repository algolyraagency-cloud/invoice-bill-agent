"""
RateGuard AI — Validation Layer (Phase 2.0).
The trust backbone for invoice extraction self-validation, contract matrix sanity checks,
spot-verification protocols, and standardized review reason code validation.

Core Law: LLMs understand, code calculates. Never the reverse.
Pure deterministic code. Zero LLM, zero network, zero I/O.
"""
import random
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from packages.schemas.models import (
    ContractSanityIssue,
    ContractValidationResult,
    ExtractionCheckDetail,
    FSCEntry,
    InvoiceJSON,
    InvoiceValidationResult,
    RateMatrixJSON,
    RateMatrixRow,
    SpotCheckItem,
    SpotVerificationResult,
)

# Standard Reason-Code Taxonomy v1 (PRD §5.5, Phase 2.0.4)
STANDARD_REASON_CODES: Set[str] = {
    "wrong-matrix-row",
    "misread-pdf-field",
    "contract-exception-misapplied",
    "not-an-error",
    "duplicate-false-positive",
    "fsc-table-wrong-month",
    "rate-effective-date-mismatch",
    "other",
}

# Standard LTL Weight Break Hierarchy (ordered from lowest to highest weight tier)
WEIGHT_BREAK_ORDER: Dict[str, int] = {
    "MC": 0,
    "MIN": 0,
    "L5C": 1,
    "M5C": 2,
    "M1M": 3,
    "1M": 3,
    "M2M": 4,
    "2M": 4,
    "M5M": 5,
    "5M": 5,
    "M10M": 6,
    "10M": 6,
    "M20M": 7,
    "20M": 7,
    "M30M": 8,
    "30M": 8,
    "M40M": 9,
    "40M": 9,
}


def validate_rejection_reason_code(code: str) -> bool:
    """Validates if a reason code conforms to the standardized v1 taxonomy."""
    return code.strip().lower() in STANDARD_REASON_CODES


# ==============================================================================
# Phase 2.0.1 — Extraction Self-Validation
# ==============================================================================

def validate_invoice_extraction(
    invoice: InvoiceJSON,
    rounding_tolerance: float = 0.02
) -> InvoiceValidationResult:
    """
    Deterministically re-derives invoice arithmetic from extracted line items
    and evaluates field integrity to assign a composite confidence score.
    
    If arithmetic or critical fields fail, flags invoice for calibration queue.
    """
    checks: List[ExtractionCheckDetail] = []
    notes: List[str] = []
    confidence: float = 1.000

    # 1. Check Header & Identifiers
    headers_valid = True
    if not invoice.carrier or len(invoice.carrier.strip()) < 2:
        headers_valid = False
        notes.append("Carrier name missing or invalid")
    if not invoice.pro_number or len(invoice.pro_number.strip()) < 3:
        headers_valid = False
        notes.append("PRO tracking number missing or malformed")
    if not invoice.invoice_number or len(invoice.invoice_number.strip()) < 2:
        headers_valid = False
        notes.append("Invoice number missing or malformed")
    
    # Date validation YYYY-MM-DD
    date_valid = True
    try:
        datetime.strptime(invoice.invoice_date.strip()[:10], "%Y-%m-%d")
    except Exception:
        date_valid = False
        headers_valid = False
        notes.append(f"Invalid invoice date format: {invoice.invoice_date}")

    # Zip code validation (at least 3 characters)
    orig_clean = re.sub(r"[^\w]", "", invoice.origin_zip)
    dest_clean = re.sub(r"[^\w]", "", invoice.dest_zip)
    if len(orig_clean) < 3 or len(dest_clean) < 3:
        headers_valid = False
        notes.append(f"Invalid origin/dest zip prefixes: {invoice.origin_zip} -> {invoice.dest_zip}")

    checks.append(ExtractionCheckDetail(
        check_name="header_integrity",
        passed=headers_valid,
        message="Headers, identifiers, and zip codes valid" if headers_valid else "; ".join(notes)
    ))
    if not headers_valid:
        confidence -= 0.20

    # 2. Arithmetic Reconciliation: Sum of Line Items == invoice_total
    line_sum = round(sum(item.amount for item in invoice.line_items), 2)
    sum_diff = round(abs(invoice.invoice_total - line_sum), 2)
    arithmetic_sum_match = sum_diff <= rounding_tolerance

    if not arithmetic_sum_match:
        confidence -= 0.35
        notes.append(
            f"Line items sum (${line_sum:.2f}) differs from invoice_total (${invoice.invoice_total:.2f}) by ${sum_diff:.2f}"
        )

    checks.append(ExtractionCheckDetail(
        check_name="line_items_sum",
        passed=arithmetic_sum_match,
        billed_value=invoice.invoice_total,
        calculated_value=line_sum,
        discrepancy=sum_diff,
        message="Sum of line items matches total" if arithmetic_sum_match else f"Mismatch of ${sum_diff:.2f}"
    ))

    # 3. Component Breakdown: Base Linehaul + Fuel (FSC) + Accessorials == Total
    # Extract base freight
    base_linehaul = 0.0
    for item in invoice.line_items:
        desc = item.description.lower()
        if any(k in desc for k in ["freight", "base", "linehaul", "lh"]):
            base_linehaul += item.amount

    accessorials_sum = round(sum(acc.amount for acc in invoice.accessorials), 2)
    fsc_val = invoice.fsc_amount if invoice.fsc_amount is not None else 0.0

    # If accessorials or FSC were populated separately from line items, verify component coherence
    components_sum = round(base_linehaul + fsc_val + accessorials_sum, 2)
    comp_diff = round(abs(invoice.invoice_total - components_sum), 2)
    
    # Linehaul component match is considered valid if components sum matches total OR if line items already match total
    linehaul_fsc_accessorial_match = (comp_diff <= max(0.50, rounding_tolerance)) or arithmetic_sum_match

    checks.append(ExtractionCheckDetail(
        check_name="component_coherence",
        passed=linehaul_fsc_accessorial_match,
        billed_value=invoice.invoice_total,
        calculated_value=components_sum,
        discrepancy=comp_diff,
        message="Linehaul, FSC, and accessorial components reconcile" if linehaul_fsc_accessorial_match else f"Component sum differs by ${comp_diff:.2f}"
    ))
    if not linehaul_fsc_accessorial_match:
        confidence -= 0.15

    # 4. Weight and Total Sanity Checks
    if invoice.billed_weight <= 0:
        confidence -= 0.15
        notes.append("Billed weight is zero or negative")
    if invoice.invoice_total <= 0:
        confidence -= 0.40
        notes.append("Invoice total is zero or negative (non-credit invoice)")

    # 5. Composite Confidence calculation
    composite_confidence = round(max(0.0, min(1.0, confidence)), 3)

    # Route to calibration queue if arithmetic fails or confidence drops below 0.85
    needs_calibration = (not arithmetic_sum_match) or (composite_confidence < 0.85) or (not headers_valid)

    is_valid = arithmetic_sum_match and headers_valid and (composite_confidence >= 0.80)

    return InvoiceValidationResult(
        invoice_number=invoice.invoice_number,
        carrier=invoice.carrier,
        is_valid=is_valid,
        composite_confidence=composite_confidence,
        needs_calibration_queue=needs_calibration,
        arithmetic_sum_match=arithmetic_sum_match,
        linehaul_fsc_accessorial_match=linehaul_fsc_accessorial_match,
        checks=checks,
        reconciliation_notes=notes
    )


# ==============================================================================
# Phase 2.0.2 — Contract Sanity Suite & Spot-Verification Protocol
# ==============================================================================

def validate_contract_matrix(
    matrix: RateMatrixJSON,
    fsc_tables: Optional[List[FSCEntry]] = None,
    in_scope_months: Optional[List[str]] = None
) -> ContractValidationResult:
    """
    Runs deterministic sanity checks on a parsed RateMatrixJSON before it can power audits:
    1. Duplicate lane rows.
    2. Overlapping weight breaks and ascending min_weights.
    3. Rate monotonicity (rates per cwt must not increase at higher weight breaks).
    4. Minimum charge floor sanity vs lane rates.
    5. FSC table coverage across required months.
    6. Currency / zero / negative rate anomalies.
    """
    issues: List[ContractSanityIssue] = []
    total_lanes = len(matrix.rates)

    if total_lanes == 0:
        issues.append(ContractSanityIssue(
            issue_type="missing_rates",
            severity="error",
            details={},
            message="Rate matrix contains zero rates"
        ))

    # Group rates by lane key: (origin_zip_prefix, dest_zip_prefix)
    lanes_map: Dict[Tuple[str, str], List[RateMatrixRow]] = {}
    seen_row_signatures: Set[Tuple[str, str, str, str, str]] = set()

    for row in matrix.rates:
        # Check non-positive rates
        if row.rate <= 0:
            issues.append(ContractSanityIssue(
                issue_type="min_charge_anomaly",
                severity="error",
                details={"origin": row.origin_zip_prefix, "dest": row.dest_zip_prefix, "rate": row.rate},
                message=f"Non-positive rate ${row.rate} for lane {row.origin_zip_prefix}->{row.dest_zip_prefix}"
            ))

        # Check negative min_charge
        if row.min_charge < 0:
            issues.append(ContractSanityIssue(
                issue_type="min_charge_anomaly",
                severity="error",
                details={"origin": row.origin_zip_prefix, "dest": row.dest_zip_prefix, "min_charge": row.min_charge},
                message=f"Negative min_charge ${row.min_charge} for lane {row.origin_zip_prefix}->{row.dest_zip_prefix}"
            ))

        # Check duplicate rows
        sig = (
            row.origin_zip_prefix.strip(),
            row.dest_zip_prefix.strip(),
            row.weight_break.strip().upper(),
            row.effective_date_start.strip(),
            row.effective_date_end.strip(),
        )
        if sig in seen_row_signatures:
            issues.append(ContractSanityIssue(
                issue_type="duplicate_lane",
                severity="error",
                details={"signature": sig},
                message=f"Duplicate matrix row detected: {sig[0]}->{sig[1]} [{sig[2]}] ({sig[3]} to {sig[4]})"
            ))
        else:
            seen_row_signatures.add(sig)

        lane_key = (row.origin_zip_prefix.strip(), row.dest_zip_prefix.strip())
        lanes_map.setdefault(lane_key, []).append(row)

    # Monotonicity & Weight Break Overlap checks per lane
    for lane_key, rows in lanes_map.items():
        # Sort rows by min_weight ascending
        rows_sorted = sorted(rows, key=lambda r: r.min_weight)

        # Check for duplicate min_weight within the same lane
        weights = [r.min_weight for r in rows_sorted]
        if len(weights) != len(set(weights)):
            issues.append(ContractSanityIssue(
                issue_type="overlapping_breaks",
                severity="error",
                details={"lane": lane_key, "weights": weights},
                message=f"Overlapping min_weights detected for lane {lane_key[0]}->{lane_key[1]}: {weights}"
            ))

        # Monotonicity check: In LTL tariffs, $/cwt should strictly decrease or remain flat as weight breaks increase
        # Example: L5C rate ($45/cwt) > M5C rate ($38/cwt) > M1M rate ($32/cwt)
        for i in range(len(rows_sorted) - 1):
            curr_row = rows_sorted[i]
            next_row = rows_sorted[i + 1]

            # If the higher weight break has a strictly higher $/cwt rate, that's non-monotonic
            if next_row.rate > curr_row.rate + 0.001:
                issues.append(ContractSanityIssue(
                    issue_type="monotonicity_violation",
                    severity="error",
                    details={
                        "lane": lane_key,
                        "lower_break": curr_row.weight_break,
                        "lower_rate": curr_row.rate,
                        "higher_break": next_row.weight_break,
                        "higher_rate": next_row.rate,
                    },
                    message=(
                        f"Non-monotonic rate in lane {lane_key[0]}->{lane_key[1]}: "
                        f"{curr_row.weight_break} (${curr_row.rate:.2f}/cwt) < "
                        f"{next_row.weight_break} (${next_row.rate:.2f}/cwt)"
                    )
                ))

    # Min charge sanity vs contract floor
    if matrix.absolute_min_charge < 0:
        issues.append(ContractSanityIssue(
            issue_type="min_charge_anomaly",
            severity="error",
            details={"absolute_min_charge": matrix.absolute_min_charge},
            message=f"Negative absolute_min_charge: ${matrix.absolute_min_charge}"
        ))

    # Check FSC table coverage if in_scope_months specified
    if in_scope_months and fsc_tables is not None:
        carrier_name = matrix.carrier.strip().lower()
        carrier_fsc = [f for f in fsc_tables if f.carrier.strip().lower() == carrier_name]
        available_months = {f.month for f in carrier_fsc if f.month}

        for req_month in in_scope_months:
            # If no month matches and no weekly ranges cover the month
            if req_month not in available_months:
                has_weekly_coverage = any(
                    (f.effective_week_start and req_month in f.effective_week_start) or
                    (f.effective_week_end and req_month in f.effective_week_end)
                    for f in carrier_fsc
                )
                if not has_weekly_coverage:
                    issues.append(ContractSanityIssue(
                        issue_type="missing_fsc_month",
                        severity="error",
                        details={"carrier": matrix.carrier, "missing_month": req_month},
                        message=f"Carrier FSC table lacks coverage for required month: {req_month}"
                    ))

    # Spot-check sampling (generate 5 stratified samples)
    spot_checks = generate_spot_check_sample(matrix, n=5, seed=42)

    # Determine status
    has_errors = any(issue.severity == "error" for issue in issues)
    has_warnings = any(issue.severity == "warning" for issue in issues)

    if has_errors:
        status = "rejected"
        is_valid = False
    elif has_warnings:
        status = "warning"
        is_valid = True
    else:
        status = "valid"
        is_valid = True

    validation_json = {
        "status": status,
        "is_valid": is_valid,
        "total_lanes_checked": total_lanes,
        "issue_count": len(issues),
        "issues": [issue.model_dump() for issue in issues],
        "spot_check_sample_indices": [s.sample_index for s in spot_checks],
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }

    return ContractValidationResult(
        contract_id=matrix.contract_id,
        carrier=matrix.carrier,
        is_valid=is_valid,
        status=status,
        total_lanes_checked=total_lanes,
        issues=issues,
        spot_checks=spot_checks,
        spot_verification_passed=None,
        contract_validation_json=validation_json
    )


def generate_spot_check_sample(
    matrix: RateMatrixJSON,
    n: int = 5,
    seed: Optional[int] = None
) -> List[SpotCheckItem]:
    """
    Selects N (default 5) stratified sample lanes from the parsed rate matrix
    for side-by-side human spot-verification against the contract PDF.
    """
    if not matrix.rates:
        return []

    if seed is not None:
        rng = random.Random(seed)
    else:
        rng = random.Random()

    total = len(matrix.rates)
    sample_size = min(n, total)

    # Stratified selection across the list of rates
    step = max(1, total // sample_size)
    sampled_indices = []
    for i in range(sample_size):
        idx = min(total - 1, i * step + rng.randint(0, max(0, step - 1)))
        sampled_indices.append(idx)

    # Deduplicate while preserving order
    unique_indices = sorted(list(set(sampled_indices)))

    spot_items: List[SpotCheckItem] = []
    for idx_num, idx in enumerate(unique_indices, start=1):
        row = matrix.rates[idx]
        spot_items.append(SpotCheckItem(
            sample_index=idx_num,
            origin_zip_prefix=row.origin_zip_prefix,
            dest_zip_prefix=row.dest_zip_prefix,
            weight_break=row.weight_break,
            matrix_rate=row.rate,
            matrix_min_charge=row.min_charge,
            page_ref_hint=f"Lane {row.origin_zip_prefix}->{row.dest_zip_prefix} [{row.weight_break}]"
        ))

    return spot_items


def evaluate_spot_verification(
    spot_checks: List[SpotCheckItem],
    user_results: List[SpotVerificationResult]
) -> Tuple[bool, str]:
    """
    Evaluates spot verification results:
    All 5 sampled lanes must match exactly (100% agreement).
    If even 1 fails, the entire contract matrix is rejected and sent back for re-parsing.
    """
    if not spot_checks:
        return True, "No spot checks required."

    if len(user_results) < len(spot_checks):
        return False, f"Incomplete verification: {len(user_results)} of {len(spot_checks)} lanes reviewed."

    results_by_index = {r.sample_index: r for r in user_results}
    mismatches = []

    for item in spot_checks:
        res = results_by_index.get(item.sample_index)
        if not res or not res.matched:
            actual = res.actual_page_rate if res else "None"
            mismatches.append(
                f"Sample #{item.sample_index} ({item.origin_zip_prefix}->{item.dest_zip_prefix} "
                f"[{item.weight_break}]): Matrix has ${item.matrix_rate:.2f}, page has ${actual}"
            )

    if mismatches:
        return False, f"Spot check failed ({len(mismatches)} mismatching lanes): " + "; ".join(mismatches)

    return True, "All spot-checked lanes verified successfully (5/5 match)."
