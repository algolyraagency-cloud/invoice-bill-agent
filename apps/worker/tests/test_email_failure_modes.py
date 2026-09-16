"""
Unit tests verifying email pipeline failure mode classification (Phase D2).
Tests:
1. Email with 0 attachments -> status = 'no_attachments'
2. Email with non-PDF attachment (e.g. .docx) -> status = 'unsupported_format'
3. Email with corrupt/fake PDF attachment -> status = 'corrupt_pdf'
4. Email with valid PDF attachment -> status = 'processed'
"""

import base64

from apps.worker.ingestion import parse_postmark_inbound_json


def test_email_mode_no_attachments():
    payload = {
        "From": "ap@shipper.com",
        "To": "acme-imports@in.rateguard.app",
        "Subject": "Monthly Statement",
        "Attachments": []
    }
    result = parse_postmark_inbound_json(payload)
    assert result["processed_status"] == "no_attachments"
    assert result["pdf_attachments"] == []
    assert "zero attachments" in result["failure_reason"]

def test_email_mode_unsupported_format():
    payload = {
        "From": "ap@shipper.com",
        "To": "acme-imports@in.rateguard.app",
        "Subject": "Carrier Rates Document",
        "Attachments": [
            {
                "Name": "carrier_rates.docx",
                "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "Content": base64.b64encode(b"Word document dummy data").decode("utf-8")
            }
        ]
    }
    result = parse_postmark_inbound_json(payload)
    assert result["processed_status"] == "unsupported_format"
    assert result["pdf_attachments"] == []
    assert "unsupported file formats" in result["failure_reason"]

def test_email_mode_corrupt_pdf():
    payload = {
        "From": "ap@shipper.com",
        "To": "acme-imports@in.rateguard.app",
        "Subject": "Freight Invoice PDF",
        "Attachments": [
            {
                "Name": "invoice_corrupt.pdf",
                "ContentType": "application/pdf",
                "Content": base64.b64encode(b"This is not a real PDF file header").decode("utf-8")
            }
        ]
    }
    result = parse_postmark_inbound_json(payload)
    assert result["processed_status"] == "corrupt_pdf"
    assert result["pdf_attachments"] == []
    assert "PDF magic-byte validation" in result["failure_reason"]

def test_email_mode_valid_pdf():
    valid_pdf_bytes = b"%PDF-1.4 valid pdf content header\n%%EOF"
    payload = {
        "From": "ap@shipper.com",
        "To": "acme-imports@in.rateguard.app",
        "Subject": "Freight Invoice PDF",
        "Attachments": [
            {
                "Name": "abf_invoice_8812.pdf",
                "ContentType": "application/pdf",
                "Content": base64.b64encode(valid_pdf_bytes).decode("utf-8")
            }
        ]
    }
    result = parse_postmark_inbound_json(payload)
    assert result["processed_status"] == "processed"
    assert len(result["pdf_attachments"]) == 1
    assert result["pdf_attachments"][0]["filename"] == "abf_invoice_8812.pdf"
