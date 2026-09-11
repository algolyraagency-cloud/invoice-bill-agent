"""
RateGuard AI — Unit & Integration Tests for Review Queue Service (Phase 4.1).
Validates flag lifecycle state transitions, role gating, 8-code taxonomy enforcement,
research resolution workflow, and throughput statistics.
"""
import pytest

from packages.schemas.models import ReviewActionRequest
from apps.worker.review_queue import ReviewQueueService, STANDARD_REASON_CODES


@pytest.fixture
def review_service():
    """Provides a fresh ReviewQueueService with seeded users and test flags."""
    service = ReviewQueueService()

    # Seed users
    service.seed_mock_user("rev_valid_01", "auditor@rateguard.app", role="internal_reviewer")
    service.seed_mock_user("unauth_user_02", "clerk@shipper.com", role="ap_clerk")
    service.seed_mock_user("customer_user_03", "cfo@shipper.com", role="customer")

    # Seed test flags
    service.seed_mock_flag(
        flag_id="flag_rate_01",
        invoice_id="inv_001",
        check_type="RATE",
        overcharge_cents=7625,
        evidence_json={
            "invoice_ref": "INV-ABF-7712",
            "carrier": "ABF Freight",
            "contract_clause": "Item 100-D (Deficit Bumping)",
            "page_number": 14,
            "billed_rate": 18.50,
            "correct_rate": 14.20,
        },
        carrier="ABF Freight",
        pro_number="042-889123",
        invoice_number="INV-ABF-7712",
        invoice_date="2026-08-16",
        invoice_total=862.50,
    )

    service.seed_mock_flag(
        flag_id="flag_fsc_02",
        invoice_id="inv_002",
        check_type="FSC",
        overcharge_cents=1850,
        evidence_json={
            "invoice_ref": "INV-XPO-9914",
            "carrier": "XPO Logistics",
            "contract_clause": "Item 220-A (Fuel Scale)",
            "page_number": 7,
            "billed_value": 34.50,
            "correct_value": 32.40,
        },
        carrier="XPO Logistics",
        pro_number="XPO-551928",
        invoice_number="INV-XPO-9914",
        invoice_date="2026-08-18",
        invoice_total=512.40,
    )

    service.seed_mock_flag(
        flag_id="flag_dup_03",
        invoice_id="inv_003",
        check_type="DUP",
        overcharge_cents=44000,
        evidence_json={
            "invoice_ref": "INV-RR-4401",
            "carrier": "Roadrunner",
            "contract_clause": "Duplicate Defense",
            "page_number": 3,
            "duplicate_pro": "RR-771122",
        },
        carrier="Roadrunner",
        pro_number="RR-771122",
        invoice_number="INV-RR-4401",
        invoice_date="2026-08-19",
        invoice_total=440.00,
    )

    return service


def test_role_gating_authorization(review_service):
    """Ensures only users with 'internal_reviewer' role can perform review actions."""
    # Authorized user succeeds
    req_auth = ReviewActionRequest(
        flag_id="flag_rate_01",
        action="approve",
        reviewer_id="rev_valid_01",
    )
    res = review_service.review_flag(req_auth)
    assert res["status"] == "approved"

    # Unauthorized users raise PermissionError
    req_unauth_clerk = ReviewActionRequest(
        flag_id="flag_fsc_02",
        action="approve",
        reviewer_id="unauth_user_02",
    )
    with pytest.raises(PermissionError, match="does not have 'internal_reviewer' role"):
        review_service.review_flag(req_unauth_clerk)

    req_unauth_customer = ReviewActionRequest(
        flag_id="flag_fsc_02",
        action="approve",
        reviewer_id="customer_user_03",
    )
    with pytest.raises(PermissionError, match="does not have 'internal_reviewer' role"):
        review_service.review_flag(req_unauth_customer)


