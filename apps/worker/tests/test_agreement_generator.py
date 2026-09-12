"""
RateGuard AI — Unit Tests for 1-Page Recovery Agreement Generator & Launch Gate (Phase 5.4).
Verifies:
- Plain text contract terms rendering (35% contingency, Net-15 terms, "we draft, customer sends")
- Vector PDF rendering via PyMuPDF (fitz)
- E-signature agreement execution
- Hard Code Gate (`verify_recovery_agreement_gate`) blocking dispute exports when unsigned
"""

import os
import pytest
from apps.worker.agreement_generator import (
    render_recovery_agreement_pdf,
    render_recovery_agreement_text,
    verify_recovery_agreement_gate,
)
from packages.schemas.models import RecoveryAgreementRequiredError
from apps.worker.portal_service import CustomerPortalService


def test_render_recovery_agreement_text():
    """Verifies plain text contract terms contain all key PRD clauses."""
    text = render_recovery_agreement_text(customer_name="Acme Imports & Logistics")
    assert "Acme Imports & Logistics" in text
    assert "35.0% of all verified overcharge recoveries" in text
    assert "Memo-Basis Trigger" in text
    assert "Net-15 days" in text
    assert "WE DRAFT, YOU SEND" in text
    assert "RateGuard shall not act as a direct legal party" in text


def test_render_recovery_agreement_pdf(tmp_path):
    """Verifies vector PDF rendering via PyMuPDF (fitz)."""
    pdf_bytes, pdf_path = render_recovery_agreement_pdf(
        customer_name="Pacific Supply Corp",
        signer_name="Jane Doe",
        signer_title="Chief Financial Officer",
        signed_at="2026-09-12T14:30:00Z",
        output_dir=str(tmp_path),
    )

    assert pdf_bytes is not None
    assert len(pdf_bytes) > 2000
    assert os.path.exists(pdf_path)
    assert pdf_bytes.startswith(b"%PDF")


def test_recovery_agreement_hard_gate_enforcement():
    """Verifies that unsigned customers raise RecoveryAgreementRequiredError on gate check."""
    unsigned_customer = {
        "id": "cust_01",
        "name": "Unsigned Shipper Inc",
        "slug": "unsigned-shipper",
        "recovery_agreement_signed_at": None,
    }

    # Should raise error
    with pytest.raises(RecoveryAgreementRequiredError, match="Recovery Agreement Launch Gate"):
        verify_recovery_agreement_gate(unsigned_customer)

    # Signed customer should pass
    signed_customer = {
        "id": "cust_02",
        "name": "Signed Shipper Inc",
        "slug": "signed-shipper",
        "recovery_agreement_signed_at": "2026-09-12T10:00:00Z",
    }
    assert verify_recovery_agreement_gate(signed_customer) is True


def test_portal_service_agreement_signing_flow(tmp_path):
    """Verifies end-to-end portal service signing flow and gate unlocking."""
    service = CustomerPortalService()
    service.seed_customer(
        customer_id="cust_test_gate",
        name="Apex Global Distribution",
        slug="apex-global",
        recovery_agreement_signed_at=None,  # Unsigned initially
    )
    service.seed_invoice(
        invoice_id="inv_01",
        customer_id="cust_test_gate",
        carrier="ABF Freight",
        invoice_number="ABF-1100",
        pro_number="042-990011",
        invoice_date="2026-08-10",
        invoice_total=500.00,
        status="audited",
    )
    service.seed_flag(
        flag_id="flg_01",
        invoice_id="inv_01",
        check_type="RATE",
        overcharge_cents=5000,
        evidence_json={"contract_clause": "Item 100-D"},
        review_status="approved",
    )

    # Attempting list_disputes with enforce_gate=True before signing MUST fail
    with pytest.raises(RecoveryAgreementRequiredError):
        service.list_disputes("cust_test_gate", enforce_gate=True)

    # Sign agreement
    record = service.sign_recovery_agreement(
        customer_id="cust_test_gate",
        signer_name="Robert Vance",
        signer_title="Controller",
        output_dir=str(tmp_path),
    )

    assert record.signed_at is not None
    assert record.signer_name == "Robert Vance"
    assert os.path.exists(record.pdf_path)

    # Now list_disputes with enforce_gate=True MUST succeed
    disputes = service.list_disputes("cust_test_gate", enforce_gate=True)
    assert len(disputes) == 1
    assert disputes[0].pro_number == "042-990011"
