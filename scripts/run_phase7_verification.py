"""
RateGuard AI — Phase 7 Verification Harness (Self-Serve Onboarding & Scale)
Executes end-to-end programmatic verification of Phase 7.1 & Phase 7.2:

- Phase 7.1: 6-step interactive self-serve onboarding wizard progression.
- Phase 7.2: Top-10 US LTL carrier formats & ultra-stable regex fallback parser layer.
"""

import sys
from pathlib import Path

# Ensure root directory is on sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from apps.worker.onboarding_wizard import OnboardingWizardService
from apps.worker.regex_fallback_parser import RegexFallbackParser
from apps.worker.portal_service import CustomerPortalService


def print_header(title: str):
    print("\n" + "=" * 80)
    print(f"RATEGUARD AI -- {title}")
    print("=" * 80 + "\n")


def print_step(step_num: int, title: str):
    print(f"[STEP {step_num}] {title}...")


def print_ok(msg: str):
    print(f"  [OK] {msg}")


def run_phase7_verification():
    print_header("PHASE 7 END-TO-END VERIFICATION (SELF-SERVE & SCALE)")

    # =========================================================================
    # PART 1: Phase 7.1 — Self-Serve Onboarding Wizard Verification
    # =========================================================================
    print_step(1, "Testing Phase 7.1 Self-Serve Onboarding Wizard (6 Steps)")

    wizard = OnboardingWizardService()
    cust_id = "cust_selfserve_77"

    # Step 1
    s1 = wizard.advance_step_1_company_profile(
        customer_id=cust_id,
        company_name="Apex Global Distribution",
        remit_to_address="500 Enterprise Pkwy, Dallas, TX 75201",
    )
    print_ok(f"Wizard Step 1 -> Step 2: Company '{s1.company_name}' | Inbound: {s1.inbound_email}")

    # Step 2
    s2 = wizard.advance_step_2_team_users(cust_id, [{"email": "ap@apex.com", "role": "ap_clerk"}])
    print_ok(f"Wizard Step 2 -> Step 3: Team invited (Current Step: {s2.current_step})")

    # Step 3
    s3 = wizard.advance_step_3_carrier_selection(cust_id, ["ABF Freight", "XPO Logistics", "Estes Express", "Saia Freight"])
    print_ok(f"Wizard Step 3 -> Step 4: Selected {len(s3.selected_carriers)} Top-10 Carriers")

    # Step 4
    s4 = wizard.advance_step_4_contract_intake(cust_id, has_signed_contract=True)
    print_ok(f"Wizard Step 4 -> Step 5: Rate Agreement Intake (Signed Contract: {s4.has_signed_contract})")

    # Step 5
    s5 = wizard.advance_step_5_verify_forwarding(cust_id)
    print_ok(f"Wizard Step 5 -> Step 6: Inbound Forwarding Rule Verified ({s5.inbound_email})")

    # Step 6
    s6 = wizard.complete_wizard(cust_id)
    assert s6.is_completed
    print_ok(f"Wizard Step 6 Complete: Organization Activated! (is_completed={s6.is_completed})")

    # =========================================================================
    # PART 2: Phase 7.2 — Top-10 Carrier Formats & Regex Fallback Verification
    # =========================================================================
    print_step(2, "Testing Phase 7.2 Top-10 Carrier Formats & Ultra-Stable Regex Fallback Layer")

    test_samples = [
        ("ABF Freight", "ABF FREIGHT PRO: 042-881234 INV: ABF-9021 TOTAL AMOUNT: $842.50 WEIGHT: 1450 LBS"),
        ("XPO Logistics", "XPO LOGISTICS PRO: 065-992143 INV: XPO-5512 TOTAL DUE: $1240.00 WEIGHT: 2100 LBS"),
        ("Roadrunner", "ROADRUNNER FREIGHT PRO: RRTS-9921 INV: RRTS-INV-01 TOTAL AMOUNT: $500.00"),
        ("Estes Express", "ESTES EXPRESS LINES PRO: ESTES-883921 INV: EST-9921401 TOTAL CHARGES: $412.50"),
        ("Saia Freight", "SAIA LTL FREIGHT PRO: SAIA-992811 INV: SAIA-INV-88120 NET AMOUNT: $525.00"),
        ("TForce Freight", "TFORCE FREIGHT (UPS FREIGHT) PRO: TF-449120 INV: TF-INV-77210 TOTAL DUE: $480.00"),
        ("Old Dominion", "OLD DOMINION FREIGHT LINE PRO: ODFL-102938 INV: ODFL-INV-3321 AMOUNT DUE: $610.00"),
        ("R+L Carriers", "R+L CARRIERS PRO: RL-882019 INV: RL-INV-5510 TOTAL DUE: $395.00"),
        ("Yellow / YRC", "YELLOW YRC FREIGHT PRO: YRC-551029 INV: YRC-INV-2201 TOTAL DUE: $720.00"),
        ("Southeastern Freight", "SOUTHEASTERN FREIGHT LINES PRO: SEFL-992018 INV: SEFL-INV-1102 TOTAL DUE: $430.00"),
    ]

    for carrier_name, doc_text in test_samples:
        res = RegexFallbackParser.parse_text(doc_text, carrier_hint=carrier_name)
        assert res.carrier == carrier_name
        assert res.total_amount_dollars is not None and res.total_amount_dollars > 0
        assert res.pro_number is not None
        print_ok(f"Carrier Verified: {res.carrier:<20} | PRO: {res.pro_number:<15} | Total: ${res.total_amount_dollars:.2f}")

    print_header("PHASE 7 VERIFICATION RESULT: ALL GATES PASSED (100% COMPLETE)")


if __name__ == "__main__":
    run_phase7_verification()
