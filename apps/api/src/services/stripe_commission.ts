/**
 * RateGuard AI — Stripe Commission Invoicing API Service (Phase 6.2)
 * TypeScript API service layer for monthly commission billing and denied dispute resends.
 */

import {
  CommissionInvoiceRecord,
  CommissionInvoiceItem,
  ResendDisputeInput,
  UnrecoverableDisputeRecord,
} from '@rateguard/schemas';

export class StripeCommissionAPIService {
  /**
   * Generates a monthly Net-15 commission invoice from verified credit memos.
   * Throws Error if any credit memo is not verified (Revenue Integrity Control).
   */
  static generateMonthlyCommissionInvoice(
    customerId: string,
    customerName: string,
    billingPeriod: string,
    verifiedMemos: Array<{ id: string; memo_number: string; verification_status: string; amount_dollars: number; carrier: string; original_invoice_ref: string; matched_dispute_id?: string }>,
    disputesMap: Record<string, { pro_number: string; is_concierge_handled?: boolean }>,
    contingencyFeePct: number = 35.0
  ): CommissionInvoiceRecord {
    const items: CommissionInvoiceItem[] = [];
    let totalGrossCents = 0;
    let totalCommissionCents = 0;

    for (const memo of verifiedMemos) {
      if (memo.verification_status !== 'verified') {
        throw new Error(
          `Revenue Integrity Violation: Credit Memo '${memo.memo_number}' is not verified. Commission invoices can ONLY be generated from verified credit memos.`
        );
      }

      const grossDollars = memo.amount_dollars;
      const grossCents = Math.round(grossDollars * 100);
      const dispute = memo.matched_dispute_id ? disputesMap[memo.matched_dispute_id] : undefined;

      const ratePct = dispute?.is_concierge_handled ? 40.0 : contingencyFeePct;
      const feeCents = Math.round(grossCents * (ratePct / 100.0));
      const feeDollars = Math.round(feeCents) / 100.0;

      totalGrossCents += grossCents;
      totalCommissionCents += feeCents;

      items.push({
        credit_memo_id: memo.id,
        dispute_id: memo.matched_dispute_id || '',
        carrier: memo.carrier,
        pro_number: dispute?.pro_number || memo.original_invoice_ref,
        original_invoice_ref: memo.original_invoice_ref,
        gross_credit_cents: grossCents,
        gross_credit_dollars: grossDollars,
        commission_rate_pct: ratePct,
        commission_cents: feeCents,
        commission_dollars: feeDollars,
      });
    }

    const now = new Date();
    const dueDate = new Date(now.getTime() + 15 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
    const invoiceId = `inv_rg_${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}_${customerId.slice(0, 8)}`;

    return {
      id: invoiceId,
      customer_id: customerId,
      customer_name: customerName,
      billing_period: billingPeriod,
      items,
      total_gross_credit_cents: totalGrossCents,
      total_gross_credit_dollars: Math.round(totalGrossCents) / 100.0,
      total_commission_cents: totalCommissionCents,
      total_commission_dollars: Math.round(totalCommissionCents) / 100.0,
      stripe_invoice_id: `in_mock_${invoiceId}`,
      stripe_hosted_url: `https://pay.rateguard.app/invoice/${invoiceId}`,
      status: 'sent',
      net_terms_due_at: dueDate,
      created_at: now.toISOString(),
    };
  }

  /**
   * Handles denied dispute resends or transitions to unrecoverable.
   */
  static handleDeniedDispute(
    dispute: { id: string; customer_id: string; carrier: string; pro_number: string; invoice_number: string; overcharge_dollars: number; resend_count?: number },
    input: ResendDisputeInput
  ): { action: 'resent_with_evidence' | 'marked_unrecoverable'; dispute: any; unrecoverable_record?: UnrecoverableDisputeRecord } {
    const resendCount = dispute.resend_count || 0;

    if (resendCount < 1) {
      const updatedDispute = {
        ...dispute,
        resend_count: resendCount + 1,
        status: 'resent_with_evidence',
        stronger_evidence_notes: input.stronger_evidence_notes,
        last_resend_at: new Date().toISOString(),
      };
      return { action: 'resent_with_evidence', dispute: updatedDispute };
    }

    const unrecRecord: UnrecoverableDisputeRecord = {
      dispute_id: dispute.id,
      customer_id: dispute.customer_id,
      carrier: dispute.carrier,
      pro_number: dispute.pro_number,
      original_invoice_number: dispute.invoice_number,
      overcharge_dollars: dispute.overcharge_dollars,
      denial_reason: input.stronger_evidence_notes || 'Carrier final denial after automated resend',
      marked_unrecoverable_at: new Date().toISOString(),
    };

    const updatedDispute = {
      ...dispute,
      status: 'unrecoverable',
      unrecoverable_at: unrecRecord.marked_unrecoverable_at,
    };

    return { action: 'marked_unrecoverable', dispute: updatedDispute, unrecoverable_record: unrecRecord };
  }
}
