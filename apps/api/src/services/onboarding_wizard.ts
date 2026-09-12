/**
 * RateGuard AI — Self-Serve Onboarding Wizard API Service (Phase 7.1)
 * TypeScript API service layer handling the 6-step interactive onboarding progression.
 */

import { OnboardingWizardState } from '@rateguard/schemas';

export class OnboardingWizardAPIService {
  /**
   * Initializes or fetches 6-step onboarding wizard state.
   */
  static getWizardState(customerId: string, companyName: string, slug: string): OnboardingWizardState {
    const inbound = `${slug}@in.rateguard.app`;
    const disputeTracking = `disputes+${slug}@in.rateguard.app`;

    return {
      customer_id: customerId,
      current_step: 1,
      company_name: companyName,
      slug,
      remit_to_address: '100 Commerce Way, Suite 400, Chicago, IL 60601',
      selected_carriers: ['ABF Freight', 'XPO Logistics', 'Roadrunner', 'Estes Express', 'Saia Freight'],
      has_signed_contract: true,
      forwarding_verified: true,
      inbound_email: inbound,
      dispute_tracking_email: disputeTracking,
      is_completed: false,
      updated_at: new Date().toISOString(),
    };
  }

  /**
   * Advances wizard to target step.
   */
  static advanceStep(
    currentState: OnboardingWizardState,
    targetStep: number,
    payload: Partial<OnboardingWizardState>
  ): OnboardingWizardState {
    const isCompleted = targetStep >= 6;
    return {
      ...currentState,
      ...payload,
      current_step: Math.max(currentState.current_step, targetStep),
      is_completed: isCompleted,
      updated_at: new Date().toISOString(),
    };
  }
}
