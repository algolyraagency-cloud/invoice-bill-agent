"""
RateGuard AI — Unit Tests for Customer Portal Service (Phase 5.5).
Verifies:
- Phase 5.5.1: Customer auth session & 5-step onboarding checklist aggregation.
- Phase 5.5.2: Invoices directory filtering and Quality Ladder Rung intake routing (Rungs A-C vs Rung D).
- Phase 5.5.3: Dispute tracker, 1-click mailto: pre-encoding, and automated credit memo verification.
"""

import pytest
from apps.worker.portal_service import CustomerPortalService


@pytest.fixture
def portal_service():
    """Initializes CustomerPortalService with seeded mock customer and test data."""
    service = CustomerPortalService()

    # Seed customer
    service.seed_customer(
        customer_id="cust_acme_01",
        name="Acme Imports & Logistics",
        slug="acme-imports",
        industry="Manufacturing",
        freight_spend_est=12500000.0,
        recovery_agreement_signed_at="2026-09-01T10:00:00Z",
        forwarding_configured=True,
    )

    # Seed users
    service.seed_user(
        user_id="usr_owner_01",
        customer_id="cust_acme_01",
        email="controller@acmeimports.com",
        role="owner",
    )
    service.seed_user(
        user_id="usr_clerk_02",
        customer_id="cust_acme_01",
        email="ap@acmeimports.com",
        role="ap_clerk",
    )

    # Seed invoices
    service.seed_invoice(
        invoice_id="inv_abf_101",
        customer_id="cust_acme_01",
        carrier="ABF Freight",
        invoice_number="ABF-9021",
        pro_number="042-881234",
        invoice_date="2026-08-12",
        invoice_total=842.50,
        status="audited",
        source="email",
    )
    service.seed_invoice(
        invoice_id="inv_xpo_102",
        customer_id="cust_acme_01",
        carrier="XPO Logistics",
        invoice_number="XPO-5512",
        pro_number="065-992143",
        invoice_date="2026-08-14",
        invoice_total=1240.00,
        status="audited",
        source="upload",
    )

    # Seed flags
    service.seed_flag(
        flag_id="flg_01",
        invoice_id="inv_abf_101",
        check_type="RATE",
        overcharge_cents=14250,  # $142.50
        evidence_json={
            "contract_clause": "Item 100-D (Deficit Bumping)",
            "billed_rate": 18.50,
            "correct_rate": 14.20,
        },
        review_status="approved",
    )
    service.seed_flag(
        flag_id="flg_02",
        invoice_id="inv_xpo_102",
        check_type="FSC",
        overcharge_cents=6500,  # $65.00
        evidence_json={
            "contract_clause": "Item 220-A (Fuel Scale)",
            "billed_value": 34.50,
            "correct_value": 31.00,
        },
        review_status="approved",
    )

    # Seed disputes
    service.seed_dispute(
        dispute_id="disp-flg_01",
        flag_id="flg_01",
        status="drafted",
    )
    service.seed_dispute(
        dispute_id="disp-flg_02",
        flag_id="flg_02",
        status="sent",
    )

    return service


def test_customer_auth_and_session_resolution(portal_service):
    """Verifies passwordless magic link session lookup for customer users."""
    session = portal_service.authenticate_session("controller@acmeimports.com")
    assert session is not None
    assert session.customer_name == "Acme Imports & Logistics"
    assert session.customer_slug == "acme-imports"
    assert session.role == "owner"

    # Non-existent email returns None
    assert portal_service.authenticate_session("unknown@nowhere.com") is None


def test_dashboard_aggregation_and_checklist(portal_service):
    """Verifies that the dashboard computes KPIs and the 5-step checklist correctly."""
    dashboard = portal_service.get_dashboard("cust_acme_01")

    # Inbound emails
    assert dashboard.inbound_email == "acme-imports@in.rateguard.app"
    assert dashboard.dispute_tracking_email == "disputes+acme-imports@in.rateguard.app"

    # Financial KPIs: $142.50 + $65.00 = $207.50
    assert dashboard.kpis.total_recoverable_cents == 20750
    assert dashboard.kpis.total_recoverable_dollars == 207.50
    # 65% Shipper Net Recovery: $207.50 * 0.65 = $134.88
    assert dashboard.kpis.estimated_shipper_net_dollars == 134.88
    # 35% RateGuard Fee: $207.50 * 0.35 = $72.62
    assert dashboard.kpis.contingency_fee_dollars == 72.63 or dashboard.kpis.contingency_fee_dollars == 72.62
    assert dashboard.kpis.total_invoices_audited == 2
    assert dashboard.kpis.open_disputes_count == 2

    # Checklist status
    chk = dashboard.checklist
    assert chk.forwarding_rule.status == "completed"
    assert chk.first_invoices_in.status == "completed"
    assert chk.recovery_agreement.status == "signed"
    assert chk.report_ready.status == "ready"
    assert chk.contracts_uploaded.status == "pending"
    assert chk.completed_steps_count == 4
    assert not chk.is_fully_onboarded


