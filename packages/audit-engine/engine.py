"""
Deterministic Audit Engine Core for RateGuard AI (packages/audit-engine).
Pure functions. No LLM, no network, no clock.
Fully unit-testable.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from packages.schemas.models import Flag, FSCEntry, InvoiceJSON, RateMatrixJSON, RateMatrixRow

try:
    from fsc import get_fsc, get_active_eia_price
except ImportError:
    try:
        from .fsc import get_fsc, get_active_eia_price
    except ImportError:
        try:
            from packages.audit_engine.fsc import get_fsc, get_active_eia_price
        except ImportError:
            get_fsc = None
            get_active_eia_price = None


def parse_date(date_str: str) -> datetime:
    """Parse YYYY-MM-DD string into datetime."""
    return datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")


def check_duplicates(invoice: InvoiceJSON, all_invoices: List[InvoiceJSON]) -> List[Flag]:
    """
    Check 1: Duplicate Detection.
    Flags invoices with:
    1. Identical carrier and PRO number billed within a 30-day window.
    2. Identical carrier and Bill of Lading (BOL) number.
    3. Identical carrier, origin/dest zips, and billed amount within a ±3-day window.

    Ensures chronological directionality: The earlier invoice is the original;
    only the subsequent invoice is flagged as a duplicate rebill.
    """
    flags: List[Flag] = []
    inv_date = parse_date(invoice.invoice_date)

    for other in all_invoices:
        # Do not compare against self
        if other.invoice_number == invoice.invoice_number and other.pro_number == invoice.pro_number:
            continue

        same_carrier = other.carrier.strip().lower() == invoice.carrier.strip().lower()
        if not same_carrier:
            continue

        other_date = parse_date(other.invoice_date)
        # Chronological directionality: only flag if the other invoice is earlier,
        # or on the same date with lower invoice number (the prior original).
        is_subsequent = (inv_date > other_date) or (inv_date == other_date and invoice.invoice_number > other.invoice_number)
        if not is_subsequent:
            continue

        date_diff_days = abs((inv_date - other_date).days)
        same_pro = other.pro_number.strip().lower() == invoice.pro_number.strip().lower()

        # BOL matching (if both have BOL populated)
        same_bol = False
        if invoice.bol_number and other.bol_number:
            clean_bol = invoice.bol_number.strip().lower()
            clean_other_bol = other.bol_number.strip().lower()
            if len(clean_bol) >= 3 and clean_bol == clean_other_bol:
                same_bol = True

        is_amount_match = abs(other.invoice_total - invoice.invoice_total) < 0.01
        same_lane = (invoice.origin_zip[:3] == other.origin_zip[:3]) and (invoice.dest_zip[:3] == other.dest_zip[:3])

        is_duplicate = False
        dup_reason = ""

        if same_pro and date_diff_days <= 30:
            is_duplicate = True
            dup_reason = f"Duplicate billing of PRO #{invoice.pro_number} originally billed on {other.invoice_date} (Inv #{other.invoice_number})"
        elif same_bol:
            is_duplicate = True
            dup_reason = f"Duplicate billing for Bill of Lading (BOL #{invoice.bol_number}) originally billed on {other.invoice_date} (Inv #{other.invoice_number})"
        elif is_amount_match and same_lane and date_diff_days <= 3:
            is_duplicate = True
            dup_reason = f"Identical amount (${invoice.invoice_total:.2f}) on lane {invoice.origin_zip}->{invoice.dest_zip} billed within {date_diff_days} day(s) of original Inv #{other.invoice_number} ({other.invoice_date})"

        if is_duplicate:
            overcharge_cents = int(round(invoice.invoice_total * 100))
            flags.append(Flag(
                invoice_id=getattr(invoice, "id", None),
                check_type="DUP",
                overcharge_cents=overcharge_cents,
                confidence=0.98 if (is_amount_match or same_pro or same_bol) else 0.90,
                evidence_json={
                    "invoice_ref": invoice.invoice_number,
                    "carrier": invoice.carrier,
                    "contract_clause": "Rule 100-D (Duplicate Billing Prohibition)",
                    "page_number": None,
                    "pro_number": invoice.pro_number,
                    "bol_number": invoice.bol_number,
                    "duplicate_of_invoice": other.invoice_number,
                    "duplicate_of_date": other.invoice_date,
                    "billed_value": round(invoice.invoice_total, 2),
                    "correct_value": 0.00,
                    "overcharge_cents": overcharge_cents,
                    "note": dup_reason
                }
            ))
            break

    return flags


def check_arithmetic(invoice: InvoiceJSON) -> List[Flag]:
    """
    Check 7 (MVP Core): Arithmetic Reconciliation.
    Verifies that the sum of line items equals invoice_total within penny tolerance.
    """
    flags: List[Flag] = []
    if not invoice.line_items:
        return flags

    calculated_total = sum(item.amount for item in invoice.line_items)
    diff = invoice.invoice_total - calculated_total

    # Allow 2 cents rounding difference; only flag when carrier overbilled
    if diff > 0.02:
        overcharge_cents = int(round(diff * 100))
        flags.append(Flag(
            invoice_id=getattr(invoice, "id", None),
            check_type="ARITH",
            overcharge_cents=overcharge_cents,
            confidence=1.00,
            evidence_json={
                "invoice_ref": invoice.invoice_number,
                "carrier": invoice.carrier,
                "contract_clause": "Standard Invoice Reconciliation Rule",
                "page_number": None,
                "billed_value": round(invoice.invoice_total, 2),
                "correct_value": round(calculated_total, 2),
                "discrepancy": round(diff, 2),
                "overcharge_cents": overcharge_cents,
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
    bumped_rate = applicable_row.rate

    if applicable_row.deficit_weight_eligible and next_higher_row and next_higher_row.min_weight > weight:
        bumped_cwt = next_higher_row.min_weight / 100.0
        potential_bump_charge = next_higher_row.rate * bumped_cwt
        if potential_bump_charge < standard_charge:
            best_charge = potential_bump_charge
            bumped = True
            bumped_weight = next_higher_row.min_weight
            bumped_rate = next_higher_row.rate

    # 3. Apply contract discount %
    discount = matrix.discount_pct / 100.0
    net_charge = best_charge * (1.0 - discount)

    # 4. Apply Absolute Minimum Charge (AMC) floor
    min_floor = max(applicable_row.min_charge, matrix.absolute_min_charge)
    contracted_base = max(net_charge, min_floor)

    # 5. Extract billed base freight (extract line item for freight or invoice total excluding FSC and accessorials)
    freight_line = None
    for item in invoice.line_items:
        desc = item.description.lower()
        if "freight" in desc or "base" in desc or "linehaul" in desc:
            freight_line = item.amount
            break

    if freight_line is not None:
        billed_base = freight_line
    else:
        acc_total = sum(acc.amount for acc in invoice.accessorials)
        fsc_total = invoice.fsc_amount or 0.0
        billed_base = max(0.0, invoice.invoice_total - acc_total - fsc_total)
        if billed_base == 0.0:
            billed_base = invoice.invoice_total

    diff = billed_base - contracted_base
    if diff > 1.00:  # Threshold > $1.00 to avoid rounding noise
        overcharge_cents = int(round(diff * 100))
        reason = "Deficit weight rating not applied" if bumped else "Billed lane rate exceeds contract tariff"
        flags.append(Flag(
            invoice_id=getattr(invoice, "id", None),
            check_type="RATE",
            overcharge_cents=overcharge_cents,
            confidence=0.95,
            evidence_json={
                "invoice_ref": invoice.invoice_number,
                "carrier": invoice.carrier,
                "contract_clause": "Item 100 — Base Linehaul Rates & Deficit Weight Rule",
                "page_number": 4,
                "origin_zip": invoice.origin_zip,
                "dest_zip": invoice.dest_zip,
                "billed_weight": weight,
                "rated_weight": bumped_weight,
                "billed_rate": applicable_row.rate if not bumped else bumped_rate,
                "billed_value": round(billed_base, 2),
                "correct_value": round(contracted_base, 2),
                "overcharge_cents": overcharge_cents,
                "deficit_weight_applied": bumped,
                "note": f"{reason}: Contract rate is ${contracted_base:.2f} (billed ${billed_base:.2f})"
            }
        ))

    return flags


def check_fsc(
    invoice: InvoiceJSON,
    fsc_tables: Optional[List[FSCEntry]] = None,
    eia_diesel_price: Optional[float] = None,
    eia_indices: Optional[List[Dict[str, Any]]] = None
) -> List[Flag]:
    """
    Check 3: Fuel Surcharge (FSC) Verification.

    1. Looks up the contracted FSC percentage for carrier based on DOE weekly diesel price or month.
       Uses get_fsc engine if available.
    2. Recalculates expected FSC against base net freight (not total amount or accessorials).
    3. Flags discrepancies where billed FSC exceeds authorized contract schedule.
    """
    flags: List[Flag] = []
    if invoice.fsc_amount is None and invoice.fsc_pct is None:
        return flags

    fsc_tables = fsc_tables or []
    carrier_name = invoice.carrier.strip().lower()

    matched_fsc_pct: Optional[float] = None
    fsc_meta: Dict[str, Any] = {}

    # 1. Match via EIA diesel price bracket if provided directly
    if eia_diesel_price is not None and fsc_tables:
        carrier_fsc = [f for f in fsc_tables if f.carrier.strip().lower() == carrier_name]
        for entry in carrier_fsc:
            if entry.min_diesel_price <= eia_diesel_price <= entry.max_diesel_price:
                matched_fsc_pct = entry.fsc_pct
                fsc_meta = {"eia_diesel_price": eia_diesel_price, "source": "fsc_tables_bracket"}
                break

    # 2. Try deterministic get_fsc engine if not matched
    if matched_fsc_pct is None and get_fsc is not None:
        pct, meta = get_fsc(invoice.carrier, invoice.invoice_date, fsc_tables, eia_indices)
        if pct is not None:
            matched_fsc_pct = pct
            fsc_meta = meta or {}

    # 3. Fallback to month or carrier schedule match
    if matched_fsc_pct is None and fsc_tables:
        carrier_fsc = [f for f in fsc_tables if f.carrier.strip().lower() == carrier_name]
        inv_month = invoice.invoice_date[:7]
        for entry in carrier_fsc:
            if entry.month == inv_month:
                matched_fsc_pct = entry.fsc_pct
                fsc_meta = {"month": inv_month, "source": "monthly_scale"}
                break
        if matched_fsc_pct is None and carrier_fsc:
            matched_fsc_pct = carrier_fsc[0].fsc_pct
            fsc_meta = {"source": "carrier_fsc_default"}

    if matched_fsc_pct is None:
        return flags

    # Calculate net freight base: Fuel Surcharge is calculated on Net Linehaul,
    # NOT on accessorial charges or fuel itself.
    acc_total = sum(acc.amount for acc in invoice.accessorials)
    fsc_billed_amt = invoice.fsc_amount or 0.0

    freight_line = None
    for item in invoice.line_items:
        desc = item.description.lower()
        if "linehaul" in desc or "freight" in desc or "base" in desc:
            freight_line = item.amount
            break

    if freight_line is not None:
        net_freight = freight_line
    else:
        net_freight = invoice.invoice_total - fsc_billed_amt - acc_total
        if net_freight <= 0:
            net_freight = invoice.invoice_total - fsc_billed_amt

    # Recalculate correct FSC
    correct_fsc = round(net_freight * (matched_fsc_pct / 100.0), 2)
    billed_fsc = invoice.fsc_amount if invoice.fsc_amount is not None else round(net_freight * ((invoice.fsc_pct or 0.0) / 100.0), 2)
    overcharge = billed_fsc - correct_fsc

    # Check percentage discrepancy or dollar overcharge
    pct_discrepancy = (invoice.fsc_pct - matched_fsc_pct) if invoice.fsc_pct is not None else 0.0

    if (invoice.fsc_pct is not None and pct_discrepancy > 0.4) or (overcharge > 0.50):
        overcharge_cents = max(int(round(overcharge * 100)), 50)
        benchmark_used = eia_diesel_price or fsc_meta.get("eia_diesel_price")
        flags.append(Flag(
            invoice_id=getattr(invoice, "id", None),
            check_type="FSC",
            overcharge_cents=overcharge_cents,
            confidence=0.96,
            evidence_json={
                "invoice_ref": invoice.invoice_number,
                "carrier": invoice.carrier,
                "contract_clause": "Item 220-A (Fuel Surcharge Scale)",
                "page_number": 7,
                "billed_fsc_pct": invoice.fsc_pct,
                "correct_fsc_pct": matched_fsc_pct,
                "billed_value": round(billed_fsc, 2),
                "correct_value": round(correct_fsc, 2),
                "overcharge_cents": overcharge_cents,
                "diesel_benchmark": benchmark_used,
                "note": f"Carrier billed {invoice.fsc_pct if invoice.fsc_pct is not None else round(billed_fsc/net_freight*100, 1):.1f}% FSC (${billed_fsc:.2f}); contract scale authorizes {matched_fsc_pct:.1f}% (${correct_fsc:.2f})"
            }
        ))

    return flags


def check_accessorials(
    invoice: InvoiceJSON,
    rate_matrix_versions: Optional[List[RateMatrixJSON]] = None,
    approved_accessorials: Optional[Dict[str, float]] = None
) -> List[Flag]:
    """
    Check 5: Accessorial Audit.
    Verifies billed accessorial fees (Liftgate, Residential, Inside Delivery, Redelivery, etc.)
    against contract approved limits or authorization state.
    """
    flags: List[Flag] = []
    matrix = select_effective_matrix(invoice.invoice_date, rate_matrix_versions) if rate_matrix_versions else None
    
    # Combined contract approved accessorial rates (lowercased keys)
    contract_approved: Dict[str, float] = {}
    if approved_accessorials:
        contract_approved.update({k.lower(): float(v) for k, v in approved_accessorials.items()})
    if matrix and matrix.approved_accessorials:
        contract_approved.update({k.lower(): float(v) for k, v in matrix.approved_accessorials.items()})

    # 1. Audit structured accessorials list
    for acc in invoice.accessorials:
        acc_type_clean = acc.type.strip().lower()
        billed_amt = acc.amount

        # Case A: Unauthorized accessorial explicitly marked
        if acc.authorized is False:
            overcharge_cents = int(round(billed_amt * 100))
            if overcharge_cents > 0:
                flags.append(Flag(
                    invoice_id=getattr(invoice, "id", None),
                    check_type="ACCESSORIAL",
                    overcharge_cents=overcharge_cents,
                    confidence=0.98,
                    evidence_json={
                        "invoice_ref": invoice.invoice_number,
                        "carrier": invoice.carrier,
                        "contract_clause": "Item 550 — Accessorial Authorization Rule",
                        "page_number": 9,
                        "accessorial_type": acc.type,
                        "billed_value": round(billed_amt, 2),
                        "correct_value": 0.00,
                        "overcharge_cents": overcharge_cents,
                        "note": f"Unauthorized accessorial '{acc.type}' billed (${billed_amt:.2f})"
                    }
                ))
            continue

        # Case B: Exceeds approved contract rate limit
        if acc_type_clean in contract_approved:
            approved_rate = contract_approved[acc_type_clean]
            if billed_amt > approved_rate + 0.50:
                diff = billed_amt - approved_rate
                overcharge_cents = int(round(diff * 100))
                flags.append(Flag(
                    invoice_id=getattr(invoice, "id", None),
                    check_type="ACCESSORIAL",
                    overcharge_cents=overcharge_cents,
                    confidence=0.95,
                    evidence_json={
                        "invoice_ref": invoice.invoice_number,
                        "carrier": invoice.carrier,
                        "contract_clause": f"Item 550 — {acc.type.title()} Schedule Rate",
                        "page_number": 9,
                        "accessorial_type": acc.type,
                        "billed_value": round(billed_amt, 2),
                        "correct_value": round(approved_rate, 2),
                        "overcharge_cents": overcharge_cents,
                        "note": f"Billed {acc.type} (${billed_amt:.2f}) exceeds contracted rate (${approved_rate:.2f})"
                    }
                ))

    # 2. Audit line items for unapproved/overbilled accessorial charges
    for item in invoice.line_items:
        desc_clean = item.description.strip().lower()
        if any(keyword in desc_clean for keyword in ["liftgate", "residential", "inside delivery", "redelivery", "notification", "detention"]):
            matched_key = None
            for key in contract_approved:
                if key in desc_clean:
                    matched_key = key
                    break
            
            if matched_key:
                approved_rate = contract_approved[matched_key]
                if item.amount > approved_rate + 0.50:
                    diff = item.amount - approved_rate
                    overcharge_cents = int(round(diff * 100))
                    # Avoid duplicate flag if already covered in invoice.accessorials
                    already_flagged = any(f.check_type == "ACCESSORIAL" and f.evidence_json.get("billed_value") == round(item.amount, 2) for f in flags)
                    if not already_flagged:
                        flags.append(Flag(
                            invoice_id=getattr(invoice, "id", None),
                            check_type="ACCESSORIAL",
                            overcharge_cents=overcharge_cents,
                            confidence=0.94,
                            evidence_json={
                                "invoice_ref": invoice.invoice_number,
                                "carrier": invoice.carrier,
                                "contract_clause": f"Item 550 — Accessorial Line Item Schedule",
                                "page_number": 9,
                                "accessorial_type": item.description,
                                "billed_value": round(item.amount, 2),
                                "correct_value": round(approved_rate, 2),
                                "overcharge_cents": overcharge_cents,
                                "note": f"Billed line item '{item.description}' (${item.amount:.2f}) exceeds contract rate (${approved_rate:.2f})"
                            }
                        ))

    return flags


def check_reweigh_dimension(
    invoice: InvoiceJSON,
    bol_weight: Optional[float] = None,
    certified_reweigh: Optional[bool] = None
) -> List[Flag]:
    """
    Check 6: Reweigh & Dimension Discrepancy Audit.
    Flags unauthorized reweigh fees or uncertified weight increases (> 50 lbs over BOL weight).
    """
    flags: List[Flag] = []
    
    # 1. Check for explicit reweigh / inspection fee line items
    for item in invoice.line_items:
        desc_clean = item.description.strip().lower()
        if "reweigh" in desc_clean or "weight adjustment" in desc_clean or "weight inspection" in desc_clean:
            if certified_reweigh is False or certified_reweigh is None:
                overcharge_cents = int(round(item.amount * 100))
                if overcharge_cents > 0:
                    flags.append(Flag(
                        invoice_id=getattr(invoice, "id", None),
                        check_type="REWEIGH",
                        overcharge_cents=overcharge_cents,
                        confidence=0.96,
                        evidence_json={
                            "invoice_ref": invoice.invoice_number,
                            "carrier": invoice.carrier,
                            "contract_clause": "Item 140 — Reweigh & Weight Inspection Certification",
                            "page_number": 11,
                            "billed_weight": invoice.billed_weight,
                            "bol_weight": bol_weight or invoice.billed_weight,
                            "reweigh_fee": round(item.amount, 2),
                            "billed_value": round(item.amount, 2),
                            "correct_value": 0.00,
                            "overcharge_cents": overcharge_cents,
                            "note": f"Reweigh fee (${item.amount:.2f}) charged without attached weight verification certificate"
                        }
                    ))

    # 2. Check if billed weight exceeds BOL weight by > 50 lbs without certified reweigh doc
    if bol_weight is not None and invoice.billed_weight > bol_weight + 50.0:
        if certified_reweigh is False or certified_reweigh is None:
            # Check if we haven't already flagged the reweigh line item
            if not any(f.check_type == "REWEIGH" for f in flags):
                weight_diff = invoice.billed_weight - bol_weight
                # Estimated overcharge based on weight diff proportion or baseline penalty
                cwt_diff = weight_diff / 100.0
                estimated_overcharge = max(35.0, cwt_diff * 12.50)
                overcharge_cents = int(round(estimated_overcharge * 100))
                flags.append(Flag(
                    invoice_id=getattr(invoice, "id", None),
                    check_type="REWEIGH",
                    overcharge_cents=overcharge_cents,
                    confidence=0.92,
                    evidence_json={
                        "invoice_ref": invoice.invoice_number,
                        "carrier": invoice.carrier,
                        "contract_clause": "Item 140-B — Uncertified Weight Adjustment Restriction",
                        "page_number": 11,
                        "billed_weight": invoice.billed_weight,
                        "bol_weight": bol_weight,
                        "weight_diff_lbs": weight_diff,
                        "billed_value": round(invoice.invoice_total, 2),
                        "correct_value": round(invoice.invoice_total - estimated_overcharge, 2),
                        "overcharge_cents": overcharge_cents,
                        "note": f"Billed weight ({invoice.billed_weight:.1f} lbs) exceeds BOL weight ({bol_weight:.1f} lbs) by {weight_diff:.1f} lbs without scale certificate"
                    }
                ))

    return flags


def check_guaranteed_sla(
    invoice: InvoiceJSON,
    guaranteed_service: Optional[bool] = None,
    promised_delivery_date: Optional[str] = None,
    actual_delivery_date: Optional[str] = None
) -> List[Flag]:
    """
    Check 7: Guaranteed SLA & On-Time Delivery Audit.
    Flags late delivery on guaranteed shipments (100% money-back guarantee under Item 780).
    """
    flags: List[Flag] = []
    
    # Detect guaranteed service line item or argument
    guarantee_line_amount = 0.0
    for item in invoice.line_items:
        desc_clean = item.description.strip().lower()
        if "guaranteed" in desc_clean or "gsd" in desc_clean or "am delivery" in desc_clean:
            guarantee_line_amount += item.amount

    is_guaranteed = guaranteed_service or (guarantee_line_amount > 0.0)
    if not is_guaranteed:
        return flags

    # Check dates if provided
    if promised_delivery_date and actual_delivery_date:
        promised_dt = parse_date(promised_delivery_date)
        actual_dt = parse_date(actual_delivery_date)
        
        if actual_dt > promised_dt:
            # SLA Missed! Full money-back guarantee refund applies
            # Overcharge is guaranteed fee plus total freight or guaranteed fee amount
            refundable_amount = guarantee_line_amount if guarantee_line_amount > 0.0 else invoice.invoice_total
            overcharge_cents = int(round(refundable_amount * 100))
            flags.append(Flag(
                invoice_id=getattr(invoice, "id", None),
                check_type="GUARANTEE",
                overcharge_cents=overcharge_cents,
                confidence=0.99,
                evidence_json={
                    "invoice_ref": invoice.invoice_number,
                    "carrier": invoice.carrier,
                    "contract_clause": "Item 780 — Guaranteed Service Money-Back Guarantee",
                    "page_number": 14,
                    "promised_delivery_date": promised_delivery_date,
                    "actual_delivery_date": actual_delivery_date,
                    "billed_value": round(invoice.invoice_total, 2),
                    "correct_value": round(max(0.0, invoice.invoice_total - refundable_amount), 2),
                    "overcharge_cents": overcharge_cents,
                    "note": f"Guaranteed delivery missed: promised {promised_delivery_date}, actual delivery {actual_delivery_date}. 100% refund of ${refundable_amount:.2f}"
                }
            ))

    return flags


def check_freight_tax(
    invoice: InvoiceJSON,
    is_interstate: Optional[bool] = None
) -> List[Flag]:
    """
    Check 8: Freight Transportation Tax Audit.
    Flags sales/transportation taxes billed on tax-exempt interstate freight shipments.
    """
    flags: List[Flag] = []
    
    # Determine interstate status: different zip prefixes or explicit param
    orig_prefix = invoice.origin_zip[:3] if invoice.origin_zip else ""
    dest_prefix = invoice.dest_zip[:3] if invoice.dest_zip else ""
    interstate = is_interstate if is_interstate is not None else (orig_prefix != dest_prefix)

    if not interstate:
        return flags

    # Inspect line items for tax charges
    for item in invoice.line_items:
        desc_clean = item.description.strip().lower()
        if any(keyword in desc_clean for keyword in ["sales tax", "state tax", "transportation tax", "gst", "hst", "tax charge"]):
            tax_amount = item.amount
            if tax_amount > 0.0:
                overcharge_cents = int(round(tax_amount * 100))
                flags.append(Flag(
                    invoice_id=getattr(invoice, "id", None),
                    check_type="TAX",
                    overcharge_cents=overcharge_cents,
                    confidence=0.98,
                    evidence_json={
                        "invoice_ref": invoice.invoice_number,
                        "carrier": invoice.carrier,
                        "contract_clause": "IRC Sec. 4271 & State Tax Exemption for Interstate Commerce",
                        "page_number": 2,
                        "origin_zip": invoice.origin_zip,
                        "dest_zip": invoice.dest_zip,
                        "tax_description": item.description,
                        "billed_value": round(tax_amount, 2),
                        "correct_value": 0.00,
                        "overcharge_cents": overcharge_cents,
                        "note": f"Tax line item '{item.description}' (${tax_amount:.2f}) billed on tax-exempt interstate shipment"
                    }
                ))

    return flags


