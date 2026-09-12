"""
RateGuard AI — Stripe Commission Service Unit Tests (Phase 6.2)
Tests monthly 35% / 40% commission invoicing, Revenue Integrity Guard, PyMuPDF vector PDF generation,
and denied dispute resend workflows.
"""

import os
import pytest
from apps.worker.stripe_commission import StripeCommissionService
from packages.schemas.models import UnverifiedMemoBillingError, CommissionInvoiceRecord


def test_generate_monthly_commission_invoice_success(tmp_path):
    """Verify monthly commission invoice calculation (35% standard fee, Net-15 due date)."""
    customer_id = "cust_acme_01"
    customer_name = "Acme Imports & Logistics"
    billing_period = "2026-09"

    verified_memos = [
        {
            "id": "memo_8812",
            "memo_number": "CM-8812",
            "carrier": "ABF Freight",
            "original_invoice_ref": "042-881234",
            "amount_dollars": 142.50,
            "amount_cents": 14250,
            "verification_status": "verified",
            "matched_dispute_id": "disp_abf_01",
        },
        {
            "id": "memo_5512",
            "memo_number": "CM-5512",
            "carrier": "XPO Logistics",
            "original_invoice_ref": "065-992143",
            "amount_dollars": 65.00,
            "amount_cents": 6500,
            "verification_status": "verified",
            "matched_dispute_id": "disp_xpo_02",
        },
    ]

    disputes_map = {
        "disp_abf_01": {"id": "disp_abf_01", "pro_number": "042-881234", "carrier": "ABF Freight"},
        "disp_xpo_02": {"id": "disp_xpo_02", "pro_number": "065-992143", "carrier": "XPO Logistics"},
    }

    record = StripeCommissionService.generate_monthly_commission_invoice(
        customer_id=customer_id,
        customer_name=customer_name,
        billing_period=billing_period,
        verified_memos=verified_memos,
        disputes_map=disputes_map,
        contingency_fee_pct=35.0,
    )

    assert record.customer_id == customer_id
    assert record.total_gross_credit_dollars == 207.50
    assert record.total_gross_credit_cents == 20750

    # 35% of $142.50 = $49.875 -> $49.88 ($4988 cents)
    # 35% of $65.00 = $22.75 ($2275 cents)
    # Total = $72.63 ($7263 cents)
    assert record.total_commission_cents == 7263
    assert record.total_commission_dollars == 72.63
    assert len(record.items) == 2
    assert record.status == "sent"


def test_unverified_memo_billing_error():
    """Verify Revenue Integrity Guard raises UnverifiedMemoBillingError when billing unverified memos."""
    unverified_memos = [
        {
            "id": "memo_unverified_01",
            "memo_number": "CM-UNVERIFIED",
            "carrier": "ABF Freight",
            "amount_dollars": 100.00,
            "amount_cents": 10000,
            "verification_status": "pending",  # NOT VERIFIED!
        }
    ]

    with pytest.raises(UnverifiedMemoBillingError) as exc_info:
        StripeCommissionService.generate_monthly_commission_invoice(
            customer_id="cust_test",
            customer_name="Test Customer",
            billing_period="2026-09",
            verified_memos=unverified_memos,
            disputes_map={},
        )

    assert "Revenue Integrity Violation" in str(exc_info.value)
    assert "CM-UNVERIFIED" in str(exc_info.value)


def test_vector_pdf_generation(tmp_path):
    """Verify vector PDF commission invoice generation using PyMuPDF."""
    customer_dir = tmp_path / "cust_acme_01"
    customer_dir.mkdir(parents=True, exist_ok=True)

    verified_memos = [
        {
            "id": "memo_8812",
            "memo_number": "CM-8812",
            "carrier": "ABF Freight",
            "original_invoice_ref": "042-881234",
            "amount_dollars": 142.50,
            "amount_cents": 14250,
            "verification_status": "verified",
            "matched_dispute_id": "disp_abf_01",
        }
    ]

    disputes_map = {
        "disp_abf_01": {"id": "disp_abf_01", "pro_number": "042-881234", "carrier": "ABF Freight"}
    }

    record = StripeCommissionService.generate_monthly_commission_invoice(
        customer_id="cust_acme_01",
        customer_name="Acme Imports & Logistics",
        billing_period="2026-09",
        verified_memos=verified_memos,
        disputes_map=disputes_map,
    )

    pdf_path = StripeCommissionService.render_commission_invoice_pdf(
        record=record, output_dir=str(tmp_path)
    )

    assert os.path.exists(pdf_path)
    assert os.path.getsize(pdf_path) > 1000  # Non-trivial PDF compiled


def test_concierge_40_percent_rate():
    """Verify concierge-handled disputes are billed at 40% contingency fee."""
    verified_memos = [
        {
            "id": "memo_concierge_01",
            "memo_number": "CM-CONCIERGE",
            "carrier": "Roadrunner",
            "original_invoice_ref": "RRTS-99",
            "amount_dollars": 100.00,
            "amount_cents": 10000,
            "verification_status": "verified",
            "matched_dispute_id": "disp_concierge",
        }
    ]

    disputes_map = {
        "disp_concierge": {
            "id": "disp_concierge",
            "pro_number": "RRTS-99",
            "carrier": "Roadrunner",
            "is_concierge_handled": True,  # 40% Concierge Fee
        }
    }

    record = StripeCommissionService.generate_monthly_commission_invoice(
        customer_id="cust_acme_01",
        customer_name="Acme Imports",
        billing_period="2026-09",
        verified_memos=verified_memos,
        disputes_map=disputes_map,
        contingency_fee_pct=35.0,  # Default 35%, but dispute overrides to 40%
    )

    assert record.items[0].commission_rate_pct == 40.0
    assert record.items[0].commission_dollars == 40.00
    assert record.total_commission_dollars == 40.00


def test_denied_dispute_resend_and_unrecoverable():
    """Verify 1-time automated resend task and transition to unrecoverable status on second denial."""
    dispute = {
        "id": "disp_denied_01",
        "customer_id": "cust_acme_01",
        "carrier": "XPO Logistics",
        "pro_number": "065-992143",
        "invoice_number": "XPO-5512",
        "overcharge_dollars": 65.00,
        "resend_count": 0,
        "status": "denied",
    }

    # First Denial -> Triggers Automated Resend
    res1 = StripeCommissionService.handle_denied_dispute(
        dispute=dispute,
        stronger_evidence_notes="Citing Item 220-A fuel scale table row #4.",
    )

    assert res1["action"] == "resent_with_evidence"
    assert dispute["resend_count"] == 1
    assert dispute["status"] == "resent_with_evidence"

    # Second Denial -> Transition to Unrecoverable ($0 fee)
    res2 = StripeCommissionService.handle_denied_dispute(
        dispute=dispute,
        stronger_evidence_notes="Carrier final denial after secondary review.",
    )

    assert res2["action"] == "marked_unrecoverable"
    assert dispute["status"] == "unrecoverable"
    assert res2["unrecoverable_record"]["overcharge_dollars"] == 65.00
