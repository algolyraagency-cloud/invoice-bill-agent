"""
Deterministic Audit Engine Core for RateGuard AI (packages/audit-engine).
Pure functions. No LLM, no network, no clock.
Fully unit-testable.
"""
from datetime import datetime
from typing import List, Optional, Tuple

from packages.schemas.models import Flag, FSCEntry, InvoiceJSON, RateMatrixJSON, RateMatrixRow


def parse_date(date_str: str) -> datetime:
    """Parse YYYY-MM-DD string into datetime."""
    return datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")


def check_duplicates(invoice: InvoiceJSON, all_invoices: List[InvoiceJSON]) -> List[Flag]:
    """
    Check 1: Duplicate Detection.
    Flags invoices with identical carrier, pro number, and billed amount within a ±3-day window,
    or duplicate PRO number billing.
    """
    flags: List[Flag] = []
    inv_date = parse_date(invoice.invoice_date)

    for other in all_invoices:
        # Do not compare against self
        if other.invoice_number == invoice.invoice_number and other.pro_number == invoice.pro_number:
            continue

        same_carrier = other.carrier.strip().lower() == invoice.carrier.strip().lower()
        same_pro = other.pro_number.strip().lower() == invoice.pro_number.strip().lower()

        if same_carrier and same_pro:
            other_date = parse_date(other.invoice_date)
            # Only flag as duplicate if the other invoice is the original (earlier date, or same date with lower invoice #)
            # The prior/original invoice is never a duplicate of a future invoice.
            is_subsequent = (inv_date > other_date) or (inv_date == other_date and invoice.invoice_number > other.invoice_number)
            if not is_subsequent:
                continue

            date_diff_days = abs((inv_date - other_date).days)

            # If same PRO number billed within 30 days or identical amount in ±3 days
            is_amount_match = abs(other.invoice_total - invoice.invoice_total) < 0.01

            if is_amount_match or date_diff_days <= 30:
                overcharge_cents = int(round(invoice.invoice_total * 100))
                flags.append(Flag(
                    check_type="DUP",
                    overcharge_cents=overcharge_cents,
                    confidence=0.98 if is_amount_match else 0.90,
                    evidence_json={
                        "invoice_ref": invoice.invoice_number,
                        "carrier": invoice.carrier,
                        "pro_number": invoice.pro_number,
                        "duplicate_of_invoice": other.invoice_number,
                        "duplicate_of_date": other.invoice_date,
                        "billed_value": invoice.invoice_total,
                        "correct_value": 0.00,
                        "note": f"Duplicate billing of PRO #{invoice.pro_number} originally billed on {other.invoice_date} (Inv #{other.invoice_number})"
                    }
                ))
                break

    return flags


def check_arithmetic(invoice: InvoiceJSON) -> List[Flag]:
    """
    Check 7 (MVP Core): Arithmetic Reconciliation.
    Verifies that the sum of line items equals invoice_total.
    """
    flags: List[Flag] = []
    if not invoice.line_items:
        return flags

    calculated_total = sum(item.amount for item in invoice.line_items)
    diff = invoice.invoice_total - calculated_total

    # Allow 1 cent rounding difference
    if abs(diff) > 0.02 and diff > 0:
        overcharge_cents = int(round(diff * 100))
        flags.append(Flag(
            check_type="ARITH",
            overcharge_cents=overcharge_cents,
            confidence=1.00,
            evidence_json={
                "invoice_ref": invoice.invoice_number,
                "carrier": invoice.carrier,
                "contract_clause": "Standard Invoice Reconciliation Rule",
                "billed_value": round(invoice.invoice_total, 2),
                "correct_value": round(calculated_total, 2),
                "discrepancy": round(diff, 2),
                "note": f"Sum of line items (${calculated_total:.2f}) does not match total billed (${invoice.invoice_total:.2f})"
            }
        ))

    return flags