def test_contract_intake_quality_ladder_routing(portal_service):
    """Verifies Quality Ladder Rung detection (Rungs A-C vs Rung D)."""
    # Rung A: Signed agreement
    c_a = portal_service.submit_contract(
        customer_id="cust_acme_01",
        carrier="ABF Freight",
        rung="A",
        has_signed_agreement=True,
        filename="abf_pricing_agreement_2026.pdf",
    )
    assert c_a.rung == "A"
    assert c_a.validation_status == "valid"
    assert c_a.parsed_lanes_count == 42

    # Rung B: Email proposals
    c_b = portal_service.submit_contract(
        customer_id="cust_acme_01",
        carrier="XPO Logistics",
        rung="B",
        has_signed_agreement=False,
        filename="xpo_quote_thread.pdf",
    )
    assert c_b.rung == "B"
    assert c_b.validation_status == "needs_spot_check"

    # Rung D: Disqualified per PRD §4.3
    with pytest.raises(ValueError, match="Rung D"):
        portal_service.submit_contract(
            customer_id="cust_acme_01",
            carrier="Roadrunner",
            rung="D",
            has_signed_agreement=False,
        )

    # Verify contracts listed
    contracts = portal_service.list_contracts("cust_acme_01")
    assert len(contracts) == 2


def test_invoice_listing_and_filters(portal_service):
    """Verifies invoice directory filtering by carrier and search term."""
    # List all
    res_all = portal_service.list_invoices("cust_acme_01")
    assert res_all["total_count"] == 2

    # Filter by carrier
    res_abf = portal_service.list_invoices("cust_acme_01", carrier="ABF")
    assert res_abf["total_count"] == 1
    assert res_abf["invoices"][0]["carrier"] == "ABF Freight"
    assert res_abf["invoices"][0]["overcharge_dollars"] == 142.50

    # Filter by search
    res_search = portal_service.list_invoices("cust_acme_01", search="5512")
    assert res_search["total_count"] == 1
    assert res_search["invoices"][0]["invoice_number"] == "XPO-5512"


def test_dispute_tracker_and_mailto_encoding(portal_service):
    """Verifies dispute notices format RFC 2368 mailto links with To, CC, and structured body."""
    disputes = portal_service.list_disputes("cust_acme_01")
    assert len(disputes) == 2

    abf_disp = next(d for d in disputes if d.carrier == "ABF Freight")
    assert abf_disp.carrier_dispute_email == "freightbilling@abf.com"
    assert "mailto:freightbilling%40abf.com" in abf_disp.mailto_link or "mailto:freightbilling@abf.com" in abf_disp.mailto_link
    assert "disputes%2Bacme-imports%40in.rateguard.app" in abf_disp.mailto_link or "disputes+acme-imports@in.rateguard.app" in abf_disp.mailto_link
    assert "ABF-9021" in abf_disp.email_subject

    # Test status transition: drafted -> sent
    updated = portal_service.update_dispute_status("cust_acme_01", abf_disp.dispute_id, "sent")
    assert updated.status == "sent"


def test_credit_memo_auto_matching_and_verification(portal_service):
    """
    Verifies that when a credit memo matches an open invoice reference,
    it automatically verifies and transitions the dispute to credit_issued.
    """
    # Submit credit memo referencing invoice ABF-9021
    memo = portal_service.submit_credit_memo(
        customer_id="cust_acme_01",
        carrier="ABF Freight",
        memo_number="CM-ABF-7741",
        original_invoice_ref="ABF-9021",
        amount_cents=14250,
        kind="credit_memo",
    )

    assert memo.verification_status == "verified"
    assert memo.matched_dispute_id == "disp-flg_01"
    assert memo.amount_dollars == 142.50

    # Dispute status should now be credit_issued
    disputes = portal_service.list_disputes("cust_acme_01")
    abf_disp = next(d for d in disputes if d.dispute_id == "disp-flg_01")
    assert abf_disp.status == "credit_issued"

    # List credit memos
    memos = portal_service.list_credit_memos("cust_acme_01")
    assert len(memos) == 1
    assert memos[0].verification_status == "verified"
