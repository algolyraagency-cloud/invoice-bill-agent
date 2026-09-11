"""
RateGuard AI — Phase 5.2: Dispute Letter Generator
Generates carrier dispute letters & batch packets ("We Draft, Shipper Sends"):
- Per-claim dispute notices citing exact contract clauses & overcharges
- 1-Click pre-encoded mailto: links (with carrier TO, disputes+{slug}@ CC, subject, body)
- Carrier batch packets consolidating multiple claims
- Vector PDF dispute notice generation via PyMuPDF (fitz)
- Dispute status state machine: drafted -> sent -> responded -> credit_issued | denied
"""

import os
import sys
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Ensure packages path is accessible
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from packages.schemas.models import (
    DisputeBatchPacket,
    DisputeLetterItem,
    DisputeStatus,
    ReviewQueueItem,
)

# Seeded default carrier contacts (mirroring DB carrier_contacts table)
DEFAULT_CARRIER_CONTACTS: Dict[str, Dict[str, str]] = {
    "ABF Freight": {
        "dispute_email": "freightbilling@abf.com",
        "billing_phone": "800-610-5544",
        "notes": "Requires PRO# in subject line",
    },
    "XPO Logistics": {
        "dispute_email": "ltlclaims@xpo.com",
        "billing_phone": "800-755-2728",
        "notes": "Credit memos issued within 10 business days",
    },
    "Roadrunner": {
        "dispute_email": "billingdisputes@rrts.com",
        "billing_phone": "800-435-0777",
        "notes": "Prefers invoice PDF attached with dispute",
    },
}

# Legal status transition table (PRD §5.6, §5.7)
VALID_STATUS_TRANSITIONS: Dict[str, List[str]] = {
    "drafted": ["sent"],
    "sent": ["responded", "credit_issued", "denied"],
    "responded": ["credit_issued", "denied", "sent"],  # 'sent' allows re-escalation with stronger evidence
    "credit_issued": [],  # Terminal
    "denied": ["sent"],    # Re-escalate once per PRD §5.7
}


