"""
Unit tests for Dispute Tracker Automation & Carrier Hostility Analytics (Phase 7.4).
Covers:
- scan_overdue_disputes (>14 days threshold & 1-click mailto generation)
- compute_carrier_hostility_analytics (approval/denial ratios, latency, hostility score, status)
- CustomerPortalService dispute reminders & carrier analytics methods
"""
from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from apps.worker.dispute_tracker_automation import (
    compute_carrier_hostility_analytics,
    scan_overdue_disputes,
)
from apps.worker.portal_service import CustomerPortalService


def test_scan_overdue_disputes():
    ref_dt = datetime(2026, 9, 12, 12, 0, 0, tzinfo=timezone.utc)
    sent_20_days_ago = (ref_dt - timedelta(days=20)).isoformat()
    sent_5_days_ago = (ref_dt - timedelta(days=5)).isoformat()

    disputes = [
        {
            "dispute_id": "disp_01",
            "pro_number": "PRO-OVERDUE-01",
            "invoice_number": "INV-01",
            "carrier": "FedEx Freight",
            "carrier_dispute_email": "disputes@fedex.com",
            "customer_id": "cust_acme_01",
            "customer_name": "Acme Imports",
            "status": "sent",
            "sent_at": sent_20_days_ago,
            "overcharge_dollars": 145.00,
        },
        {
            "dispute_id": "disp_02",
            "pro_number": "PRO-RECENT-02",
            "invoice_number": "INV-02",
            "carrier": "Estes Express",
            "carrier_dispute_email": "claims@estes.com",
            "customer_id": "cust_acme_01",
            "customer_name": "Acme Imports",
            "status": "sent",
            "sent_at": sent_5_days_ago,
            "overcharge_dollars": 60.00,
        },
        {
            "dispute_id": "disp_03",
            "pro_number": "PRO-CLOSED-03",
            "carrier": "Old Dominion",
            "status": "credit_issued",
            "sent_at": sent_20_days_ago,
        },
    ]

    nudges = scan_overdue_disputes(disputes, days_threshold=14, reference_date=ref_dt)
    assert len(nudges) == 1
    assert nudges[0].dispute_id == "disp_01"
    assert nudges[0].pro_number == "PRO-OVERDUE-01"
    assert nudges[0].days_since_sent == 20
    assert "mailto:disputes%40fedex.com" in nudges[0].mailto_reminder_link
    assert "REMINDER: Unresolved Billing Dispute Notice" in nudges[0].reminder_subject


def test_compute_carrier_hostility_analytics():
    ref_dt = datetime(2026, 9, 12, 12, 0, 0, tzinfo=timezone.utc)
    d1 = (ref_dt - timedelta(days=25)).isoformat()
    d2 = (ref_dt - timedelta(days=5)).isoformat()

    disputes = [
        # Carrier A (Friendly): 4 approved, 1 pending
        {"carrier": "Estes Express", "status": "credit_issued", "overcharge_dollars": 100.0, "sent_at": d1, "updated_at": d2},
        {"carrier": "Estes Express", "status": "credit_issued", "overcharge_dollars": 50.0, "sent_at": d1, "updated_at": d2},
        {"carrier": "Estes Express", "status": "credit_issued", "overcharge_dollars": 75.0, "sent_at": d1, "updated_at": d2},
        {"carrier": "Estes Express", "status": "sent", "overcharge_dollars": 40.0, "sent_at": d2},

        # Carrier B (Hostile): 1 approved, 4 denied
        {"carrier": "Hostile Trucking", "status": "denied", "overcharge_dollars": 200.0, "sent_at": d1, "updated_at": d2},
        {"carrier": "Hostile Trucking", "status": "denied", "overcharge_dollars": 300.0, "sent_at": d1, "updated_at": d2},
        {"carrier": "Hostile Trucking", "status": "denied", "overcharge_dollars": 150.0, "sent_at": d1, "updated_at": d2},
        {"carrier": "Hostile Trucking", "status": "denied", "overcharge_dollars": 100.0, "sent_at": d1, "updated_at": d2},
        {"carrier": "Hostile Trucking", "status": "credit_issued", "overcharge_dollars": 50.0, "sent_at": d1, "updated_at": d2},
    ]

    report = compute_carrier_hostility_analytics(disputes, customer_id="cust_acme_01")
    assert report.total_carriers_tracked == 2
    assert report.highest_hostility_carrier == "Hostile Trucking"
    assert report.lowest_hostility_carrier == "Estes Express"

    hostile_m = next(c for c in report.carriers if c.carrier == "Hostile Trucking")
    assert hostile_m.hostility_status == "hostile"
    assert hostile_m.denial_rate_pct == 80.0

    friendly_m = next(c for c in report.carriers if c.carrier == "Estes Express")
    assert friendly_m.hostility_status in ["friendly", "moderate"]

    assert friendly_m.approval_rate_pct == 75.0


def test_portal_service_dispute_automation():
    service = CustomerPortalService()
    service.seed_customer("cust_test", "Test Shipper", "test-shipper")
    
    service.seed_invoice("inv_1", "cust_test", "Estes Express", "INV-101", "PRO-101", "2026-08-01", 500.0)
    service.seed_flag("flag_1", "inv_1", "RATE", 5000, {"note": "Overcharge"}, review_status="approved")
    service.seed_dispute("disp_1", "flag_1", status="sent", customer_id="cust_test")
    service._disputes["disp_1"]["sent_at"] = "2026-08-10T10:00:00+00:00"

    reminders = service.list_dispute_reminders("cust_test", days_threshold=14)
    assert len(reminders) == 1
    assert reminders[0].carrier == "Estes Express"

    analytics = service.get_carrier_analytics("cust_test")
    assert analytics.total_disputes == 1
    assert analytics.carriers[0].carrier == "Estes Express"
