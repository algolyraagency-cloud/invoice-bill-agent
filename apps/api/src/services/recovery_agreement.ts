/**
 * RateGuard AI — Recovery Agreement Service (TypeScript / Node Runtime).
 * Implements Phase 5.4: 1-Page Contingency Recovery Agreement Gate.
 * Enforces hard gate blocking dispute letter exports until recovery_agreement_signed_at is set.
 */

import { SupabaseClient } from '@supabase/supabase-js';
import {
  RecoveryAgreementRecord,
  RecoveryAgreementSignInput,
} from '../../../packages/schemas/index';

/**
 * Verifies if customer has signed the 1-page Recovery Agreement.
 * Throws an error if unsigned, blocking dispute exports.
 */
export async function verifyRecoveryAgreementGate(
  customerId: string,
  supabase: SupabaseClient
): Promise<boolean> {
  const { data: customer, error } = await supabase
    .from('customers')
    .select('id, name, recovery_agreement_signed_at')
    .eq('id', customerId)
    .single();

  if (error || !customer) {
    throw new Error(`Customer organization '${customerId}' not found.`);
  }

  if (!customer.recovery_agreement_signed_at) {
    throw new Error(
      `Recovery Agreement Launch Gate: Customer '${customer.name}' has not signed the 1-page ` +
      'contingency recovery agreement. Dispute letter generation and carrier exports are strictly ' +
      'gated until agreement signature (PRD Flow A & Implementation §5.4).'
    );
  }

  return true;
}

/**
 * Renders the plain text 1-page Recovery Agreement for customer review in portal.
 */
export function getRecoveryAgreementText(
  customerName: string,
  conciergeHandling = false
): string {
  const feePct = conciergeHandling ? 40.0 : 35.0;
  return `================================================================================
RATEGUARD AI — FREIGHT AUDIT & RECOVERY CONTINGENCY AGREEMENT
================================================================================
PARTIES:
  Provider: RateGuard AI Inc. ("RateGuard")
  Client:   ${customerName} ("Shipper")
  Date:     ${new Date().toISOString().split('T')[0]}

1. PURPOSE & SCOPE OF ENGAGEMENT
Shipper engages RateGuard to audit freight billing, carrier rate tariffs, fuel surcharges, 
and accessorial charges across Shipper's LTL carrier invoice stream.

2. CONTINGENCY PRICING & PAYMENT TERMS (NO RECOVERY = ZERO OWED)
  (a) Contingency Fee: Shipper agrees to pay RateGuard ${feePct.toFixed(1)}% of all verified overcharge 
      recoveries, credit memos, or refund checks issued by carriers.
  (b) Billing Trigger: RateGuard invoices Shipper upon carrier issuance of a verified credit memo 
      or refund check ("Memo-Basis Trigger"), regardless of cash flow application.
  (c) Payment Terms: Net-15 days from date of RateGuard commission invoice.

3. DISPUTE MECHANISM — "WE DRAFT, YOU SEND"
  (a) RateGuard prepares mathematically verified dispute notices citing exact carrier contract 
      clauses and overcharges.
  (b) RateGuard shall not act as a direct legal party or communicate directly with carriers 
      without Shipper involvement. Shipper dispatches dispute notices directly to carriers.
  (c) All dispute email correspondence shall CC disputes+slug@in.rateguard.app for status tracking.

4. CONFIDENTIALITY & DATA SECURITY
RateGuard agrees to maintain strict confidentiality of Shipper's rate contracts, lane volumes, 
and invoice documentation in accordance with SOC-2 guidelines. Data shall never be sold or shared.

5. EXECUTION & ACKNOWLEDGEMENT
By checking the agreement box and submitting e-signature, the undersigned officer certifies 
authority to bind Shipper to this 1-page contingency recovery agreement.
================================================================================`;
}

/**
 * Executes e-signature for 1-page Recovery Agreement:
 * - Updates customer.recovery_agreement_signed_at timestamp in Supabase
 * - Saves contract agreement record
 */
export async function signRecoveryAgreement(
  input: RecoveryAgreementSignInput,
  supabase: SupabaseClient
): Promise<RecoveryAgreementRecord> {
  if (!input.agree_terms) {
    throw new Error('You must explicitly check the terms acknowledgement box to sign the agreement.');
  }

  const nowIso = new Date().toISOString();

  // 1. Fetch customer
  const { data: customer, error: custErr } = await supabase
    .from('customers')
    .select('id, name, slug')
    .eq('id', input.customer_id)
    .single();

  if (custErr || !customer) {
    throw new Error(`Customer organization '${input.customer_id}' not found.`);
  }

  // 2. Update customer record signed_at timestamp
  const { error: updateErr } = await supabase
    .from('customers')
    .update({
      recovery_agreement_signed_at: nowIso,
      updated_at: nowIso,
    })
    .eq('id', input.customer_id);

  if (updateErr) {
    throw new Error(`Failed to update customer agreement status: ${updateErr.message}`);
  }

  const feePct = input.concierge_handling ? 40.0 : 35.0;
  const agreementId = `AGR-${Date.now()}`;
  const pdfPath = `generated-pdfs/${customer.slug}/recovery_agreement_${input.customer_id}.pdf`;

  return {
    agreement_id: agreementId,
    customer_id: input.customer_id,
    customer_name: customer.name,
    contingency_fee_pct: feePct,
    signed_at: nowIso,
    signer_name: input.signer_name,
    signer_title: input.signer_title,
    pdf_path: pdfPath,
    is_active: true,
  };
}
