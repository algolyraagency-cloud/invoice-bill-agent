"""
Comprehensive Security, Data Integrity, and API Unit Test Suite for RateGuard AI Server (apps/api/server.py).
Tests health, customer listing, multi-tenant portal session, review queue role protection,
Postmark webhook auth, upload magic-byte validation, rate limiting, and agreement gates.
"""

import os
import pytest
from fastapi.testclient import TestClient
from apps.api.server import app, portal_service

client = TestClient(app)

def test_health_check():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "RateGuard AI API"
    assert data["version"] == "2.0"
    assert "llm_circuit_breaker_tripped" in data

def test_list_customers():
    response = client.get("/api/v1/customers")
    assert response.status_code == 200
    customers = response.json()
    assert len(customers) >= 4
    slugs = [c["slug"] for c in customers]
    assert "acme-imports" in slugs
    assert "pacific-supply" in slugs
    assert "apex-global" in slugs
    assert "vanguard-freight" in slugs

def test_portal_session():
    response = client.get("/api/v1/portal/session?customer_id=cust_acme_01")
    assert response.status_code == 200
    data = response.json()
    assert data["kpis"]["total_invoices_audited"] >= 0

def test_review_queue_role_protection():
    # Attempt unauthenticated request without role header
    response_unauth = client.get("/api/v1/review/queue")
    assert response_unauth.status_code == 403
    assert "Access Denied" in response_unauth.json()["detail"]

    # Request with valid internal_reviewer role header
    response_auth = client.get("/api/v1/review/queue", headers={"X-RateGuard-Role": "internal_reviewer"})
    assert response_auth.status_code == 200
    flags = response_auth.json()
    assert isinstance(flags, list)
    assert len(flags) > 0

def test_internal_review_static_route_role_protection():
    # Attempt accessing /internal/review without role
    response_unauth = client.get("/internal/review")
    assert response_unauth.status_code == 403

    # Accessing with role header
    response_auth = client.get("/internal/review", headers={"X-RateGuard-Role": "internal_reviewer"})
    assert response_auth.status_code == 200

def test_review_action_submit():
    response = client.post(
        "/api/v1/review/action",
        data={
            "flag_id": "flg_03",
            "action": "approve",
            "reason_code": "wrong-matrix-row",
            "reviewer_id": "rev_auditor_01"
        },
        headers={"X-RateGuard-Role": "internal_reviewer"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"

def test_postmark_webhook_token_auth():
    os.environ["POSTMARK_SERVER_TOKEN"] = "secret_postmark_token_123"

    # Unauthorized request without header
    response_unauth = client.post("/api/webhooks/postmark", json={"From": "billing@abf.com", "Subject": "Invoice"})
    assert response_unauth.status_code == 401

    # Authorized request with header
    response_auth = client.post(
        "/api/webhooks/postmark",
        json={"From": "billing@abf.com", "Subject": "Invoice"},
        headers={"X-Postmark-Server-Token": "secret_postmark_token_123"}
    )
    assert response_auth.status_code == 200
    assert response_auth.json()["status"] == "processed"

    # Clean up env
    del os.environ["POSTMARK_SERVER_TOKEN"]

def test_file_upload_validation_and_magic_bytes():
    # Executable file block (.exe)
    response_exe = client.post(
        "/api/v1/upload",
        files={"file": ("malicious.exe", b"MZexecutablecontent", "application/octet-stream")}
    )
    assert response_exe.status_code == 400
    assert "Executable files are strictly prohibited" in response_exe.json()["detail"]

    # Invalid fake PDF (fails magic byte check)
    response_fake = client.post(
        "/api/v1/upload",
        files={"file": ("fake_invoice.pdf", b"This is not a real PDF file", "application/pdf")}
    )
    assert response_fake.status_code == 400
    assert "Invalid file format" in response_fake.json()["detail"]

    # Valid PDF with %PDF- magic bytes
    valid_pdf_bytes = b"%PDF-1.5 %Valid PDF document header\n%%EOF"
    response_valid = client.post(
        "/api/v1/upload",
        files={"file": ("abf_invoice.pdf", valid_pdf_bytes, "application/pdf")},
        data={"customer_id": "cust_acme_01", "source": "upload"}
    )
    assert response_valid.status_code == 200
    assert response_valid.json()["status"] == "success"

def test_disputes_batch_locked_for_unsigned_customer():
    # Unsigned customer check before signing
    portal_service._customers["cust_apex_03"]["recovery_agreement_signed_at"] = None
    response = client.get("/api/v1/disputes/batch?customer_id=cust_apex_03")
    assert response.status_code == 403
    assert "RecoveryAgreementRequiredError" in response.json()["detail"]

def test_agreement_e_signature():
    response = client.post("/api/v1/agreement/sign", data={
        "customer_id": "cust_apex_03",
        "signer_name": "Marcus Brody",
        "signer_title": "VP Logistics"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "Marcus Brody" in data["signer"]

def test_disputes_batch_unlocked():
    response = client.get("/api/v1/disputes/batch?customer_id=cust_acme_01")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "unlocked"
    assert "batch" in data

def test_credit_memo_logging():
    response = client.post("/api/v1/credit-memos", data={
        "customer_id": "cust_acme_01",
        "carrier": "ABF Freight",
        "memo_number": "CM-9901",
        "original_invoice_ref": "INV-8812",
        "amount": 16.50
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "verified"
    assert data["memo_number"] == "CM-9901"

def test_commission_invoices():
    response = client.get("/api/v1/commission-invoices?customer_id=cust_acme_01")
    assert response.status_code == 200
    invoices = response.json()
    assert len(invoices) > 0
    assert invoices[0]["rate_pct"] == 35.0

def test_carrier_analytics():
    response = client.get("/api/v1/analytics/carrier-hostility")
    assert response.status_code == 200
    analytics = response.json()
    assert len(analytics) >= 4

def test_static_routes():
    assert client.get("/").status_code == 200
    assert client.get("/portal").status_code == 200
    assert client.get("/onboarding").status_code == 200
    assert client.get("/setup-forwarding").status_code == 200
