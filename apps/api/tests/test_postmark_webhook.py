"""
Tests for Postmark Inbound Webhook Parsing & Email Ingestion (Phase 1.1).
"""
import base64

from apps.worker.ingestion import (
    compute_sha256,
    extract_slug_and_stream,
    is_pdf_magic_bytes,
    parse_postmark_inbound_json,
)


def test_extract_slug_and_stream():
    slug, is_dispute = extract_slug_and_stream("acme-parts@in.rateguard.app")
    assert slug == "acme-parts"
    assert is_dispute is False

    # Dispute CC stream
    slug_cc, is_dispute_cc = extract_slug_and_stream("disputes+acme-parts@in.rateguard.app")
    assert slug_cc == "acme-parts"
    assert is_dispute_cc is True

    # With display name format
    slug_disp, _ = extract_slug_and_stream('"Acme AP Team" <acme-logistics@in.rateguard.app>')
    assert slug_disp == "acme-logistics"


def test_postmark_inbound_parsing():
    # Synthetic minimal PDF bytes
    sample_pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
    pdf_b64 = base64.b64encode(sample_pdf_bytes).decode("utf-8")

    payload = {
        "From": "billing@abf.com",
        "FromName": "ABF Freight Billing",
        "To": "acme-corp@in.rateguard.app",
        "Subject": "ABF Invoice INV-88219 (PRO #042-882190)",
        "Date": "2026-08-16T14:30:00Z",
        "TextBody": "Please find attached your freight invoice.",
        "Attachments": [
            {
                "Name": "INV-88219.pdf",
                "Content": pdf_b64,
                "ContentType": "application/pdf",
                "ContentLength": len(sample_pdf_bytes)
            },
            {
                "Name": "logo.png",
                "Content": base64.b64encode(b"not a pdf").decode("utf-8"),
                "ContentType": "image/png",
                "ContentLength": 9
            }
        ]
    }

    result = parse_postmark_inbound_json(payload)
    assert result["slug"] == "acme-corp"
    assert result["is_dispute_stream"] is False
    assert len(result["pdf_attachments"]) == 1  # logo.png filtered out

    pdf = result["pdf_attachments"][0]
    assert pdf["filename"] == "INV-88219.pdf"
    assert is_pdf_magic_bytes(pdf["content_bytes"]) is True
    assert pdf["sha256"] == compute_sha256(sample_pdf_bytes)


def test_postmark_dispute_cc_routing():
    payload = {
        "From": "claims@xpo.com",
        "To": "ap@acme-corp.com",
        "Cc": "disputes+acme-corp@in.rateguard.app",
        "Subject": "Re: Billing Dispute PRO #XPO-99120",
        "Date": "2026-08-18T10:00:00Z",
        "TextBody": "Credit memo CM-9910 has been issued for $125.00."
    }

    result = parse_postmark_inbound_json(payload)
    assert result["slug"] == "acme-corp"
    assert result["is_dispute_stream"] is True


def test_postmark_webhook_live_audit_execution():
    from fastapi.testclient import TestClient
    from apps.api.server import app

    client = TestClient(app)

    # 1. Test live simulate endpoint
    resp = client.post("/api/v1/simulate/inbound-email", data={"carrier": "ABF Freight", "customer_id": "cust_acme_01"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["simulation"] == "success"
    assert data["carrier_simulated"] == "ABF Freight"
    assert "pipeline_result" in data
    pipe = data["pipeline_result"]
    assert pipe["status"] == "processed"
    assert pipe["attachments_count"] == 1
    assert len(pipe["invoices_audited"]) == 1
    audited = pipe["invoices_audited"][0]
    assert audited["status"] == "success"
    assert audited["carrier"] == "ABF Freight"
    assert audited["flag_detected"] is True
    assert audited["overcharge_amount"] > 0


def test_cloudflare_email_inbound_parsing_and_webhook():
    from email.mime.multipart import MIMEMultipart
    from email.mime.application import MIMEApplication
    from email.mime.text import MIMEText
    from fastapi.testclient import TestClient
    from apps.api.server import app

    client = TestClient(app)

    # Build a sample MIME email with PDF attachment
    msg = MIMEMultipart()
    msg["To"] = "acme@in.lexaintake.com"
    msg["From"] = "billing@abf.com"
    msg["Subject"] = "Freight Invoice ABF-9901"
    msg.attach(MIMEText("Please find your freight bill attached.", "plain"))

    sample_pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
    pdf_part = MIMEApplication(sample_pdf_bytes, _subtype="pdf")
    pdf_part.add_header("Content-Disposition", "attachment", filename="ABF-9901.pdf")
    msg.attach(pdf_part)

    payload = {
        "to": "acme@in.lexaintake.com",
        "from": "billing@abf.com",
        "subject": "Freight Invoice ABF-9901",
        "raw": msg.as_string()
    }

    resp = client.post("/api/webhooks/cloudflare-email", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processed"
    assert data["slug"] == "acme"
    assert data["attachments_count"] == 1
    assert len(data["invoices_audited"]) == 1


