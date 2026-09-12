/**
 * RateGuard AI — Credit Memo Detection & Verification API Service (Phase 6.1)
 * TypeScript API service layer interfacing with Supabase for credit memo stream detection and matching.
 */

import {
  CreditMemoDetectionCandidate,
  CreditMemoVerificationResult,
  CreditMemoListItem,
} from '@rateguard/schemas';

export class CreditMemoAPIService {
  /**
   * Detects credit memo candidates from invoice stream parsing.
   */
  static detectCreditMemosFromStream(
    parsedInvoice: { carrier: string; invoice_number: string; pro_number?: string; invoice_total: number; invoice_total_cents?: number },
    rawText: string = '',
    fileName: string = ''
  ): CreditMemoDetectionCandidate[] {
    const textToCheck = `${rawText} ${fileName}`.toUpperCase();
    const isNegative = parsedInvoice.invoice_total < 0 || (parsedInvoice.invoice_total_cents && parsedInvoice.invoice_total_cents < 0);
    const hasKeywords = textToCheck.includes('CREDIT MEMO') || textToCheck.includes('CREDIT ADVICE') || textToCheck.includes('STATEMENT OF ADJUSTMENT');

    if (!isNegative && !hasKeywords) {
      return [];
    }

    const absDollars = Math.abs(parsedInvoice.invoice_total);
    const absCents = Math.round(absDollars * 100);

    return [
      {
        carrier: parsedInvoice.carrier || 'Unknown Carrier',
        memo_number: parsedInvoice.invoice_number || `CM-${absCents}`,
        original_invoice_ref: parsedInvoice.pro_number || parsedInvoice.invoice_number || 'N/A',
        amount_cents: absCents,
        amount_dollars: absDollars,
        kind: textToCheck.includes('CHECK') ? 'refund_check' : 'credit_memo',
        detected_via: 'stream',
        raw_text_snippet: textToCheck.slice(0, 200),
        confidence_score: isNegative && hasKeywords ? 0.95 : 0.85,
      },
    ];
  }

  /**
   * Matches candidate credit memo against active disputes for a customer.
   */
  static verifyCreditMemo(
    candidate: CreditMemoDetectionCandidate & { id?: string },
    activeDisputes: Array<{ id: string; carrier: string; pro_number: string; invoice_number: string; overcharge_dollars: number }>
  ): CreditMemoVerificationResult {
    const memoCarrier = (candidate.carrier || '').toLowerCase();
    const memoRef = (candidate.original_invoice_ref || '').toLowerCase();
    const memoAmount = candidate.amount_dollars;

    const matched = activeDisputes.find((disp) => {
      const dispCarrier = disp.carrier.toLowerCase();
      const dispPro = disp.pro_number.toLowerCase();
      const dispInv = disp.invoice_number.toLowerCase();

      const carrierMatch = memoCarrier.includes(dispCarrier) || dispCarrier.includes(memoCarrier);
      const refMatch = memoRef.includes(dispPro) || memoRef.includes(dispInv) || dispPro.includes(memoRef);
      const amtMatch = Math.abs(disp.overcharge_dollars - memoAmount) <= 1.0;

      return carrierMatch && refMatch && amtMatch;
    });

    if (matched) {
      return {
        credit_memo_id: candidate.id || `memo_${Date.now()}`,
        verification_status: 'verified',
        matched_dispute_id: matched.id,
        carrier: candidate.carrier,
        original_invoice_ref: candidate.original_invoice_ref,
        memo_amount_dollars: memoAmount,
        dispute_amount_dollars: matched.overcharge_dollars,
        discrepancy_dollars: Math.round(Math.abs(matched.overcharge_dollars - memoAmount) * 100) / 100,
        verified_at: new Date().toISOString(),
        notes: `Matched dispute ${matched.id} for PRO ${matched.pro_number}`,
      };
    }

    return {
      credit_memo_id: candidate.id || `memo_${Date.now()}`,
      verification_status: 'rejected',
      matched_dispute_id: null,
      carrier: candidate.carrier,
      original_invoice_ref: candidate.original_invoice_ref,
      memo_amount_dollars: memoAmount,
      dispute_amount_dollars: null,
      discrepancy_dollars: 0,
      verified_at: null,
      notes: 'No active dispute found matching carrier, reference PRO/Invoice number, and dollar amount tolerance.',
    };
  }
}
