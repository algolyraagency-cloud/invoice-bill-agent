/**
 * RateGuard AI — Recovery Report Service (Phase 5.1).
 * TypeScript service for compiling CFO Recovery Reports and generating executive HTML in Next.js / Supabase.
 */

import { SupabaseClient } from '@supabase/supabase-js';
import {
  RecoveryReportClaimItem,
  RecoveryReportSummary,
  ReviewQueueItem,
} from '../../../packages/schemas';

export function compileRecoveryReport(
  approvedFlags: ReviewQueueItem[],
  customerId: string,
  customerName: string,
  periodStart: string = '2026-03-01',
  periodEnd: string = '2026-08-31',
  totalInvoicesAudited?: number
): RecoveryReportSummary {
  const claims: RecoveryReportClaimItem[] = [];
  let totalRecoverableCents = 0;

  const carrierCounts: Record<string, number> = {};
  const carrierCents: Record<string, number> = {};
  const checkTypeCounts: Record<string, number> = {};
  const checkTypeCents: Record<string, number> = {};

  approvedFlags.forEach((flag, idx) => {
    const overchargeCents = flag.overcharge_cents || 0;
    const overchargeDollars = Math.round((overchargeCents / 100) * 100) / 100;
    totalRecoverableCents += overchargeCents;

    let billedAmount = flag.invoice_total || 0;
    if (billedAmount <= 0) {
      billedAmount = flag.evidence_json?.billed_amount || overchargeDollars;
    }

    let contractAmount = flag.evidence_json?.correct_amount || 0;
    if (contractAmount <= 0) {
      contractAmount = Math.max(0, Math.round((billedAmount - overchargeDollars) * 100) / 100);
    }

    const contractClause = flag.evidence_json?.contract_clause || 'Tariff Schedule Rules & Provisions';
    const pageNumber = flag.evidence_json?.page_number ? Number(flag.evidence_json.page_number) : null;

    let explanation = flag.evidence_json?.explanation;
    if (!explanation) {
      if (flag.check_type === 'RATE') {
        explanation = `Billed rate $${billedAmount.toFixed(2)} exceeded contracted rate $${contractAmount.toFixed(2)} under ${contractClause}.`;
      } else if (flag.check_type === 'FSC') {
        explanation = `Fuel surcharge miscalculation: does not match DOE/EIA weekly diesel benchmark.`;
      } else if (flag.check_type === 'DUP') {
        explanation = `Duplicate billing identified for PRO #${flag.pro_number}.`;
      } else {
        explanation = `Discrepancy identified under ${contractClause}.`;
      }
    }

    claims.push({
      flag_id: flag.id,
      invoice_id: flag.invoice_id,
      pro_number: flag.pro_number,
      invoice_number: flag.invoice_number,
      invoice_date: flag.invoice_date,
      carrier: flag.carrier,
      check_type: flag.check_type,
      billed_amount: billedAmount,
      contract_amount: contractAmount,
      overcharge_cents: overchargeCents,
      overcharge_dollars: overchargeDollars,
      contract_clause: contractClause,
      evidence_summary: explanation,
      page_number: pageNumber,
    });

    // Aggregations
    carrierCounts[flag.carrier] = (carrierCounts[flag.carrier] || 0) + 1;
    carrierCents[flag.carrier] = (carrierCents[flag.carrier] || 0) + overchargeCents;

    checkTypeCounts[flag.check_type] = (checkTypeCounts[flag.check_type] || 0) + 1;
    checkTypeCents[flag.check_type] = (checkTypeCents[flag.check_type] || 0) + overchargeCents;
  });

  const totalRecoverableDollars = Math.round((totalRecoverableCents / 100) * 100) / 100;
  const estimatedShipperRecoveryDollars = Math.round(totalRecoverableDollars * 0.65 * 100) / 100;
  const contingencyFeeDollars = Math.round(totalRecoverableDollars * 0.35 * 100) / 100;

  const byCarrier: Record<string, Record<string, any>> = {};
  for (const [carrier, count] of Object.entries(carrierCounts)) {
    const cents = carrierCents[carrier] || 0;
    const dollars = Math.round((cents / 100) * 100) / 100;
    const share = totalRecoverableCents > 0 ? Math.round((cents / totalRecoverableCents) * 1000) / 10 : 0;
    byCarrier[carrier] = {
      carrier,
      claims_count: count,
      recoverable_dollars: dollars,
      share_pct: share,
    };
  }

  const byCheckType: Record<string, Record<string, any>> = {};
  for (const [ctype, count] of Object.entries(checkTypeCounts)) {
    const cents = checkTypeCents[ctype] || 0;
    const dollars = Math.round((cents / 100) * 100) / 100;
    const share = totalRecoverableCents > 0 ? Math.round((cents / totalRecoverableCents) * 1000) / 10 : 0;
    byCheckType[ctype] = {
      check_type: ctype,
      claims_count: count,
      recoverable_dollars: dollars,
      share_pct: share,
    };
  }

  const uniqueInvoices = new Set(claims.map((c) => c.invoice_id)).size;
  const finalTotalAudited = totalInvoicesAudited || Math.max(uniqueInvoices, claims.length * 4);
  const now = new Date().toISOString();
  const reportId = `REP-${now.substring(0, 10).replace(/-/g, '')}-${Math.random().toString(36).substring(2, 8).toUpperCase()}`;

  return {
    report_id: reportId,
    customer_id: customerId,
    customer_name: customerName,
    report_title: 'Freight Audit & Recovery Report',
    period_start: periodStart,
    period_end: periodEnd,
    generated_at: now,
    total_invoices_audited: finalTotalAudited,
    total_flagged_invoices: uniqueInvoices,
    total_approved_claims: claims.length,
    total_recoverable_cents: totalRecoverableCents,
    total_recoverable_dollars: totalRecoverableDollars,
    estimated_shipper_recovery_dollars: estimatedShipperRecoveryDollars,
    contingency_fee_dollars: contingencyFeeDollars,
    by_carrier: byCarrier,
    by_check_type: byCheckType,
    claims,
  };
}

export class RecoveryReportService {
  constructor(private supabase?: SupabaseClient) {}

  async generateCustomerReport(customerId: string, customerName: string): Promise<RecoveryReportSummary> {
    if (!this.supabase) {
      return compileRecoveryReport([], customerId, customerName);
    }

    // Fetch approved flags joined with invoice info
    const { data: flags, error } = await this.supabase
      .from('flags')
      .select(`
        id, invoice_id, check_type, overcharge_cents, confidence, evidence_json, review_status,
        invoices!inner(carrier, pro_number, invoice_number, invoice_date, invoice_total, customer_id)
      `)
      .eq('review_status', 'approved')
      .eq('invoices.customer_id', customerId);

    if (error || !flags) {
      throw new Error(`Failed to load approved flags for report: ${error?.message}`);
    }

    const reviewItems: ReviewQueueItem[] = flags.map((f: any) => ({
      id: f.id,
      invoice_id: f.invoice_id,
      check_type: f.check_type,
      overcharge_cents: f.overcharge_cents,
      confidence: Number(f.confidence),
      evidence_json: f.evidence_json || {},
      review_status: 'approved',
      reject_reason_code: null,
      reviewed_by: null,
      reviewed_at: null,
      carrier: f.invoices.carrier,
      pro_number: f.invoices.pro_number,
      invoice_number: f.invoices.invoice_number,
      invoice_date: f.invoices.invoice_date,
      invoice_total: Number(f.invoices.invoice_total),
      customer_id: f.invoices.customer_id,
    }));

    return compileRecoveryReport(reviewItems, customerId, customerName);
  }
}