def match_lane_prefix(origin: str, dest: str, row: RateMatrixRow) -> int:
    """
    Returns prefix match score:
    2 = both 5-digit match
    1 = 3-digit prefix match
    0 = no match
    """
    clean_orig = origin.replace("-", "").strip()
    clean_dest = dest.replace("-", "").strip()
    clean_row_orig = row.origin_zip_prefix.replace("-", "").strip()
    clean_row_dest = row.dest_zip_prefix.replace("-", "").strip()

    orig_match = clean_orig.startswith(clean_row_orig)
    dest_match = clean_dest.startswith(clean_row_dest)

    if orig_match and dest_match:
        return len(clean_row_orig) + len(clean_row_dest)
    return 0


def select_effective_matrix(
    invoice_date_str: str,
    matrices: List[RateMatrixJSON]
) -> Optional[RateMatrixJSON]:
    """Select the rate matrix in effect on invoice_date."""
    inv_date = parse_date(invoice_date_str)

    for mat in matrices:
        start_str = mat.effective_dates.get("start")
        end_str = mat.effective_dates.get("end")
        if start_str and end_str:
            start_date = parse_date(start_str)
            end_date = parse_date(end_str)
            if start_date <= inv_date <= end_date:
                return mat
        elif not start_str and not end_str:
            return mat

    # Fallback to the first matrix if date range not specified
    return matrices[0] if matrices else None


def check_rates(invoice: InvoiceJSON, rate_matrix_versions: List[RateMatrixJSON]) -> List[Flag]:
    """
    Check 2: Rate Verification with Deficit Weight Bumping & 3-Digit Zip Prefix Matching.

    1. Selects rate matrix in effect on invoice date.
    2. Resolves lane by longest matching origin/dest zip prefix.
    3. Evaluates applicable weight breaks and deficit weight rating (bumping).
    4. Applies discount percentage and minimum charge floor.
    5. Flags overcharges if billed rate exceeds contracted rate.
    """
    flags: List[Flag] = []
    matrix = select_effective_matrix(invoice.invoice_date, rate_matrix_versions)
    if not matrix or not matrix.rates:
        return flags

    # Find matching lane rows
    matching_rows: List[Tuple[int, RateMatrixRow]] = []
    for row in matrix.rates:
        score = match_lane_prefix(invoice.origin_zip, invoice.dest_zip, row)
        if score > 0:
            matching_rows.append((score, row))

    if not matching_rows:
        return flags

    # Keep highest prefix match score
    highest_score = max(score for score, _ in matching_rows)
    lane_rows = [row for score, row in matching_rows if score == highest_score]

    # Sort lane rows by min_weight ascending
    lane_rows.sort(key=lambda r: r.min_weight)

    weight = invoice.billed_weight
    cwt = weight / 100.0

    # 1. Normal rating: find tier where min_weight <= weight
    applicable_row = None
    next_higher_row = None

    for i, row in enumerate(lane_rows):
        if weight >= row.min_weight:
            applicable_row = row
            next_higher_row = lane_rows[i + 1] if i + 1 < len(lane_rows) else None
        else:
            if next_higher_row is None:
                next_higher_row = row
            break

    if not applicable_row:
        applicable_row = lane_rows[0]

    # Calculate standard charge: rate * cwt
    standard_charge = applicable_row.rate * cwt

    # 2. Deficit weight bumping (Deficit Weight Rating / "As" Weight)
    # If customer qualifies for bumping and next break is cheaper, carrier must bill next break!
    best_charge = standard_charge
    bumped = False
    bumped_weight = weight

    if applicable_row.deficit_weight_eligible and next_higher_row and next_higher_row.min_weight > weight:
        bumped_cwt = next_higher_row.min_weight / 100.0
        potential_bump_charge = next_higher_row.rate * bumped_cwt
        if potential_bump_charge < standard_charge:
            best_charge = potential_bump_charge
            bumped = True
            bumped_weight = next_higher_row.min_weight

    # Apply contract discount %
    discount = matrix.discount_pct / 100.0
    net_charge = best_charge * (1.0 - discount)

    # Apply Absolute Minimum Charge (AMC) floor
    min_floor = max(applicable_row.min_charge, matrix.absolute_min_charge)
    contracted_base = max(net_charge, min_floor)

    # Compare against billed base freight (extract line item for freight or invoice total excluding FSC)
    freight_line = None
    for item in invoice.line_items:
        desc = item.description.lower()
        if "freight" in desc or "base" in desc or "linehaul" in desc:
            freight_line = item.amount
            break

    billed_base = freight_line if freight_line is not None else invoice.invoice_total

    diff = billed_base - contracted_base
    if diff > 1.00:  # Threshold > $1.00 to avoid rounding noise
        overcharge_cents = int(round(diff * 100))
        reason = "Deficit weight rating not applied" if bumped else "Billed lane rate exceeds contract tariff"
        flags.append(Flag(
            check_type="RATE",
            overcharge_cents=overcharge_cents,
            confidence=0.95,
            evidence_json={
                "invoice_ref": invoice.invoice_number,
                "carrier": invoice.carrier,
                "contract_clause": "Item 100 — Base Linehaul Rates & Deficit Weight Rule",
                "origin_zip": invoice.origin_zip,
                "dest_zip": invoice.dest_zip,
                "billed_weight": weight,
                "rated_weight": bumped_weight,
                "billed_value": round(billed_base, 2),
                "correct_value": round(contracted_base, 2),
                "deficit_weight_applied": bumped,
                "note": f"{reason}: Contract rate is ${contracted_base:.2f} (billed ${billed_base:.2f})"
            }
        ))

    return flags


