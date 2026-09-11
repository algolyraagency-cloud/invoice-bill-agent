"""
RateGuard AI — Unit Tests for Dispute Letter Generator (Phase 5.2).
Validates dispute letter composition, carrier contact directory resolution,
RFC 2368 mailto: URL encoding, status state machine, carrier batching, and vector PDF generation.
"""

import sys
from pathlib import Path
import pytest

# Ensure root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from apps.worker.dispute_generator import (
    generate_carrier_dispute_batch,
    generate_dispute_letter,
    get_carrier_contact,
    render_dispute_pdf,
    transition_dispute_status,
)
from packages.schemas.models import ReviewQueueItem


@pytest.fixture
def abf_flag_01():
    return ReviewQueueItem(
        id="flag_abf_01",
        invoice_id="inv_abf_01",
        check_type="RATE",
        overcharge_cents=8450,  # $84.50
        confidence=1.0,
        evidence_json={
            "contract_clause": "Tariff Item 100-D Section 4.2",
            "page_number": 12,
            "billed_amount": 950.00,
            "correct_amount": 865.50,
            "explanation": "Billed deficit weight rate misapplied; contracted weight break M1M should apply.",
        },
        review_status="approved",
        carrier="ABF Freight",
        pro_number="042-771234",
        invoice_number="INV-ABF-8819",
        invoice_date="2026-08-14",
        invoice_total=950.00,
        customer_id="cust_acme_01",
    )


@pytest.fixture
def abf_flag_02():
    return ReviewQueueItem(
        id="flag_abf_02",
        invoice_id="inv_abf_02",
        check_type="FSC",
        overcharge_cents=3120,  # $31.20
        evidence_json={
            "contract_clause": "ABF Fuel Surcharge Scale Matrix",
            "billed_amount": 420.00,
            "correct_amount": 388.80,
            "explanation": "Fuel surcharge pegged to incorrect week diesel index.",
        },
        review_status="approved",
        carrier="ABF Freight",
        pro_number="042-771235",
        invoice_number="INV-ABF-8820",
        invoice_date="2026-08-15",
        invoice_total=420.00,
        customer_id="cust_acme_01",
    )


def test_generate_dispute_letter_rate(abf_flag_01):
    letter = generate_dispute_letter(
        flag=abf_flag_01,
        customer_name="Acme Logistics Inc",
        customer_slug="acme-logistics",
    )

    assert letter.carrier == "ABF Freight"
    assert letter.carrier_dispute_email == "freightbilling@abf.com"
    assert letter.pro_number == "042-771234"
    assert letter.invoice_number == "INV-ABF-8819"
    assert letter.overcharge_dollars == 84.50
    assert letter.check_type == "RATE"
    assert "Tariff Item 100-D Section 4.2" in letter.contract_clause
    assert letter.status == "drafted"

    # Subject line verification
    assert "Billing Dispute: Invoice #INV-ABF-8819 / PRO #042-771234 — Acme Logistics Inc" == letter.email_subject

    # Plain text body verification
    assert "Dispute Email: freightbilling@abf.com" in letter.email_body_text
    assert "disputes+acme-logistics@in.rateguard.app" in letter.email_body_text
    assert "issue an itemized Credit Memo in the amount of $84.50" in letter.email_body_text

    # Mailto link verification
    assert letter.mailto_link.startswith("mailto:freightbilling@abf.com?")
    assert "cc=disputes%2Bacme-logistics%40in.rateguard.app" in letter.mailto_link
    assert "subject=Billing%20Dispute" in letter.mailto_link


def test_carrier_contacts_resolution():
    xpo = get_carrier_contact("XPO Logistics")
    assert xpo["dispute_email"] == "ltlclaims@xpo.com"

    rr = get_carrier_contact("Roadrunner")
    assert rr["dispute_email"] == "billingdisputes@rrts.com"

    unknown = get_carrier_contact("Acme Fast Freight")
    assert "@carrier-billing.com" in unknown["dispute_email"] or "billing-disputes" in unknown["dispute_email"]


def test_generate_carrier_dispute_batch(abf_flag_01, abf_flag_02):
    batch = generate_carrier_dispute_batch(
        approved_flags=[abf_flag_01, abf_flag_02],
        carrier="ABF Freight",
        customer_name="Acme Logistics Inc",
        customer_slug="acme-logistics",
    )

    assert batch.carrier == "ABF Freight"
    assert batch.carrier_dispute_email == "freightbilling@abf.com"
    assert batch.disputes_count == 2
    # 84.50 + 31.20 = 115.70
    assert batch.total_disputed_dollars == 115.70
    assert len(batch.disputes) == 2

    # Combined mailto verification
    assert batch.combined_mailto_link.startswith("mailto:freightbilling@abf.com?")
    assert "cc=disputes%2Bacme-logistics%40in.rateguard.app" in batch.combined_mailto_link
    assert "042-771234" in batch.combined_mailto_link
    assert "042-771235" in batch.combined_mailto_link


def test_dispute_status_state_machine():
    # Valid forward flow: drafted -> sent -> responded -> credit_issued
    s1 = transition_dispute_status("drafted", "sent")
    assert s1 == "sent"

    s2 = transition_dispute_status("sent", "responded")
    assert s2 == "responded"

    s3 = transition_dispute_status("responded", "credit_issued")
    assert s3 == "credit_issued"

    # Valid direct resolution: sent -> credit_issued
    assert transition_dispute_status("sent", "credit_issued") == "credit_issued"

    # Valid denial and re-escalation: sent -> denied -> sent
    assert transition_dispute_status("sent", "denied") == "denied"
    assert transition_dispute_status("denied", "sent") == "sent"

    # Invalid transitions must raise ValueError
    with pytest.raises(ValueError):
        transition_dispute_status("drafted", "credit_issued")  # Can't issue credit before sending!

    with pytest.raises(ValueError):
        transition_dispute_status("drafted", "denied")  # Can't deny before sending!

    with pytest.raises(ValueError):
        transition_dispute_status("credit_issued", "drafted")  # Terminal state


def test_render_dispute_pdf(abf_flag_01):
    letter = generate_dispute_letter(
        flag=abf_flag_01,
        customer_name="Acme Logistics Inc",
        customer_slug="acme-logistics",
    )
    pdf_bytes = render_dispute_pdf(letter)

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 800
    assert pdf_bytes.startswith(b"%PDF-")

    # Read back and inspect text
    import pymupdf as fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    assert doc.page_count == 1

    page_text = doc[0].get_text()
    assert "ACME LOGISTICS INC" in page_text
    assert "FORMAL NOTICE OF FREIGHT BILLING DISPUTE" in page_text
    assert "042-771234" in page_text
    assert "INV-ABF-8819" in page_text
    assert "$84.50" in page_text
    assert "freightbilling@abf.com" in page_text
    doc.close()
