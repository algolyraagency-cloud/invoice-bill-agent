"""
Verification Harness for Phase 7.3 & Phase 7.4 (Audit Checks 5-8 & Dispute Automation).
Validates:
1. Audit checks 5-8 (Accessorial, Reweigh, Guarantee, Tax) execution on deterministic engine.
2. Overdue dispute reminder nudge scanning and RFC 2368 mailto formatting.
3. Carrier hostility scoring and analytics report generation.
4. Customer portal integration for nudges and carrier intelligence.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

BASE_DIR = Path(__file__).resolve().parent.parent
engine_dir = BASE_DIR / "packages" / "audit-engine"
for p in [str(BASE_DIR), str(engine_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from packages.schemas.models import (
    InvoiceJSON,
    Accessorial,
    LineItem,
    RateMatrixJSON,
)
from orchestrator import audit_invoice

from apps.worker.dispute_tracker_automation import (
    scan_overdue_disputes,
    compute_carrier_hostility_analytics,
)
from apps.worker.portal_service import CustomerPortalService


def run_verification():
    print("======================================================================")
    print("RateGuard AI — Phase 7.3 & 7.4 Verification Harness")
    print("======================================================================")

    # 1. Audit Checks 5-8 Test Case
    print("\n[Step 1] Testing Deterministic Audit Engine Checks 5–8...")

    inv = InvoiceJSON(
        carrier="Estes Express",
        pro_number="PRO-P73-101",
        invoice_number="INV-P73-101",
        invoice_date="2026-09-01",
        origin_zip="90210",
        dest_zip="60601",
        billed_weight=1400,
        invoice_total=680.0,
        accessorials=[
            Accessorial(type="Liftgate", amount=90.0, authorized=False),
        ],
        line_items=[
            LineItem(description="Base Freight", amount=450.0),
            LineItem(description="Reweigh Inspection Charge", amount=65.0),
            LineItem(description="Guaranteed AM Delivery", amount=45.0),
            LineItem(description="State Sales Tax", amount=30.0),
        ],
    )

    flags = audit_invoice(
        invoice=inv,
        rate_matrices=[],
        certified_reweigh=False,
        guaranteed_service=True,
        promised_delivery_date="2026-09-03",
        actual_delivery_date="2026-09-05",
        is_interstate=True,
    )

    check_types = {f.check_type for f in flags}
    print(f"  -> Generated {len(flags)} flags across check types: {sorted(list(check_types))}")

    assert "ACCESSORIAL" in check_types, "Check 5 (ACCESSORIAL) failed to trigger!"
    assert "REWEIGH" in check_types, "Check 6 (REWEIGH) failed to trigger!"
    assert "GUARANTEE" in check_types, "Check 7 (GUARANTEE) failed to trigger!"
    assert "TAX" in check_types, "Check 8 (TAX) failed to trigger!"
    print("  [SUCCESS] All 4 Audit Checks 5-8 verified successfully!")

    # 2. Overdue Dispute Reminder Nudges
    print("\n[Step 2] Testing Dispute Status Tracking & Reminder Nudges (>14 Days)...")

    ref_dt = datetime.now(timezone.utc)
    sent_22_days_ago = (ref_dt - timedelta(days=22)).isoformat()

    sample_disputes = [
        {
            "dispute_id": "disp_verif_01",
            "pro_number": "PRO-OVERDUE-99",
            "invoice_number": "INV-99",
            "carrier": "FedEx Freight",
            "carrier_dispute_email": "disputes@fedex.com",
            "customer_id": "cust_acme_01",
            "customer_name": "Acme Imports",
            "status": "sent",
            "sent_at": sent_22_days_ago,
            "overcharge_dollars": 120.50,
        }
    ]

    nudges = scan_overdue_disputes(sample_disputes, days_threshold=14, reference_date=ref_dt)
    assert len(nudges) == 1, "Failed to identify overdue dispute nudge!"
    assert nudges[0].days_since_sent >= 14, "Incorrect days_since_sent calculation!"
    assert "mailto:disputes%40fedex.com" in nudges[0].mailto_reminder_link, "Mailto link encoding error!"
    print(f"  -> Formatted 1-Click Mailto Link: {nudges[0].mailto_reminder_link[:70]}...")
    print("  [SUCCESS] Overdue dispute reminder nudge automation verified successfully!")

    # 3. Carrier Hostility Analytics
    print("\n[Step 3] Testing Carrier Hostility Analytics & Scorecard...")

    analytics_disputes = [
        {"carrier": "Estes Express", "status": "credit_issued", "overcharge_dollars": 150.0, "sent_at": sent_22_days_ago, "updated_at": (ref_dt - timedelta(days=18)).isoformat()},
        {"carrier": "Estes Express", "status": "credit_issued", "overcharge_dollars": 200.0, "sent_at": sent_22_days_ago, "updated_at": (ref_dt - timedelta(days=15)).isoformat()},
        {"carrier": "Hostile Logistics", "status": "denied", "overcharge_dollars": 350.0, "sent_at": sent_22_days_ago, "updated_at": (ref_dt - timedelta(days=2)).isoformat()},
        {"carrier": "Hostile Logistics", "status": "denied", "overcharge_dollars": 400.0, "sent_at": sent_22_days_ago, "updated_at": (ref_dt - timedelta(days=1)).isoformat()},
    ]

    report = compute_carrier_hostility_analytics(analytics_disputes, customer_id="cust_acme_01")
    assert report.total_carriers_tracked == 2, "Carrier count mismatch!"
    assert report.highest_hostility_carrier == "Hostile Logistics", "Highest hostility carrier mismatch!"
    assert report.lowest_hostility_carrier == "Estes Express", "Lowest hostility carrier mismatch!"

    print(f"  -> Total Tracked Carriers: {report.total_carriers_tracked}")
    print(f"  -> Highest Hostility Carrier: {report.highest_hostility_carrier} (Score: {report.carriers[0].hostility_score}, Status: {report.carriers[0].hostility_status})")
    print(f"  -> Lowest Hostility Carrier: {report.lowest_hostility_carrier} (Score: {report.carriers[1].hostility_score}, Status: {report.carriers[1].hostility_status})")
    print("  [SUCCESS] Carrier Hostility Analytics report verified successfully!")

    # 4. Customer Portal Service Integration
    print("\n[Step 4] Testing Customer Portal Service API Integration...")
    portal = CustomerPortalService()
    portal.seed_customer("cust_acme_01", "Acme Imports", "acme-imports")
    portal.seed_invoice("inv_p7", "cust_acme_01", "FedEx Freight", "INV-P7-01", "PRO-P7-01", "2026-08-01", 600.0)
    portal.seed_flag("flag_p7", "inv_p7", "RATE", 6000, {"note": "Overcharge"}, review_status="approved")
    portal.seed_dispute("disp_p7", "flag_p7", status="sent", customer_id="cust_acme_01")
    portal._disputes["disp_p7"]["sent_at"] = sent_22_days_ago

    reminders = portal.list_dispute_reminders("cust_acme_01", days_threshold=14)
    assert len(reminders) == 1, "Portal list_dispute_reminders failed!"

    analytics_report = portal.get_carrier_analytics("cust_acme_01")
    assert analytics_report.total_disputes == 1, "Portal get_carrier_analytics failed!"
    print("  [SUCCESS] Customer Portal Service integration verified successfully!")

    print("\n======================================================================")
    print("ALL PHASE 7.3 & 7.4 VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("======================================================================")
    return True


if __name__ == "__main__":
    success = run_verification()
    if not success:
        sys.exit(1)
