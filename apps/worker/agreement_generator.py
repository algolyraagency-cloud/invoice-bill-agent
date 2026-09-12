"""
RateGuard AI — Phase 5.4: 1-Page Recovery Agreement Generator & Launch Gate
Generates formal contingency audit & recovery contracts ("We Draft, Shipper Sends"):
- Plain text & HTML formal contract terms
- 1-Page Vector PDF agreement generation via PyMuPDF (fitz)
- E-signature handling with typed full name, title, timestamp, and audit trail
- Hard Code Gate (`verify_recovery_agreement_gate`) blocking dispute export until signed
"""

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

# Ensure root directory is accessible
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import pymupdf as fitz
from packages.schemas.models import (
    RecoveryAgreementRecord,
    RecoveryAgreementRequiredError,
    RecoveryAgreementSignInput,
)


def render_recovery_agreement_text(
    customer_name: str,
    signer_name: Optional[str] = None,
    signer_title: Optional[str] = None,
    signed_at: Optional[str] = None,
    concierge_handling: bool = False,
) -> str:
    """
    Renders standard 1-page contingency freight audit agreement plain text (PRD §5.4).
    """
    fee_pct = 40.0 if concierge_handling else 35.0
    date_str = signed_at[:10] if signed_at else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sig_name = signer_name or "[PENDING E-SIGNATURE]"
    sig_title = signer_title or "[PENDING TITLE]"
    sig_status = f"EXECUTED via E-Signature on {signed_at}" if signed_at else "UNSIGNED DRAFT — PENDING EXECUTION"

    return f"""================================================================================
RATEGUARD AI — FREIGHT AUDIT & RECOVERY CONTINGENCY AGREEMENT
================================================================================
PARTIES:
  Provider: RateGuard AI Inc. ("RateGuard")
  Client:   {customer_name} ("Shipper")
  Date:     {date_str}

1. PURPOSE & SCOPE OF ENGAGEMENT
Shipper engages RateGuard to audit freight billing, carrier rate tariffs, fuel surcharges, 
and accessorial charges across Shipper's LTL carrier invoice stream.

2. CONTINGENCY PRICING & PAYMENT TERMS (NO RECOVERY = ZERO OWED)
  (a) Contingency Fee: Shipper agrees to pay RateGuard {fee_pct:.1f}% of all verified overcharge recoveries, credit memos, or refund checks issued by carriers.
  (b) Billing Trigger: RateGuard invoices Shipper upon carrier issuance of a verified credit memo 
      or refund check ("Memo-Basis Trigger"), regardless of cash flow application.
  (c) Payment Terms: Net-15 days from date of RateGuard commission invoice.

3. DISPUTE MECHANISM — "WE DRAFT, YOU SEND"
  (a) RateGuard prepares mathematically verified dispute notices citing exact carrier contract 
      clauses and overcharges.
  (b) RateGuard shall not act as a direct legal party or communicate directly with carriers 
      without Shipper involvement. Shipper dispatches dispute notices directly to carriers.
  (c) All dispute email correspondence shall CC disputes+slug@in.rateguard.app for status tracking.

4. CONFIDENTIALITY & DATA SECURITY
RateGuard agrees to maintain strict confidentiality of Shipper's rate contracts, lane volumes, 
and invoice documentation in accordance with SOC-2 guidelines. Data shall never be sold or shared.

5. EXECUTION & ACKNOWLEDGEMENT
By checking the agreement box and submitting e-signature, the undersigned officer certifies 
authority to bind Shipper to this 1-page contingency recovery agreement.

STATUS: {sig_status}
SIGNER NAME: {sig_name}
SIGNER TITLE: {sig_title}
SIGNATURE TIMESTAMP: {signed_at or "N/A"}
AGREEMENT REF: AGR-{uuid.uuid4().hex[:8].upper()}
================================================================================"""


