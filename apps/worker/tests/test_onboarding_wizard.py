"""
RateGuard AI — Onboarding Wizard Service Unit Tests (Phase 7.1)
Tests 6-step self-serve onboarding state progression, inputs, and completion handler.
"""

import pytest
from apps.worker.onboarding_wizard import OnboardingWizardService
from packages.schemas.models import OnboardingWizardState


def test_wizard_init_and_step1_progression():
    """Verify onboarding wizard initialization and step 1 company profile progression."""
    service = OnboardingWizardService()
    cust_id = "cust_new_01"

    init_state = service.init_wizard(cust_id, "Acme Logistics", "acme-logistics")
    assert init_state.current_step == 1
    assert init_state.inbound_email == "acme-logistics@in.rateguard.app"
    assert not init_state.is_completed

    s1_state = service.advance_step_1_company_profile(
        customer_id=cust_id,
        company_name="Acme Logistics LLC",
        remit_to_address="500 Enterprise Way, Chicago, IL 60601",
    )
    assert s1_state.current_step == 2
    assert s1_state.remit_to_address == "500 Enterprise Way, Chicago, IL 60601"


def test_full_6_step_wizard_completion():
    """Verify complete 6-step wizard progression to state activation."""
    service = OnboardingWizardService()
    cust_id = "cust_full_02"

    service.init_wizard(cust_id, "Apex Distribution", "apex-dist")
    service.advance_step_1_company_profile(cust_id, "Apex Distribution", "100 Main St")
    service.advance_step_2_team_users(cust_id, [{"email": "ap@apex.com", "role": "ap_clerk"}])
    service.advance_step_3_carrier_selection(cust_id, ["ABF Freight", "XPO Logistics", "Estes Express"])
    service.advance_step_4_contract_intake(cust_id, has_signed_contract=True)
    service.advance_step_5_verify_forwarding(cust_id)
    final_state = service.complete_wizard(cust_id)

    assert final_state.current_step == 6
    assert final_state.is_completed
    assert final_state.forwarding_verified
    assert len(final_state.selected_carriers) == 3