def test_approve_flag_lifecycle(review_service):
    """Validates approval transition, dollar staging for Phase 5 Recovery Report, and audit event logging."""
    req = ReviewActionRequest(
        flag_id="flag_rate_01",
        action="approve",
        reviewer_id="rev_valid_01",
        notes="Verified deficit weight bumping applied per Item 100-D",
        duration_seconds=12.5,
    )
    result = review_service.review_flag(req)

    assert result["status"] == "approved"
    assert result["flag_id"] == "flag_rate_01"

    # Flag is no longer in pending
    pending_items = review_service.get_queue(status="pending")
    assert not any(item.id == "flag_rate_01" for item in pending_items)

    # Flag is in approved queue
    approved_items = review_service.get_queue(status="approved")
    assert any(item.id == "flag_rate_01" for item in approved_items)

    # Review event audit trail recorded
    events = review_service._mock_review_events
    assert len(events) == 1
    assert events[0]["action"] == "approve"
    assert events[0]["reviewer"] == "rev_valid_01"
    assert "Item 100-D" in events[0]["notes"]

    # Summary reflects approved overcharge
    summary = review_service.get_queue_summary()
    assert summary.approved_count == 1
    assert summary.total_approved_overcharge_cents == 7625
    assert summary.pending_count == 2


def test_reject_flag_all_standard_taxonomy_codes(review_service):
    """Validates that all 8 standardized reason codes succeed and increment taxonomy count."""
    for idx, code in enumerate(STANDARD_REASON_CODES):
        flag_id = f"flag_tax_{idx}"
        review_service.seed_mock_flag(
            flag_id=flag_id,
            invoice_id=f"inv_tax_{idx}",
            check_type="RATE",
            overcharge_cents=1000,
            evidence_json={},
        )

        req = ReviewActionRequest(
            flag_id=flag_id,
            action="reject",
            reviewer_id="rev_valid_01",
            reason_code=code,
            notes=f"Testing code {code}",
        )
        res = review_service.review_flag(req)
        assert res["status"] == "rejected"
        assert res["reason_code"] == code

        # Check count incremented in taxonomy dictionary
        assert review_service._mock_reason_codes[code] >= 1

    summary = review_service.get_queue_summary()
    assert summary.rejected_count == len(STANDARD_REASON_CODES)


def test_reject_flag_invalid_reason_code_blocked(review_service):
    """Enforces strict rejection reason code validation (blocks arbitrary or empty codes)."""
    # Missing reason code
    req_missing = ReviewActionRequest(
        flag_id="flag_rate_01",
        action="reject",
        reviewer_id="rev_valid_01",
        reason_code=None,
    )
    with pytest.raises(ValueError, match="mandatory reason code"):
        review_service.review_flag(req_missing)

    # Non-standard reason code
    req_invalid = ReviewActionRequest(
        flag_id="flag_rate_01",
        action="reject",
        reviewer_id="rev_valid_01",
        reason_code="custom-carrier-excuse-invalid",
    )
    with pytest.raises(ValueError, match="Invalid reason code"):
        review_service.review_flag(req_invalid)

    # Flag must remain in pending
    flag = review_service.get_queue(status="pending")
    assert any(f.id == "flag_rate_01" for f in flag)


def test_needs_research_workflow(review_service):
    """Validates that flags can be placed in research queue with mandatory notes."""
    # Empty notes rejected
    req_empty_notes = ReviewActionRequest(
        flag_id="flag_fsc_02",
        action="research",
        reviewer_id="rev_valid_01",
        notes="",
    )
    with pytest.raises(ValueError, match="notes are mandatory"):
        review_service.review_flag(req_empty_notes)

    # Valid research notes succeed
    req_valid_research = ReviewActionRequest(
        flag_id="flag_fsc_02",
        action="research",
        reviewer_id="rev_valid_01",
        notes="Check amendment 4 for secondary fuel peg exception",
    )
    res = review_service.review_flag(req_valid_research)
    assert res["status"] == "research"

    research_items = review_service.get_queue(status="research")
    assert len(research_items) == 1
    assert research_items[0].id == "flag_fsc_02"


