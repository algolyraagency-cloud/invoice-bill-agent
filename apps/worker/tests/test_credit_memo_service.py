"""
RateGuard AI — Credit Memo Service Unit Tests (Phase 6.1)
Tests stream detection, forwarded email parsing, and automated matching & verification.
"""

import pytest
from apps.worker.credit_memo_service import CreditMemoService
from packages.schemas.models import CreditMemoDetectionCandidate, CreditMemoVerificationResult


def test_stream_detection_negative_total():
    """Verify stream scanner detects credit memo candidates when invoice total is negative."""
    parsed_inv = {
        "carrier": "ABF Freight",
        "invoice_number": "CM-ABF-9090",
        "pro_number": "042-881234",
        "invoice_total": -142.50,
        "invoice_total_cents": -14250,
    }

    candidates = CreditMemoService.detect_credit_memos_from_stream(parsed_inv, raw_text="OVERCHARGE ADJUSTMENT CREDIT")

    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.carrier == "ABF Freight"
    assert cand.memo_number == "CM-ABF-9090"
    assert cand.amount_dollars == 142.50
    assert cand.amount_cents == 14250
    assert cand.detected_via == "stream"
    assert cand.confidence_score >= 0.85


def test_stream_detection_credit_keywords():
    """Verify stream scanner detects credit memo candidates via explicit text keywords."""
    parsed_inv = {
        "carrier": "XPO Logistics",
        "invoice_number": "XPO-CM-01",
        "pro_number": "065-992143",
        "invoice_total": 65.00,
        "invoice_total_cents": 6500,
    }

    candidates = CreditMemoService.detect_credit_memos_from_stream(
        parsed_inv, raw_text="CARRIER STATEMENT OF ADJUSTMENT - CREDIT MEMO ISSUED FOR PRO 065-992143"
    )

    assert len(candidates) == 1
    assert candidates[0].carrier == "XPO Logistics"
    assert candidates[0].memo_number == "XPO-CM-01"


def test_forwarded_email_detection():
    """Verify forwarded email parser extracts credit memo candidate details from email content."""
    subject = "Fwd: Credit Memo CM-8812 for PRO 042-881234"
    body = "Here is the credit memo from ABF Freight in the amount of $142.50."

    candidate = CreditMemoService.detect_credit_memo_from_email(
        email_subject=subject, email_body=body, sender_email="ap@acme.com"
    )

    assert candidate is not None
    assert candidate.carrier == "ABF Freight"
    assert candidate.memo_number == "CM-8812"
    assert candidate.amount_dollars == 142.50

    assert candidate.detected_via == "forwarded"


def test_verification_matching_success():
    """Verify automated verification engine matches candidate against active disputes."""
    candidate = {
        "id": "memo_101",
        "carrier": "ABF Freight",
        "original_invoice_ref": "042-881234",
        "amount_dollars": 142.50,
        "amount_cents": 14250,
    }

    active_disputes = [
        {
            "id": "disp_abf_01",
            "carrier": "ABF Freight",
            "pro_number": "042-881234",
            "invoice_number": "ABF-9021",
            "overcharge_dollars": 142.50,
            "overcharge_cents": 14250,
        }
    ]

    res = CreditMemoService.verify_credit_memo(candidate, active_disputes)

    assert res.verification_status == "verified"
    assert res.matched_dispute_id == "disp_abf_01"
    assert res.discrepancy_dollars == 0.0
    assert res.verified_at is not None


def test_verification_matching_rejection():
    """Verify automated verification engine rejects candidate when no matching dispute exists."""
    candidate = {
        "id": "memo_102",
        "carrier": "Roadrunner",
        "original_invoice_ref": "PRO-UNKNOWN",
        "amount_dollars": 999.00,
        "amount_cents": 99900,
    }

    active_disputes = [
        {
            "id": "disp_abf_01",
            "carrier": "ABF Freight",
            "pro_number": "042-881234",
            "invoice_number": "ABF-9021",
            "overcharge_dollars": 142.50,
        }
    ]

    res = CreditMemoService.verify_credit_memo(candidate, active_disputes)

    assert res.verification_status == "rejected"
    assert res.matched_dispute_id is None
    assert "No active dispute found" in res.notes