def render_recovery_agreement_pdf(
    customer_name: str,
    signer_name: str,
    signer_title: str,
    signed_at: str,
    concierge_handling: bool = False,
    output_dir: Optional[str] = None,
) -> Tuple[bytes, str]:
    """
    Generates a 1-page vector PDF agreement via PyMuPDF (fitz) with formal header,
    legal terms boxes, and e-signature audit stamp.
    """
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)  # Standard Letter 8.5 x 11 inches

    # Colors
    primary_color = (0.05, 0.05, 0.05)       # Charcoal / Near-black
    brand_blue = (0.10, 0.35, 0.75)          # Deep blue
    accent_emerald = (0.05, 0.55, 0.30)      # Emerald green
    neutral_bg = (0.96, 0.96, 0.97)          # Light grey
    text_dark = (0.12, 0.12, 0.12)           # Main text
    text_muted = (0.40, 0.40, 0.40)          # Muted subtext

    # Header rectangle
    page.draw_rect(fitz.Rect(36, 36, 576, 110), color=brand_blue, fill=brand_blue)
    page.insert_text(fitz.Point(52, 65), "RATEGUARD AI", fontsize=18, color=(1, 1, 1), fontname="helv")
    page.insert_text(fitz.Point(52, 85), "Freight Audit & Recovery Contingency Agreement", fontsize=12, color=(0.9, 0.95, 1.0), fontname="helv")
    page.insert_text(fitz.Point(430, 65), "1-PAGE CONTRACT", fontsize=10, color=(1, 1, 1), fontname="helv")
    page.insert_text(fitz.Point(430, 82), f"Date: {signed_at[:10]}", fontsize=9, color=(0.9, 0.9, 0.9), fontname="helv")

    # Parties Box
    page.draw_rect(fitz.Rect(36, 120, 576, 165), color=(0.85, 0.85, 0.85), fill=neutral_bg)
    page.insert_text(fitz.Point(50, 138), "PROVIDER:", fontsize=9, color=text_muted, fontname="helv")
    page.insert_text(fitz.Point(115, 138), "RateGuard AI Inc. (Concierge Audit Division)", fontsize=9, color=text_dark, fontname="helv")
    page.insert_text(fitz.Point(50, 153), "CLIENT:", fontsize=9, color=text_muted, fontname="helv")
    page.insert_text(fitz.Point(115, 153), f"{customer_name} ('Shipper')", fontsize=9, color=text_dark, fontname="helv")

    # Terms Section
    fee_pct = 40.0 if concierge_handling else 35.0
    terms = [
        ("1. SCOPE OF AUDIT", "Shipper engages RateGuard AI to audit carrier freight bills, rate tariffs, fuel surcharges (FSC), and accessorials across Shipper's LTL carrier invoice stream."),
        ("2. CONTINGENCY PRICING & PAYMENT TERMS", f"• Contingency Fee: Shipper agrees to pay RateGuard {fee_pct:.1f}% of all verified overcharge recoveries, credit memos, or refund checks.\n• Billing Trigger: RateGuard invoices upon carrier credit memo issuance ('Memo-Basis Trigger').\n• Payment Terms: Net-15 days from date of RateGuard commission invoice."),
        ("3. 'WE DRAFT, YOU SEND' DISPUTE MECHANISM", "RateGuard prepares mathematically verified dispute notices citing exact contract tariffs. RateGuard never acts as a direct legal party. Shipper dispatches dispute notices directly from Shipper's AP email client with CC tracking."),
        ("4. CONFIDENTIALITY & DATA SECURITY", "RateGuard maintains strict confidentiality of Shipper's rate contracts, lane volumes, and freight documents under SOC-2 security protocols."),
    ]

    y_pos = 180
    for title, text in terms:
        page.insert_text(fitz.Point(36, y_pos), title, fontsize=10, color=brand_blue, fontname="helv")
        y_pos += 14
        
        # Multiline text insertion
        rect = fitz.Rect(36, y_pos, 576, y_pos + 45)
        page.insert_textbox(rect, text, fontsize=8.5, color=text_dark, fontname="helv", align=0)
        y_pos += (35 if "\n" not in text else 45)

    # E-Signature Box (Bottom)
    page.draw_rect(fitz.Rect(36, 610, 576, 735), color=accent_emerald, fill=(0.95, 0.99, 0.96), width=1.5)
    page.insert_text(fitz.Point(50, 630), "OFFICIAL E-SIGNATURE ACKNOWLEDGEMENT & EXECUTION", fontsize=10, color=accent_emerald, fontname="helv")
    page.insert_text(fitz.Point(50, 646), "By typing full name and checking the agreement box, the undersigned officer certifies legal authority to bind Shipper.", fontsize=8, color=text_muted, fontname="helv")

    page.draw_line(fitz.Point(50, 656), fitz.Point(562, 656), color=(0.8, 0.8, 0.8))

    page.insert_text(fitz.Point(50, 675), "SIGNER FULL NAME:", fontsize=9, color=text_muted, fontname="helv")
    page.insert_text(fitz.Point(160, 675), signer_name, fontsize=10, color=text_dark, fontname="helv")

    page.insert_text(fitz.Point(50, 692), "CORPORATE TITLE:", fontsize=9, color=text_muted, fontname="helv")
    page.insert_text(fitz.Point(160, 692), signer_title, fontsize=10, color=text_dark, fontname="helv")

    page.insert_text(fitz.Point(50, 709), "EXECUTED AT:", fontsize=9, color=text_muted, fontname="helv")
    page.insert_text(fitz.Point(160, 709), f"{signed_at} (UTC)", fontsize=9, color=text_dark, fontname="helv")

    page.insert_text(fitz.Point(50, 725), "STATUS:", fontsize=9, color=text_muted, fontname="helv")
    page.insert_text(fitz.Point(160, 725), "EXECUTED & VERIFIED (35% CONTINGENCY NET-15 ACTIVE)", fontsize=9, color=accent_emerald, fontname="helv")

    # Footer
    page.insert_text(fitz.Point(36, 760), "RateGuard AI Inc. • 1-Page Contingency Recovery Contract • Document ID: AGR-202609-001", fontsize=8, color=text_muted, fontname="helv")

    pdf_bytes = doc.tobytes()
    doc.close()

    # Save to output_dir if specified
    out_path = ""
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        filename = f"recovery_agreement_{uuid.uuid4().hex[:8]}.pdf"
        out_path = str(Path(output_dir) / filename)
        with open(out_path, "wb") as f:
            f.write(pdf_bytes)

    return pdf_bytes, out_path


def verify_recovery_agreement_gate(customer_record: Dict[str, Any]) -> bool:
    """
    Hard Code Gate (PRD Flow A & Implementation §5.4):
    Verifies if customer has signed the 1-page recovery agreement.
    If unsigned, raises RecoveryAgreementRequiredError blocking dispute generation/export.
    """
    signed_at = customer_record.get("recovery_agreement_signed_at")
    if not signed_at:
        customer_name = customer_record.get("name", "Customer")
        raise RecoveryAgreementRequiredError(customer_name=customer_name)
    return True