def check_fsc(
    invoice: InvoiceJSON,
    fsc_tables: List[FSCEntry],
    eia_diesel_price: Optional[float] = None
) -> List[Flag]:
    """
    Check 3: Fuel Surcharge (FSC) Verification.

    1. Looks up the contracted FSC percentage for carrier based on DOE weekly diesel price or month.
    2. Recalculates expected FSC against base net freight.
    3. Flags discrepancies where billed FSC% exceeds contract schedule.
    """
    flags: List[Flag] = []
    if invoice.fsc_amount is None and invoice.fsc_pct is None:
        return flags

    carrier_name = invoice.carrier.strip().lower()
    carrier_fsc = [f for f in fsc_tables if f.carrier.strip().lower() == carrier_name]
    if not carrier_fsc:
        return flags

    matched_fsc_pct: Optional[float] = None

    # 1. Match via EIA diesel price bracket if available
    if eia_diesel_price is not None:
        for entry in carrier_fsc:
            if entry.min_diesel_price <= eia_diesel_price <= entry.max_diesel_price:
                matched_fsc_pct = entry.fsc_pct
                break

    # 2. Fallback to month matching if bracket not matched
    if matched_fsc_pct is None:
        inv_month = invoice.invoice_date[:7]
        for entry in carrier_fsc:
            if entry.month == inv_month:
                matched_fsc_pct = entry.fsc_pct
                break

    if matched_fsc_pct is None and carrier_fsc:
        matched_fsc_pct = carrier_fsc[0].fsc_pct

    if matched_fsc_pct is None:
        return flags

    # Check percentage discrepancy
    if invoice.fsc_pct is not None:
        pct_diff = invoice.fsc_pct - matched_fsc_pct
        if pct_diff > 0.4:  # Billed higher by >0.4%
            # Calculate overcharge amount
            base_amount = invoice.invoice_total - (invoice.fsc_amount or 0.0)
            correct_fsc = base_amount * (matched_fsc_pct / 100.0)
            billed_fsc = invoice.fsc_amount if invoice.fsc_amount is not None else (base_amount * (invoice.fsc_pct / 100.0))
            overcharge = billed_fsc - correct_fsc

            if overcharge > 0.50:
                flags.append(Flag(
                    check_type="FSC",
                    overcharge_cents=int(round(overcharge * 100)),
                    confidence=0.96,
                    evidence_json={
                        "invoice_ref": invoice.invoice_number,
                        "carrier": invoice.carrier,
                        "contract_clause": "Item 220-A (Fuel Surcharge Scale)",
                        "billed_fsc_pct": invoice.fsc_pct,
                        "correct_fsc_pct": matched_fsc_pct,
                        "billed_value": round(billed_fsc, 2),
                        "correct_value": round(correct_fsc, 2),
                        "diesel_benchmark": eia_diesel_price,
                        "note": f"Carrier billed {invoice.fsc_pct:.1f}% FSC; contract scale authorizes {matched_fsc_pct:.1f}%"
                    }
                ))

    return flags
