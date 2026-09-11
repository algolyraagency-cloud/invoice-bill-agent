"""
RateGuard AI — Unit & Integration Tests for Reason-Code Feedback Loop (Phase 4.2).
Validates precision calculation, PRD §10 trajectory benchmarking, top reason code ranking,
automated parser/prompt ticket generation, and monthly retrospective reports.
"""
import pytest

from packages.schemas.models import MonthlyRetroReport, PrecisionReportItem
from apps.worker.feedback_loop import (
    FeedbackLoopService,
    compute_precision_score,
    evaluate_trajectory_status,
    format_retro_markdown,
)


def test_precision_calculation_and_division_by_zero():
    """Validates human review precision math and safe handling of zero reviews."""
    # Zero reviews edge cases
    assert compute_precision_score(0, 0) == 0.0
    assert compute_precision_score(0, 5) == 0.0

    # Clean reviews
    assert compute_precision_score(10, 0) == 100.0
    assert compute_precision_score(9, 1) == 90.0
    assert compute_precision_score(19, 1) == 95.0
    assert compute_precision_score(49, 1) == 98.0
    assert compute_precision_score(1, 1) == 50.0
    assert compute_precision_score(7, 3) == 70.0


def test_trajectory_status_evaluation():
    """Verifies PRD §10 Quality Gate trajectory evaluation."""
    assert evaluate_trajectory_status(0.0, 0) == "NO_REVIEWS_RECORDED"
    assert evaluate_trajectory_status(88.5, 20) == "BELOW_TARGET"
    assert evaluate_trajectory_status(90.0, 10) == "PILOT_GATE_PASSED"
    assert evaluate_trajectory_status(92.4, 25) == "PILOT_GATE_PASSED"
    assert evaluate_trajectory_status(95.0, 40) == "SCALE_TARGET_MET"
    assert evaluate_trajectory_status(96.8, 50) == "SCALE_TARGET_MET"
    assert evaluate_trajectory_status(98.0, 100) == "ENTERPRISE_MET"
    assert evaluate_trajectory_status(99.2, 120) == "ENTERPRISE_MET"


@pytest.fixture
def feedback_service():
    """Provides a FeedbackLoopService with synthetic multi-carrier, multi-check review data."""
    service = FeedbackLoopService()

    mock_flags = [
        # ABF Freight: 4 approved RATE, 1 rejected RATE (wrong-matrix-row) -> 80.0% precision
        {"id": "f1", "carrier": "ABF Freight", "check_type": "RATE", "review_status": "approved", "reviewed_at": "2026-08-10T10:00:00Z"},
        {"id": "f2", "carrier": "ABF Freight", "check_type": "RATE", "review_status": "approved", "reviewed_at": "2026-08-11T10:00:00Z"},
        {"id": "f3", "carrier": "ABF Freight", "check_type": "RATE", "review_status": "approved", "reviewed_at": "2026-08-12T10:00:00Z"},
        {"id": "f4", "carrier": "ABF Freight", "check_type": "RATE", "review_status": "approved", "reviewed_at": "2026-08-13T10:00:00Z"},
        {"id": "f5", "carrier": "ABF Freight", "check_type": "RATE", "review_status": "rejected", "reject_reason_code": "wrong-matrix-row", "reviewed_at": "2026-08-14T10:00:00Z"},

        # XPO Logistics: 4 approved FSC, 1 rejected FSC (fsc-table-wrong-month) -> 80.0% precision
        {"id": "f6", "carrier": "XPO Logistics", "check_type": "FSC", "review_status": "approved", "reviewed_at": "2026-08-15T10:00:00Z"},
        {"id": "f7", "carrier": "XPO Logistics", "check_type": "FSC", "review_status": "approved", "reviewed_at": "2026-08-16T10:00:00Z"},
        {"id": "f8", "carrier": "XPO Logistics", "check_type": "FSC", "review_status": "approved", "reviewed_at": "2026-08-17T10:00:00Z"},
        {"id": "f9", "carrier": "XPO Logistics", "check_type": "FSC", "review_status": "approved", "reviewed_at": "2026-08-18T10:00:00Z"},
        {"id": "f10", "carrier": "XPO Logistics", "check_type": "FSC", "review_status": "rejected", "reject_reason_code": "fsc-table-wrong-month", "reviewed_at": "2026-08-19T10:00:00Z"},

        # Roadrunner: 10 approved DUP, 0 rejected -> 100.0% precision
        * [{"id": f"f_rr_{i}", "carrier": "Roadrunner", "check_type": "DUP", "review_status": "approved", "reviewed_at": "2026-08-20T10:00:00Z"} for i in range(10)],

        # Extra rejection: misread-pdf-field for ARITH
        {"id": "f_arith_rej", "carrier": "ABF Freight", "check_type": "ARITH", "review_status": "rejected", "reject_reason_code": "misread-pdf-field", "reviewed_at": "2026-08-21T10:00:00Z"},
        {"id": "f_arith_app", "carrier": "ABF Freight", "check_type": "ARITH", "review_status": "approved", "reviewed_at": "2026-08-22T10:00:00Z"},
    ]

    service.seed_mock_flags(mock_flags)
    return service


