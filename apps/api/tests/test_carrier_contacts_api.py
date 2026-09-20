"""
Tests for Carrier Contacts Directory API & Rep Email Overrides (Issue 2).
"""
import pytest
from fastapi.testclient import TestClient

from apps.api.server import app, portal_service

client = TestClient(app)


def test_list_carrier_contacts():
    response = client.get("/api/v1/carrier-contacts")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    carriers = [c["carrier"] for c in data]
    assert "ABF Freight" in carriers
    assert "SwiftPath Logistics LLC" in carriers
    assert "GSW Freight System, Inc." in carriers


def test_save_carrier_contact_success():
    payload = {
        "carrier": "SwiftPath Logistics LLC",
        "dispute_email": "disputes@swiftpathlogistics.com",
        "billing_phone": "800-555-9988",
        "notes": "Direct rep: Marcus at dispute desk",
        "customer_id": "cust_acme_01"
    }
    response = client.post("/api/v1/carrier-contacts", json=payload)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["carrier"] == "SwiftPath Logistics LLC"
    assert res_data["dispute_email"] == "disputes@swiftpathlogistics.com"
    assert res_data["billing_phone"] == "800-555-9988"

    # Verify resolution in portal_service
    resolved = portal_service.resolve_carrier_contact("SwiftPath Logistics LLC")
    assert resolved["dispute_email"] == "disputes@swiftpathlogistics.com"


def test_save_carrier_contact_invalid_email():
    payload = {
        "carrier": "SwiftPath Logistics LLC",
        "dispute_email": "not-an-email",
        "billing_phone": "800-555-9988"
    }
    response = client.post("/api/v1/carrier-contacts", json=payload)
    assert response.status_code == 400
    assert "Invalid email address format" in response.json()["detail"]


def test_fuzzy_carrier_contact_resolution():
    # Fuzzy match 'SwiftPath' should match 'SwiftPath Logistics LLC'
    resolved = portal_service.resolve_carrier_contact("SwiftPath")
    assert "swiftpath" in resolved["dispute_email"]