def test_resolve_research_workflow_zero_orphans(review_service):
    """Guarantees flags in research can be resolved back to the queue or finalized ('nothing dies in research')."""
    # 1. Move flag into research
    review_service.review_flag(
        ReviewActionRequest(
            flag_id="flag_fsc_02",
            action="research",
            reviewer_id="rev_valid_01",
            notes="Need to check tariff schedule",
        )
    )

    # 2. Try resolving without notes -> fails
    req_no_notes = ReviewActionRequest(
        flag_id="flag_fsc_02",
        action="resolve_research",
        reviewer_id="rev_valid_01",
        notes="",
    )
    with pytest.raises(ValueError, match="Resolution notes are mandatory"):
        review_service.review_flag(req_no_notes)

    # 3. Resolve back to pending queue
    req_resolve_queue = ReviewActionRequest(
        flag_id="flag_fsc_02",
        action="resolve_research",
        reviewer_id="rev_valid_01",
        notes="Confirmed tariff schedule; returning to queue for review",
    )
    res = review_service.review_flag(req_resolve_queue)
    assert res["status"] == "pending"

    # Flag is back in pending
    pending_items = review_service.get_queue(status="pending")
    assert any(item.id == "flag_fsc_02" for item in pending_items)

    # 4. Resolve directly as reject with valid taxonomy code
    review_service.review_flag(
        ReviewActionRequest(
            flag_id="flag_fsc_02",
            action="research",
            reviewer_id="rev_valid_01",
            notes="Need recheck",
        )
    )
    req_resolve_reject = ReviewActionRequest(
        flag_id="flag_fsc_02",
        action="resolve_research",
        reviewer_id="rev_valid_01",
        reason_code="fsc-table-wrong-month",
        notes="Tariff amendment proves wrong monthly index was referenced",
    )
    res_reject = review_service.review_flag(req_resolve_reject)
    assert res_reject["status"] == "rejected"
    assert review_service._mock_reason_codes["fsc-table-wrong-month"] >= 1


def test_queue_filters_and_summary_metrics(review_service):
    """Tests carrier/check filtering, queue summary counts, and throughput timing calculation."""
    # Initial summary
    summary_init = review_service.get_queue_summary()
    assert summary_init.pending_count == 3
    assert summary_init.flags_by_carrier.get("ABF Freight") == 1
    assert summary_init.flags_by_carrier.get("XPO Logistics") == 1
    assert summary_init.flags_by_carrier.get("Roadrunner") == 1

    # Filter by check_type
    rate_flags = review_service.get_queue(status="pending", check_type="RATE")
    assert len(rate_flags) == 1
    assert rate_flags[0].check_type == "RATE"

    # Filter by carrier
    xpo_flags = review_service.get_queue(status="pending", carrier="XPO Logistics")
    assert len(xpo_flags) == 1
    assert xpo_flags[0].carrier == "XPO Logistics"

    # Review flag with duration timing (under 30s target)
    review_service.review_flag(
        ReviewActionRequest(
            flag_id="flag_rate_01",
            action="approve",
            reviewer_id="rev_valid_01",
            duration_seconds=18.4,
        )
    )

    review_service.review_flag(
        ReviewActionRequest(
            flag_id="flag_fsc_02",
            action="reject",
            reviewer_id="rev_valid_01",
            reason_code="not-an-error",
            duration_seconds=21.6,
        )
    )

    summary_final = review_service.get_queue_summary()
    assert summary_final.approved_count == 1
    assert summary_final.rejected_count == 1
    assert summary_final.total_reviewed_count == 2
    assert summary_final.pending_count == 1
    # Average duration: (18.4 + 21.6) / 2 = 20.0s (meets <=30s target)
    assert summary_final.avg_duration_seconds == 20.0