def get_carrier_contact(carrier: str, override_contact: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Resolves carrier dispute contact with fallback."""
    if override_contact and override_contact.get("dispute_email"):
        return override_contact

    for cname, cinfo in DEFAULT_CARRIER_CONTACTS.items():
        if carrier.lower() in cname.lower() or cname.lower() in carrier.lower():
            return cinfo

    clean_name = carrier.lower().replace(" ", "").replace("-", "")
    return {
        "dispute_email": f"billing-disputes@{clean_name}.com",
        "billing_phone": "800-555-0100",
        "notes": "Standard LTL billing dispute intake",
    }


def transition_dispute_status(current_status: str, next_status: str) -> str:
    """
    Enforces the dispute state machine transitions:
    drafted -> sent -> responded -> credit_issued | denied
    Raises ValueError if transition is disallowed.
    """
    allowed_next = VALID_STATUS_TRANSITIONS.get(current_status)
    if allowed_next is None:
        raise ValueError(f"Unknown current dispute status: '{current_status}'")

    if next_status not in allowed_next:
        raise ValueError(
            f"Invalid dispute status transition: '{current_status}' -> '{next_status}'. "
            f"Allowed transitions from '{current_status}' are: {allowed_next}"
        )

    return next_status


def generate_dispute_letter(
    flag: Union[ReviewQueueItem, Dict[str, Any]],
    customer_name: str,
    customer_slug: str,
    carrier_contact: Optional[Dict[str, str]] = None,
) -> DisputeLetterItem:
    """
    Generates a single, professional dispute letter for an approved discrepancy.
    Produces:
    - Pre-formatted plain-text & HTML email body
    - Pre-encoded mailto: link for 1-click customer email launch
    - Exact contract clause references
    """
    if isinstance(flag, ReviewQueueItem):
        f = flag.model_dump()
    else:
        f = dict(flag)

    flag_id = str(f.get("id", f"flag-{uuid.uuid4().hex[:6]}"))
    invoice_id = str(f.get("invoice_id", f"inv-{uuid.uuid4().hex[:6]}"))
    carrier = str(f.get("carrier", "Carrier"))
    pro_number = str(f.get("pro_number", "PRO-UNKNOWN"))
    invoice_number = str(f.get("invoice_number", "INV-UNKNOWN"))
    invoice_date = str(f.get("invoice_date", datetime.now(timezone.utc).strftime("%Y-%m-%d")))
    check_type = str(f.get("check_type", "RATE"))

    overcharge_cents = int(f.get("overcharge_cents", 0))
    overcharge_dollars = round(overcharge_cents / 100.0, 2)

    billed_amount = float(f.get("invoice_total", 0.0))
    if billed_amount <= 0.0:
        billed_amount = float(f.get("evidence_json", {}).get("billed_amount", overcharge_dollars))

    contract_amount = float(f.get("evidence_json", {}).get("correct_amount", 0.0))
    if contract_amount <= 0.0:
        contract_amount = max(0.0, round(billed_amount - overcharge_dollars, 2))

    evidence_json = f.get("evidence_json", {})
    contract_clause = str(evidence_json.get("contract_clause", "Governing Tariff Schedule Rules & Provisions"))
    page_number = evidence_json.get("page_number")
    page_str = f" (Page {page_number})" if page_number else ""

    # Human-readable dispute reason text
    explanation = evidence_json.get("explanation")
    if not explanation:
        if check_type == "RATE":
            explanation = (
                f"The billed freight rate of ${billed_amount:,.2f} exceeded the contracted agreed lane rate "
                f"of ${contract_amount:,.2f} per {contract_clause}{page_str}. Resulting overcharge is ${overcharge_dollars:,.2f}."
            )
        elif check_type == "FSC":
            explanation = (
                f"Fuel surcharge calculation discrepancy: Applied surcharge does not match the published DOE/EIA "
                f"weekly on-highway diesel index scale for the shipment date under {contract_clause}{page_str}. "
                f"Overcharge discrepancy is ${overcharge_dollars:,.2f}."
            )
        elif check_type == "DUP":
            explanation = (
                f"Duplicate billing detected: Invoice #{invoice_number} duplicates prior billing for PRO #{pro_number} "
                f"under {contract_clause}. Full invoiced amount of ${overcharge_dollars:,.2f} is disputed."
            )
        elif check_type == "ARITH":
            explanation = (
                f"Arithmetic discrepancy: The itemized freight charges sum does not equal the invoice stated total "
                f"of ${billed_amount:,.2f}. Disputed difference is ${overcharge_dollars:,.2f}."
            )
        else:
            explanation = f"Discrepancy identified under {contract_clause}{page_str}. Disputed overcharge: ${overcharge_dollars:,.2f}."

    contact = get_carrier_contact(carrier, carrier_contact)
    carrier_dispute_email = contact["dispute_email"]
    carrier_phone = contact.get("billing_phone")

    cc_email = f"disputes+{customer_slug}@in.rateguard.app"
    email_subject = f"Billing Dispute: Invoice #{invoice_number} / PRO #{pro_number} — {customer_name}"

    now_iso = datetime.now(timezone.utc).isoformat()
    now_date_str = datetime.now(timezone.utc).strftime("%B %d, %Y")

    # Plain text email body
    email_body_text = f"""To: {carrier} Billing & Claims Department
Dispute Email: {carrier_dispute_email}
From: Accounts Payable, {customer_name}
Date: {now_date_str}
Subject: {email_subject}

Dear Billing Department,

We have audited carrier billing on freight invoice #{invoice_number} (PRO #{pro_number}) dated {invoice_date} and identified a confirmed overcharge discrepancy totaling ${overcharge_dollars:,.2f}.

DISPUTE PARTICULARS:
- Carrier: {carrier}
- Invoice Number: {invoice_number}
- PRO Tracking Number: {pro_number}
- Billing Date: {invoice_date}
- Billed Total: ${billed_amount:,.2f}
- Contract Rate: ${contract_amount:,.2f}
- Disputed Overcharge: ${overcharge_dollars:,.2f}
- Audit Category: {check_type}
- Governing Authority: {contract_clause}{page_str}

AUDIT FINDINGS & PROOF:
{explanation}

REQUESTED ACTION:
Pursuant to our contracted pricing agreement and standard industry billing practices, please issue an itemized Credit Memo in the amount of ${overcharge_dollars:,.2f} referencing original Invoice #{invoice_number} and PRO #{pro_number} within 30 days.

Please reply to this email or forward the credit memo documentation directly to:
{cc_email}

Thank you for your prompt attention to this reconciliation.

Sincerely,
Freight Accounts Payable
{customer_name}
"""

    # HTML formatted email body
    email_body_html = f"""
    <div style="font-family: Arial, sans-serif; font-size: 14px; color: #111; line-height: 1.5;">
      <p><strong>To:</strong> {carrier} Billing & Claims Department ({carrier_dispute_email})<br>
      <strong>From:</strong> Accounts Payable, {customer_name}<br>
      <strong>Date:</strong> {now_date_str}<br>
      <strong>Subject:</strong> {email_subject}</p>

      <p>Dear Billing Department,</p>

      <p>We have completed an audit of freight invoice <strong>#{invoice_number}</strong> (PRO <strong>#{pro_number}</strong>) dated {invoice_date} and identified a confirmed overcharge discrepancy totaling <strong>${overcharge_dollars:,.2f}</strong>.</p>

      <table style="width: 100%; max-width: 600px; border-collapse: collapse; margin: 16px 0; font-size: 13px;">
        <tr style="background: #f4f4f4;"><td style="padding: 6px 10px; border: 1px solid #ddd;"><strong>Carrier:</strong></td><td style="padding: 6px 10px; border: 1px solid #ddd;">{carrier}</td></tr>
        <tr><td style="padding: 6px 10px; border: 1px solid #ddd;"><strong>Invoice Number:</strong></td><td style="padding: 6px 10px; border: 1px solid #ddd;">{invoice_number}</td></tr>
        <tr style="background: #f4f4f4;"><td style="padding: 6px 10px; border: 1px solid #ddd;"><strong>PRO Number:</strong></td><td style="padding: 6px 10px; border: 1px solid #ddd;">{pro_number}</td></tr>
        <tr><td style="padding: 6px 10px; border: 1px solid #ddd;"><strong>Billed Amount:</strong></td><td style="padding: 6px 10px; border: 1px solid #ddd;">${billed_amount:,.2f}</td></tr>
        <tr style="background: #f4f4f4;"><td style="padding: 6px 10px; border: 1px solid #ddd;"><strong>Contract Rate:</strong></td><td style="padding: 6px 10px; border: 1px solid #ddd;">${contract_amount:,.2f}</td></tr>
        <tr style="background: #e8f5e9; font-weight: bold;"><td style="padding: 6px 10px; border: 1px solid #ddd; color: #2e7d32;">Disputed Overcharge:</td><td style="padding: 6px 10px; border: 1px solid #ddd; color: #2e7d32;">${overcharge_dollars:,.2f}</td></tr>
        <tr><td style="padding: 6px 10px; border: 1px solid #ddd;"><strong>Governing Clause:</strong></td><td style="padding: 6px 10px; border: 1px solid #ddd;">{contract_clause}{page_str}</td></tr>
      </table>

      <p><strong>Audit Finding:</strong><br>{explanation}</p>

      <p><strong>Requested Action:</strong><br>
      Please issue an itemized Credit Memo for <strong>${overcharge_dollars:,.2f}</strong> referencing Invoice #{invoice_number} and PRO #{pro_number} within 30 days. Reply to this email or send documentation to <a href="mailto:{cc_email}">{cc_email}</a>.</p>

      <p>Sincerely,<br>
      Freight Accounts Payable<br>
      <strong>{customer_name}</strong></p>
    </div>
    """

    # Build RFC 2368 compliant mailto URL
    mailto_params = {
        "cc": cc_email,
        "subject": email_subject,
        "body": email_body_text,
    }
    mailto_link = f"mailto:{carrier_dispute_email}?" + urllib.parse.urlencode(mailto_params, quote_via=urllib.parse.quote)

    dispute_id = str(f.get("dispute_id")) if f.get("dispute_id") else f"DISP-{datetime.now(timezone.utc).strftime('%Y%m')}-{uuid.uuid4().hex[:6].upper()}"
    status = str(f.get("status", "drafted"))

    return DisputeLetterItem(
        dispute_id=dispute_id,
        flag_id=flag_id,
        invoice_id=invoice_id,
        customer_id=str(f.get("customer_id", f"cust-{uuid.uuid4().hex[:6]}")),
        customer_name=customer_name,
        customer_slug=customer_slug,
        carrier=carrier,
        carrier_dispute_email=carrier_dispute_email,
        carrier_phone=carrier_phone,
        invoice_number=invoice_number,
        pro_number=pro_number,
        invoice_date=invoice_date,
        billed_amount=billed_amount,
        contract_amount=contract_amount,
        overcharge_dollars=overcharge_dollars,
        check_type=check_type,
        contract_clause=contract_clause + page_str,
        dispute_reason_text=str(explanation),
        evidence_details=evidence_json,
        status=status,
        letter_pdf_path=None,
        mailto_link=mailto_link,
        email_subject=email_subject,
        email_body_text=email_body_text,
        email_body_html=email_body_html,
        created_at=now_iso,
        updated_at=now_iso,
    )


def generate_carrier_dispute_batch(
    approved_flags: List[Union[ReviewQueueItem, Dict[str, Any]]],
    carrier: str,
    customer_name: str,
    customer_slug: str,
    carrier_contact: Optional[Dict[str, str]] = None,
) -> DisputeBatchPacket:
    """
    Consolidates multiple claims for a single carrier into an organized dispute package.
    Generates combined mailto: link for one-click transmission of all claims in the batch.
    """
    disputes: List[DisputeLetterItem] = []
    total_disputed_dollars = 0.0

    for raw_flag in approved_flags:
        if isinstance(raw_flag, ReviewQueueItem):
            flag_carrier = raw_flag.carrier
        else:
            flag_carrier = raw_flag.get("carrier", "")

        if carrier.lower() in flag_carrier.lower() or flag_carrier.lower() in carrier.lower():
            letter = generate_dispute_letter(
                flag=raw_flag,
                customer_name=customer_name,
                customer_slug=customer_slug,
                carrier_contact=carrier_contact,
            )
            disputes.append(letter)
            total_disputed_dollars += letter.overcharge_dollars

    total_disputed_dollars = round(total_disputed_dollars, 2)
    contact = get_carrier_contact(carrier, carrier_contact)
    carrier_dispute_email = contact["dispute_email"]
    cc_email = f"disputes+{customer_slug}@in.rateguard.app"

    pro_list_str = ", ".join([d.pro_number for d in disputes[:5]])
    if len(disputes) > 5:
        pro_list_str += f" (+{len(disputes) - 5} more)"

    batch_subject = f"Freight Billing Disputes ({len(disputes)} Claims) — Total ${total_disputed_dollars:,.2f} — {customer_name}"

    claim_bullet_points = ""
    for idx, d in enumerate(disputes, start=1):
        claim_bullet_points += (
            f"Claim #{idx} [PRO #{d.pro_number} / Inv #{d.invoice_number} / Date: {d.invoice_date}]:\n"
            f"  - Billed: ${d.billed_amount:,.2f} | Contract: ${d.contract_amount:,.2f} | Overcharge: ${d.overcharge_dollars:,.2f}\n"
            f"  - Category: {d.check_type} ({d.contract_clause})\n"
            f"  - Summary: {d.dispute_reason_text}\n\n"
        )

    batch_body_text = f"""To: {carrier} Billing & Dispute Department
Dispute Email: {carrier_dispute_email}
From: Accounts Payable, {customer_name}
Subject: {batch_subject}

Dear Billing Department,

We have audited freight invoices billed to {customer_name} and identified {len(disputes)} overcharge discrepancies totaling ${total_disputed_dollars:,.2f}.

SUMMARY OF DISPUTED CLAIMS:
{claim_bullet_points}
REQUESTED ACTION:
Please issue credit memos totaling ${total_disputed_dollars:,.2f} referencing the individual Invoice and PRO numbers detailed above within 30 days.

Please reply to this email or send confirmed credit memo documentation to:
{cc_email}

Thank you,
Freight Accounts Payable
{customer_name}
"""

    batch_mailto_params = {
        "cc": cc_email,
        "subject": batch_subject,
        "body": batch_body_text,
    }
    combined_mailto_link = f"mailto:{carrier_dispute_email}?" + urllib.parse.urlencode(batch_mailto_params, quote_via=urllib.parse.quote)

    return DisputeBatchPacket(
        carrier=carrier,
        carrier_dispute_email=carrier_dispute_email,
        customer_name=customer_name,
        customer_slug=customer_slug,
        disputes_count=len(disputes),
        total_disputed_dollars=total_disputed_dollars,
        disputes=disputes,
        combined_mailto_link=combined_mailto_link,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def render_dispute_pdf(letter: DisputeLetterItem) -> bytes:
    """
    Generates a formal, printable dispute notice PDF using PyMuPDF (fitz).
    Enforces professional freight audit dispute styling on shipper letterhead.
    """
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz

    doc = fitz.open()
    page_width, page_height = 612, 792
    margin = 44

    p = doc.new_page(width=page_width, height=page_height)

    # Shipper letterhead header
    p.insert_text(fitz.Point(margin, 52), letter.customer_name.upper(), fontsize=14, fontname="helv", color=(0.1, 0.1, 0.1))
    p.insert_text(fitz.Point(margin, 64), "FREIGHT ACCOUNTS PAYABLE & BILLING DISPUTES", fontsize=8, fontname="helv", color=(0.4, 0.4, 0.4))

    # Right side meta
    p.insert_text(fitz.Point(page_width - margin - 140, 52), f"Dispute Ref: {letter.dispute_id}", fontsize=8, fontname="helv", color=(0.3, 0.3, 0.3))
    p.insert_text(fitz.Point(page_width - margin - 140, 64), f"Date: {datetime.now(timezone.utc).strftime('%B %d, %Y')}", fontsize=8, fontname="helv", color=(0.3, 0.3, 0.3))

    p.draw_line(fitz.Point(margin, 74), fitz.Point(page_width - margin, 74), color=(0.8, 0.8, 0.8), width=1)

    # Carrier Addressee Box
    cy = 94
    p.insert_text(fitz.Point(margin, cy), "TO CARRIER BILLING DEPARTMENT:", fontsize=8, fontname="helv", color=(0.4, 0.4, 0.4))
    p.insert_text(fitz.Point(margin, cy + 14), letter.carrier, fontsize=11, fontname="helv", color=(0.1, 0.1, 0.1))
    p.insert_text(fitz.Point(margin, cy + 26), f"Dispute Intake Email: {letter.carrier_dispute_email}", fontsize=8, color=(0.3, 0.3, 0.3))
    if letter.carrier_phone:
        p.insert_text(fitz.Point(margin, cy + 36), f"Billing Phone: {letter.carrier_phone}", fontsize=8, color=(0.3, 0.3, 0.3))

    # Notice Title
    ny = 150
    p.draw_rect(fitz.Rect(margin, ny, page_width - margin, ny + 24), fill=(0.95, 0.95, 0.95))
    p.insert_text(fitz.Point(margin + 8, ny + 16), f"FORMAL NOTICE OF FREIGHT BILLING DISPUTE — PRO #{letter.pro_number}", fontsize=9, fontname="helv", color=(0.1, 0.1, 0.1))

    # Itemized details table
    ty = 186
    p.draw_rect(fitz.Rect(margin, ty, page_width - margin, ty + 120), color=(0.85, 0.85, 0.85), fill=(1, 1, 1), width=0.5)

    fields = [
        ("Carrier PRO Number:", letter.pro_number),
        ("Carrier Invoice Number:", letter.invoice_number),
        ("Billing Date:", letter.invoice_date),
        ("Discrepancy Category:", letter.check_type),
        ("Governing Contract Rule:", letter.contract_clause),
        ("Billed Amount:", f"${letter.billed_amount:,.2f}"),
        ("Contract Agreed Rate:", f"${letter.contract_amount:,.2f}"),
        ("DISPUTED OVERCHARGE:", f"${letter.overcharge_dollars:,.2f}"),
    ]

    for idx, (label, val) in enumerate(fields):
        ry = ty + 15 + idx * 13
        p.insert_text(fitz.Point(margin + 12, ry), label, fontsize=8, color=(0.4, 0.4, 0.4))
        if "DISPUTED" in label:
            p.insert_text(fitz.Point(margin + 170, ry), val, fontsize=8, fontname="helv", color=(0.04, 0.45, 0.3))
        else:
            p.insert_text(fitz.Point(margin + 170, ry), val, fontsize=8, fontname="helv", color=(0.1, 0.1, 0.1))

    # Audit Findings Narrative
    fy = 325
    p.insert_text(fitz.Point(margin, fy), "AUDIT FINDINGS & CONTRACTUAL JUSTIFICATION:", fontsize=9, fontname="helv", color=(0.1, 0.1, 0.1))
    
    rect_narrative = fitz.Rect(margin, fy + 8, page_width - margin, fy + 88)
    p.draw_rect(rect_narrative, color=(0.9, 0.9, 0.9), fill=(0.98, 0.98, 0.98), width=0.5)
    
    # Render text lines cleanly
    p.insert_textbox(rect_narrative, f"\n{letter.dispute_reason_text}", fontsize=8, color=(0.25, 0.25, 0.25))

    # Demand for Credit Memo
    dy = fy + 105
    p.insert_text(fitz.Point(margin, dy), "FORMAL DEMAND FOR CREDIT MEMORANDUM:", fontsize=9, fontname="helv", color=(0.1, 0.1, 0.1))
    demand_text = (
        f"In accordance with our contractual pricing terms, {letter.customer_name} hereby requests that {letter.carrier} "
        f"issue a formal Credit Memo in the amount of ${letter.overcharge_dollars:,.2f}. The credit memo must cite "
        f"original Invoice #{letter.invoice_number} and PRO #{letter.pro_number} and be transmitted within thirty (30) "
        f"calendar days to disputes+{letter.customer_slug}@in.rateguard.app."
    )
    rect_demand = fitz.Rect(margin, dy + 8, page_width - margin, dy + 70)
    p.draw_rect(rect_demand, color=(0.8, 0.92, 0.85), fill=(0.95, 0.98, 0.96), width=0.5)
    p.insert_textbox(rect_demand, f"\n{demand_text}", fontsize=8, color=(0.05, 0.42, 0.28))

    # Shipper Signature block
    sy = dy + 95
    p.insert_text(fitz.Point(margin, sy), "SUBMITTED BY:", fontsize=8, fontname="helv", color=(0.4, 0.4, 0.4))
    p.insert_text(fitz.Point(margin, sy + 14), f"Accounts Payable / Freight Recovery Department", fontsize=8, color=(0.2, 0.2, 0.2))
    p.insert_text(fitz.Point(margin, sy + 26), letter.customer_name, fontsize=8, fontname="helv", color=(0.1, 0.1, 0.1))
    p.insert_text(fitz.Point(margin, sy + 38), f"Email: disputes+{letter.customer_slug}@in.rateguard.app", fontsize=8, color=(0.3, 0.3, 0.3))

    # Footer
    p.draw_line(fitz.Point(margin, page_height - 35), fitz.Point(page_width - margin, page_height - 35), color=(0.85, 0.85, 0.85), width=0.5)
    p.insert_text(fitz.Point(margin, page_height - 24), "Document prepared for shipper transmission — RateGuard AI Freight Recovery", fontsize=7, color=(0.5, 0.5, 0.5))

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes
