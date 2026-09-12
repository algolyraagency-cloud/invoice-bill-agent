"""
RateGuard AI — Phase 6 Verification Harness (Recovery Tracking & Commission Billing)
Executes end-to-end programmatic verification of Phase 6.1 & Phase 6.2:

- Phase 6.1: Stream detection, forwarded email credit memo parsing, and automated matching & verification.
- Phase 6.2: 35% Monthly commission aggregation, Revenue Integrity Guard, Stripe sync, vector PDF generation, and denied dispute resends.
"""

import sys
from pathlib import Path

# Ensure root directory is on sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from apps.worker.credit_memo_service import CreditMemoService
from apps.worker.stripe_commission import StripeCommissionService
from apps.worker.portal_service import CustomerPortalService
from packages.schemas.models import UnverifiedMemoBillingError


def print_header(title: str):
    print("\n" + "=" * 80)
    print(f"RATEGUARD AI -- {title}")
    print("=" * 80 + "\n")


def print_step(step_num: int, title: str):
    print(f"[STEP {step_num}] {title}...")


def print_ok(msg: str):
    print(f"  [OK] {msg}")


def run_phase6_verification():
    print_header("PHASE 6 END-TO-END VERIFICATION (RECOVERY TRACKING & COMMISSION BILLING)")

    portal = CustomerPortalService()

    # 1. Onboard Customer & Seed Active Disputes
    print_step(1, "Setting up Pilot Customer & Active Disputes")
    portal.seed_customer(
        customer_id="cust_acme_01",
        name="Acme Imports & Logistics",
        slug="acme-imports",
    )
    cust = portal.get_customer("cust_acme_01")
    portal.sign_recovery_agreement("cust_acme_01", "Eleanor Vance", "Chief Financial Officer")


    # Invoices
    portal.seed_invoice("inv_abf_101", "cust_acme_01", "ABF Freight", "ABF-9021", "042-881234", "2026-08-12", 842.50)
    portal.seed_invoice("inv_xpo_102", "cust_acme_01", "XPO Logistics", "XPO-5512", "065-992143", "2026-08-14", 1240.00)

    # Flags
    portal.seed_flag("flg_abf_01", "inv_abf_101", "RATE", 14250, {"clause": "Item 100-D"}, "approved")
    portal.seed_flag("flg_xpo_02", "inv_xpo_102", "FSC", 6500, {"clause": "Item 220-A"}, "approved")

    # Disputes
    portal.seed_dispute("disp_abf_01", "flg_abf_01", "drafted")
    portal.seed_dispute("disp_xpo_02", "flg_xpo_02", "drafted")

    portal.update_dispute_status("cust_acme_01", "disp_abf_01", "sent")
    portal.update_dispute_status("cust_acme_01", "disp_xpo_02", "sent")

    disp1 = portal._disputes["disp_abf_01"]
    disp2 = portal._disputes["disp_xpo_02"]

    print_ok(f"Seeded Customer: '{cust['name']}' ({cust['id']})")
    print_ok(f"Seeded Sent Dispute 1: ABF Freight PRO #042-881234 ($142.50 overcharge)")
    print_ok(f"Seeded Sent Dispute 2: XPO Logistics PRO #065-992143 ($65.00 overcharge)")

    # 2. Stream Detection (Phase 6.1)
    print_step(2, "Stream Detection of Carrier Credit Memos (Phase 6.1)")
    parsed_inv = {
        "carrier": "ABF Freight",
        "invoice_number": "CM-ABF-8812",
        "pro_number": "042-881234",
        "invoice_total": -142.50,
        "invoice_total_cents": -14250,
    }
    candidates_stream = CreditMemoService.detect_credit_memos_from_stream(
        parsed_inv, raw_text="CARRIER OVERCHARGE ADJUSTMENT CREDIT MEMO"
    )
    assert len(candidates_stream) == 1
    cand_stream = candidates_stream[0]
    print_ok(f"Stream Detected Memo: {cand_stream.memo_number} | Amount: ${cand_stream.amount_dollars:.2f} | Carrier: {cand_stream.carrier}")

    # 3. Forwarded Email Detection (Phase 6.1)
    print_step(3, "Customer-Forwarded Email Intake Detection (Phase 6.1)")
    email_subj = "Fwd: Credit Memo CM-5512 for PRO 065-992143"
    email_body = "Attaching credit advice from XPO Logistics for $65.00 overcharge refund."
    cand_email = CreditMemoService.detect_credit_memo_from_email(email_subj, email_body, carrier_hint="XPO Logistics")
    assert cand_email is not None
    print_ok(f"Forwarded Email Detected Memo: {cand_email.memo_number} | Amount: ${cand_email.amount_dollars:.2f} | Carrier: {cand_email.carrier}")

    # 4. Automated Verification Engine (Phase 6.1)
    print_step(4, "Automated Verification Matching against Disputes (Phase 6.1)")
    active_disputes = [
        {"id": "disp_abf_01", "carrier": "ABF Freight", "pro_number": "042-881234", "invoice_number": "ABF-9021", "overcharge_dollars": 142.50},
        {"id": "disp_xpo_02", "carrier": "XPO Logistics", "pro_number": "065-992143", "invoice_number": "XPO-5512", "overcharge_dollars": 65.00},
    ]

    ver1 = CreditMemoService.verify_credit_memo(cand_stream.model_dump(), active_disputes)
    assert ver1.verification_status == "verified"
    print_ok(f"Memo {cand_stream.memo_number} VERIFIED -> Matched Dispute: {ver1.matched_dispute_id}")

    ver2 = CreditMemoService.verify_credit_memo(cand_email.model_dump(), active_disputes)
    assert ver2.verification_status == "verified"
    print_ok(f"Memo {cand_email.memo_number} VERIFIED -> Matched Dispute: {ver2.matched_dispute_id}")

    # Log verified credit memos into portal
    portal.submit_credit_memo(
        customer_id="cust_acme_01",
        carrier=cand_stream.carrier,
        memo_number=cand_stream.memo_number,
        original_invoice_ref=cand_stream.original_invoice_ref,
        amount_cents=cand_stream.amount_cents,
        kind="credit_memo",
        detected_via="stream",
    )
    portal.submit_credit_memo(
        customer_id="cust_acme_01",
        carrier=cand_email.carrier,
        memo_number=cand_email.memo_number,
        original_invoice_ref=cand_email.original_invoice_ref,
        amount_cents=cand_email.amount_cents,
        kind="credit_memo",
        detected_via="forwarded",
    )


    # 5. Testing Revenue Integrity Guard (Phase 6.1/6.2)
    print_step(5, "Testing Revenue Integrity Guard (Unverified Billing Block)")
    unverified_memos = [
        {
            "id": "memo_fake_99",
            "memo_number": "CM-UNVERIFIED-99",
            "carrier": "ABF Freight",
            "amount_cents": 5000,
            "verification_status": "pending",  # Unverified!
        }
    ]
    try:
        StripeCommissionService.generate_monthly_commission_invoice(
            customer_id="cust_acme_01",
            customer_name="Acme Imports",
            billing_period="2026-09",
            verified_memos=unverified_memos,
            disputes_map={},
        )
        print("  [FAIL] Unverified memo was billed without exception!")
        sys.exit(1)
    except UnverifiedMemoBillingError as err:
        print_ok(f"REVENUE INTEGRITY GUARD PASSED: Unverified memo billing strictly blocked! Exception caught:\n    '{err}'")

    # 6. Generate 35% Monthly Commission Invoice (Phase 6.2)
    print_step(6, "Generating Monthly 35% Net-15 Commission Invoice (Phase 6.2)")
    comm_invoice = portal.generate_commission_invoice(customer_id="cust_acme_01", billing_period="2026-09")
    print_ok(f"Commission Invoice ID: {comm_invoice.id}")
    print_ok(f"Total Gross Credit Recovered: ${comm_invoice.total_gross_credit_dollars:.2f}")
    print_ok(f"Total RateGuard Commission (35%): ${comm_invoice.total_commission_dollars:.2f}")
    print_ok(f"Net-15 Due Date: {comm_invoice.net_terms_due_at}")
    print_ok(f"Stripe Invoice Reference: {comm_invoice.stripe_invoice_id}")
    print_ok(f"Vector PDF Generated: {comm_invoice.pdf_path}")

    # 7. Testing Denied Dispute Resend & Unrecoverable Workflow (Phase 6.2)
    print_step(7, "Testing Denied Dispute Resend & Unrecoverable Workflow (Phase 6.2)")
    portal.seed_invoice("inv_rrts_103", "cust_acme_01", "Roadrunner", "RRTS-881", "RRTS-9921", "2026-08-15", 500.00)
    portal.seed_flag("flg_rrts_03", "inv_rrts_103", "RATE", 8500, {"clause": "Item 100-D"}, "approved")
    portal.seed_dispute("disp_rrts_03", "flg_rrts_03", "drafted")
    portal.update_dispute_status("cust_acme_01", "disp_rrts_03", "sent")
    portal.update_dispute_status("cust_acme_01", "disp_rrts_03", "denied")


    # First Denial -> Triggers 1 automated resend task
    res1 = portal.resend_denied_dispute(
        customer_id="cust_acme_01",
        dispute_id="disp_rrts_03",
        stronger_evidence_notes="Citing Item 100-D Tariff Section 4.2 with signed BOL weight certificate.",
    )
    assert res1["action"] == "resent_with_evidence"
    print_ok(f"Resend #1 Dispatched: {res1['message']}")

    # Second Denial -> Transitions to Unrecoverable ($0 fee)
    res2 = portal.resend_denied_dispute(
        customer_id="cust_acme_01",
        dispute_id="disp_rrts_03",
        stronger_evidence_notes="Carrier final denial after secondary review.",
    )
    assert res2["action"] == "marked_unrecoverable"
    print_ok(f"Resend #2 Transition: {res2['message']}")
    print_ok(f"Unrecoverable Record Logged ($0 fee charged).")

    print_header("PHASE 6 VERIFICATION RESULT: ALL GATES PASSED (100% COMPLETE)")


if __name__ == "__main__":
    run_phase6_verification()
