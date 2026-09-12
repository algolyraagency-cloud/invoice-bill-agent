"""
RateGuard AI — Credit Memo Detection & Verification Service (Phase 6.1)
Continuous stream scanner, forwarded email parser, and automated verification engine.

Revenue Integrity Guard:
Commission invoices can ONLY be generated from credit memos with verification_status='verified'
(PRD Flow A & Implementation §6.1).
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from packages.schemas.models import (
    CreditMemoDetectionCandidate,
    CreditMemoVerificationResult,
    CreditMemoListItem,
)

# Standardized Credit Memo keywords
CREDIT_MEMO_KEYWORDS = [
    "CREDIT MEMO",
    "CREDIT ADVICE",
    "STATEMENT OF ADJUSTMENT",
    "CREDIT BALANCE",
    "CREDIT NOTE",
    "REFUND CHECK",
    "OVERCHARGE ADJUSTMENT CREDIT",
]


class CreditMemoService:
    """Service handling stream detection, forwarded email parsing, and verification of carrier credit memos."""

    @staticmethod
    def is_credit_memo_text(text: str) -> bool:
        """Check if document text contains explicit credit memo markers."""
        upper_text = text.upper()
        return any(kw in upper_text for kw in CREDIT_MEMO_KEYWORDS)

    @classmethod
    def detect_credit_memos_from_stream(
        cls,
        parsed_invoice: Dict[str, Any],
        raw_text: Optional[str] = None,
        file_name: str = "",
    ) -> List[CreditMemoDetectionCandidate]:
        """Scans newly ingested invoices / documents for negative totals or credit memo patterns."""
        candidates: List[CreditMemoDetectionCandidate] = []

        total_cents = parsed_invoice.get("invoice_total_cents", 0)
        total_dollars = parsed_invoice.get("invoice_total", 0.0)
        if total_dollars == 0.0 and total_cents != 0:
            total_dollars = round(total_cents / 100.0, 2)

        carrier = parsed_invoice.get("carrier", "Unknown Carrier")
        inv_number = parsed_invoice.get("invoice_number", "")
        pro_number = parsed_invoice.get("pro_number", "")

        text_to_check = (raw_text or "") + " " + file_name
        has_keywords = cls.is_credit_memo_text(text_to_check)
        is_negative = total_cents < 0 or total_dollars < 0

        if is_negative or has_keywords:
            abs_cents = abs(total_cents) if total_cents != 0 else int(abs(total_dollars) * 100)
            abs_dollars = abs(total_dollars) if total_dollars != 0.0 else round(abs_cents / 100.0, 2)

            memo_num = inv_number if inv_number else f"CM-{abs_cents}"
            orig_ref = pro_number if pro_number else inv_number

            kind = "refund_check" if "CHECK" in text_to_check.upper() else "credit_memo"

            candidates.append(
                CreditMemoDetectionCandidate(
                    carrier=carrier,
                    memo_number=memo_num,
                    original_invoice_ref=orig_ref,
                    amount_cents=abs_cents,
                    amount_dollars=abs_dollars,
                    kind=kind,
                    detected_via="stream",
                    raw_text_snippet=text_to_check[:200] if text_to_check else None,
                    confidence_score=0.95 if (is_negative and has_keywords) else 0.85,
                )
            )

        return candidates

    @classmethod
    def detect_credit_memo_from_email(
        cls,
        email_subject: str,
        email_body: str,
        sender_email: str = "",
        carrier_hint: str = "",
    ) -> Optional[CreditMemoDetectionCandidate]:
        """Parses customer-forwarded carrier credit memo emails sent to disputes+{slug}@in.rateguard.app."""
        full_content = f"{email_subject} {email_body}".upper()
        if not cls.is_credit_memo_text(full_content) and "CREDIT" not in full_content and "ADJUSTMENT" not in full_content:
            return None

        # Extract Memo Number using Regex
        memo_match = re.search(r"(?:CM|CREDIT|MEMO|REF)[#:\s]*([A-Z0-9\-]{5,20})", full_content)
        memo_number = memo_match.group(1) if memo_match else f"CM-FWD-{int(datetime.now(timezone.utc).timestamp())}"

        # Extract Original Invoice / PRO reference
        pro_match = re.search(r"(?:PRO|INV|INVOICE|REF)[#:\s]*([A-Z0-9\-]{5,20})", full_content)
        original_ref = pro_match.group(1) if pro_match else memo_number

        # Extract Amount
        amt_match = re.search(r"\$\s*([\d,]+\.\d{2})", full_content)
        amount_dollars = float(amt_match.group(1).replace(",", "")) if amt_match else 0.0
        amount_cents = int(round(amount_dollars * 100))

        carrier = carrier_hint or "Unknown Carrier"
        if "ABF" in full_content or "ARCBEST" in full_content:
            carrier = "ABF Freight"
        elif "XPO" in full_content:
            carrier = "XPO Logistics"
        elif "ROADRUNNER" in full_content or "RRTS" in full_content:
            carrier = "Roadrunner"

        return CreditMemoDetectionCandidate(
            carrier=carrier,
            memo_number=memo_number,
            original_invoice_ref=original_ref,
            amount_cents=amount_cents,
            amount_dollars=amount_dollars,
            kind="credit_memo",
            detected_via="forwarded",
            raw_text_snippet=email_subject,
            confidence_score=0.90,
        )

    @classmethod
    def verify_credit_memo(
        cls,
        candidate: Dict[str, Any],
        active_disputes: List[Dict[str, Any]],
        amount_tolerance_dollars: float = 1.00,
    ) -> CreditMemoVerificationResult:
        """Matches credit memo candidate against open/sent disputes in disputes repository.

        Matches by:
        1. Carrier name alignment (case-insensitive substring match).
        2. Reference match (PRO number or original invoice number).
        3. Dollar amount match within tolerance (e.g. ±$1.00).

        Returns CreditMemoVerificationResult with status 'verified', 'pending', or 'rejected'.
        """
        memo_id = candidate.get("id", f"memo_{int(datetime.now(timezone.utc).timestamp())}")
        memo_carrier = (candidate.get("carrier") or "").lower().strip()
        memo_ref = (candidate.get("original_invoice_ref") or candidate.get("pro_number") or "").lower().strip()
        memo_amount = float(candidate.get("amount_dollars") or (candidate.get("amount_cents", 0) / 100.0))

        best_match: Optional[Dict[str, Any]] = None

        for dispute in active_disputes:
            disp_carrier = (dispute.get("carrier") or "").lower().strip()
            disp_pro = (dispute.get("pro_number") or "").lower().strip()
            disp_inv = (dispute.get("invoice_number") or "").lower().strip()
            disp_overcharge = float(dispute.get("overcharge_dollars") or (dispute.get("overcharge_cents", 0) / 100.0))

            # Check carrier alignment
            carrier_match = (
                memo_carrier in disp_carrier
                or disp_carrier in memo_carrier
                or ("abf" in memo_carrier and "abf" in disp_carrier)
                or ("xpo" in memo_carrier and "xpo" in disp_carrier)
                or ("roadrunner" in memo_carrier and "roadrunner" in disp_carrier)
            )

            if not carrier_match:
                continue

            # Check reference alignment
            ref_match = (
                (memo_ref and memo_ref in disp_pro)
                or (memo_ref and memo_ref in disp_inv)
                or (disp_pro and disp_pro in memo_ref)
                or (disp_inv and disp_inv in memo_ref)
            )

            if not ref_match:
                continue

            # Check dollar amount tolerance
            discrepancy = abs(disp_overcharge - memo_amount)
            if discrepancy <= amount_tolerance_dollars:
                best_match = dispute
                break

        now_iso = datetime.now(timezone.utc).isoformat()

        if best_match:
            disp_overcharge = float(best_match.get("overcharge_dollars") or (best_match.get("overcharge_cents", 0) / 100.0))
            discrepancy = abs(disp_overcharge - memo_amount)
            return CreditMemoVerificationResult(
                credit_memo_id=memo_id,
                verification_status="verified",
                matched_dispute_id=best_match.get("id"),
                carrier=candidate.get("carrier", "Carrier"),
                original_invoice_ref=candidate.get("original_invoice_ref", ""),
                memo_amount_dollars=memo_amount,
                dispute_amount_dollars=disp_overcharge,
                discrepancy_dollars=round(discrepancy, 2),
                verified_at=now_iso,
                notes=f"Matched dispute {best_match.get('id')} for PRO {best_match.get('pro_number')}",
            )
        else:
            return CreditMemoVerificationResult(
                credit_memo_id=memo_id,
                verification_status="rejected",
                matched_dispute_id=None,
                carrier=candidate.get("carrier", "Carrier"),
                original_invoice_ref=candidate.get("original_invoice_ref", ""),
                memo_amount_dollars=memo_amount,
                dispute_amount_dollars=None,
                discrepancy_dollars=0.0,
                verified_at=None,
                notes="No active dispute found matching carrier, reference PRO/Invoice number, and dollar amount tolerance.",
            )
