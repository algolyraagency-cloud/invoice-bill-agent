"""
RateGuard AI — Unit Tests for Recovery Report Generator (Phase 5.1).
Validates financial calculations (65% shipper / 35% fee), carrier & check breakdowns,
HTML report rendering, and vector PDF generation via PyMuPDF.
"""

import sys
from pathlib import Path
import pytest

# Ensure root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from apps.worker.report_generator import (
    compile_recovery_report,
    render_report_html,
    render_report_pdf,
)
from packages.schemas.models import ReviewQueueItem


@pytest.fixture
def sample_approved_flags():
    return [
        ReviewQueueItem(
            id="flag_abf_01",
            invoice_id="inv_abf_01",
            check_type="RATE",
            overcharge_cents=7625,  # $76.25
            confidence=1.0,
            evidence_json={
                "contract_clause": "Tariff ABF 111-Item 100-D",
                "page_number": 14,
                "billed_amount": 862.50,
                "correct_amount": 786.25,
                "explanation": "Billed rate exceeded contracted deficit bumped weight break rate.",
            },
            review_status="approved",
            carrier="ABF Freight",
            pro_number="042-889123",
            invoice_number="INV-ABF-7712",
            invoice_date="2026-08-16",
            invoice_total=862.50,
            customer_id="cust_acme_01",
        ),
        ReviewQueueItem(
            id="flag_xpo_02",
            invoice_id="inv_xpo_02",
            check_type="FSC",
            overcharge_cents=4500,  # $45.00
            confidence=1.0,
            evidence_json={
                "contract_clause": "XPO Fuel Surcharge Scale Table June 2026",
                "page_number": 8,
                "billed_amount": 620.00,
                "correct_amount": 575.00,
                "explanation": "Billed FSC of 34.0% applied instead of published 32.5% bracket for EIA diesel benchmark.",
            },
            review_status="approved",
            carrier="XPO Logistics",
            pro_number="098-112344",
            invoice_number="INV-XPO-3301",
            invoice_date="2026-08-20",
            invoice_total=620.00,
            customer_id="cust_acme_01",
        ),
        ReviewQueueItem(
            id="flag_rr_03",
            invoice_id="inv_rr_03",
            check_type="DUP",
            overcharge_cents=12550,  # $125.50
            confidence=1.0,
            evidence_json={
                "contract_clause": "Duplicate Invoicing Clause §3.1",
                "billed_amount": 125.50,
                "correct_amount": 0.00,
                "explanation": "Duplicate billing detected matching PRO 004-998811 previously settled.",
            },
            review_status="approved",
            carrier="Roadrunner",
            pro_number="004-998811",
            invoice_number="INV-RR-9041",
            invoice_date="2026-08-25",
            invoice_total=125.50,
            customer_id="cust_acme_01",
        ),
    ]


def test_compile_recovery_report_math(sample_approved_flags):
    report = compile_recovery_report(
        approved_flags=sample_approved_flags,
        customer_id="cust_acme_01",
        customer_name="Acme Industrial Logistics",
        period_start="2026-08-01",
        period_end="2026-08-31",
        total_invoices_audited=120,
    )

    # 7625 + 4500 + 12550 = 24675 cents = $246.75
    assert report.total_recoverable_cents == 24675
    assert report.total_recoverable_dollars == 246.75
    assert report.total_approved_claims == 3
    assert report.total_invoices_audited == 120
    assert report.total_flagged_invoices == 3

    # Financial economics (65% Shipper recovery / 35% RateGuard fee)
    # 246.75 * 0.65 = 160.3875 -> 160.39
    # 246.75 * 0.35 = 86.3625 -> 86.36
    assert report.estimated_shipper_recovery_dollars == 160.39
    assert report.contingency_fee_dollars == 86.36
    assert round(report.estimated_shipper_recovery_dollars + report.contingency_fee_dollars, 2) == 246.75

    # Carrier distribution
    assert "ABF Freight" in report.by_carrier
    assert "XPO Logistics" in report.by_carrier
    assert "Roadrunner" in report.by_carrier
    assert report.by_carrier["ABF Freight"]["claims_count"] == 1
    assert report.by_carrier["ABF Freight"]["recoverable_dollars"] == 76.25

    # Check type distribution
    assert "RATE" in report.by_check_type
    assert "FSC" in report.by_check_type
    assert "DUP" in report.by_check_type
    assert report.by_check_type["RATE"]["claims_count"] == 1
    assert report.by_check_type["FSC"]["claims_count"] == 1
    assert report.by_check_type["DUP"]["claims_count"] == 1


def test_compile_empty_report():
    report = compile_recovery_report(
        approved_flags=[],
        customer_id="cust_empty",
        customer_name="Zero Corp",
    )
    assert report.total_approved_claims == 0
    assert report.total_recoverable_cents == 0
    assert report.total_recoverable_dollars == 0.0
    assert report.estimated_shipper_recovery_dollars == 0.0
    assert report.contingency_fee_dollars == 0.0
    assert len(report.claims) == 0


def test_render_report_html(sample_approved_flags):
    report = compile_recovery_report(
        approved_flags=sample_approved_flags,
        customer_id="cust_acme_01",
        customer_name="Acme Industrial Logistics",
    )
    html = render_report_html(report)

    assert "<!DOCTYPE html>" in html
    assert "Acme Industrial Logistics" in html
    assert "$246.75" in html
    assert "$160.39" in html
    assert "$86.36" in html
    assert "ABF Freight" in html
    assert "XPO Logistics" in html
    assert "Roadrunner" in html
    assert "042-889123" in html
    assert "Tariff ABF 111-Item 100-D" in html
    assert "Evidence Appendix" in html


def test_render_report_pdf(sample_approved_flags):
    report = compile_recovery_report(
        approved_flags=sample_approved_flags,
        customer_id="cust_acme_01",
        customer_name="Acme Industrial Logistics",
    )
    pdf_bytes = render_report_pdf(report)

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF-")

    # Verify PyMuPDF can inspect and read back the generated PDF
    import pymupdf as fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    assert doc.page_count >= 3
    
    # Page 1 text inspection
    p1_text = doc[0].get_text()
    assert "RateGuard AI" in p1_text
    assert "Acme Industrial Logistics" in p1_text
    assert "$246.75" in p1_text

    # Page 2 claim schedule inspection
    p2_text = doc[1].get_text()
    assert "ITEMIZED CLAIM SCHEDULE" in p2_text
    assert "042-889123" in p2_text

    # Page 3 evidence appendix inspection
    p3_text = doc[2].get_text()
    assert "EVIDENCE APPENDIX" in p3_text
    assert "Tariff ABF 111-Item 100-D" in p3_text
    doc.close()