def test_precision_analytics_grouped(feedback_service):
    """Tests overall, per-check, and per-carrier precision breakdown."""
    res = feedback_service.get_precision_analytics(month="2026-08")

    overall: PrecisionReportItem = res["overall"]
    # Total approved: 4 (RATE) + 4 (FSC) + 10 (DUP) + 1 (ARITH) = 19
    # Total rejected: 1 (wrong-matrix-row) + 1 (fsc-table-wrong-month) + 1 (misread-pdf-field) = 3
    # Total reviewed: 22. Precision: 19 / 22 = 86.4%
    assert overall.approved_count == 19
    assert overall.rejected_count == 3
    assert overall.total_reviewed == 22
    assert overall.precision_pct == 86.4
    assert res["trajectory_status"] == "BELOW_TARGET"

    # Check type breakdown
    by_check = res["by_check_type"]
    assert by_check["DUP"].precision_pct == 100.0
    assert by_check["DUP"].meets_pilot_target is True
    assert by_check["RATE"].approved_count == 4
    assert by_check["RATE"].rejected_count == 1
    assert by_check["RATE"].precision_pct == 80.0
    assert by_check["FSC"].precision_pct == 80.0
    assert by_check["ARITH"].precision_pct == 50.0

    # Carrier breakdown
    by_carrier = res["by_carrier"]
    assert by_carrier["Roadrunner"].precision_pct == 100.0
    assert by_carrier["Roadrunner"].meets_pilot_target is True
    assert by_carrier["XPO Logistics"].precision_pct == 80.0
    # ABF: 5 approved (4 rate + 1 arith), 2 rejected (1 rate + 1 arith) -> 5/7 = 71.4%
    assert by_carrier["ABF Freight"].approved_count == 5
    assert by_carrier["ABF Freight"].rejected_count == 2
    assert by_carrier["ABF Freight"].precision_pct == 71.4


def test_parser_ticket_generation_mapping(feedback_service):
    """Tests automatic generation of prioritized fix tickets mapped to correct component and remedy."""
    tickets = feedback_service.generate_fix_tickets(month="2026-08")

    assert len(tickets) == 3
    reason_codes_found = {t.reason_code for t in tickets}
    assert "wrong-matrix-row" in reason_codes_found
    assert "fsc-table-wrong-month" in reason_codes_found
    assert "misread-pdf-field" in reason_codes_found

    # Validate mapping to categories
    for t in tickets:
        if t.reason_code == "wrong-matrix-row":
            assert t.category == "contract_parser"
            assert "RateMatrixJSON" in t.recommended_action
            assert t.affected_carrier == "ABF Freight"
            assert t.affected_check_type == "RATE"
        elif t.reason_code == "misread-pdf-field":
            assert t.category == "invoice_parser"
            assert "OCR" in t.recommended_action or "InvoiceParser" in t.recommended_action
        elif t.reason_code == "fsc-table-wrong-month":
            assert t.category == "fsc_engine"
            assert "FSCTable" in t.recommended_action or "EIA" in t.recommended_action
            assert t.affected_carrier == "XPO Logistics"


def test_monthly_retro_report_end_to_end(feedback_service):
    """Tests full monthly retro report generation and Markdown formatting."""
    report: MonthlyRetroReport = feedback_service.run_monthly_retro(month="2026-08")

    assert report.month == "2026-08"
    assert report.total_flags_reviewed == 22
    assert report.total_approved == 19
    assert report.total_rejected == 3
    assert report.overall_precision_pct == 86.4
    assert len(report.top_reason_codes) == 3
    assert len(report.generated_tickets) == 3

    # Format into Markdown
    markdown = format_retro_markdown(report)
    assert "# RateGuard AI — Monthly Precision Retrospective" in markdown
    assert "86.4%" in markdown
    assert "DUP" in markdown
    assert "Roadrunner" in markdown
    assert "wrong-matrix-row" in markdown
    assert "TICKET-CONTRACT_PARSER" in markdown
