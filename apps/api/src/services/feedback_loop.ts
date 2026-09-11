/**
 * RateGuard AI — Reason-Code Feedback Loop Service (Phase 4.2).
 * TypeScript service for precision analytics and automated ticket generation in Next.js / Supabase.
 */

import { SupabaseClient } from '@supabase/supabase-js';
import {
  FeedbackTicket,
  MonthlyRetroReport,
  PrecisionReportItem,
} from '../../../packages/schemas';

export const TAXONOMY_REMEDIATION_MAP: Record<string, { category: string; action: string }> = {
  'wrong-matrix-row': {
    category: 'contract_parser',
    action: 'Audit ContractParser RateMatrixJSON generation. Verify 3-digit vs 5-digit zip prefix lane priority, FAK class mapping, and weight break tier order.',
  },
  'misread-pdf-field': {
    category: 'invoice_parser',
    action: 'Calibrate InvoiceParser LLM prompt extraction and OCR bounding boxes for PRO#, linehaul total, and fuel surcharge currency fields.',
  },
  'contract-exception-misapplied': {
    category: 'contract_parser',
    action: 'Refine contractual rider and exception extraction in ContractParser Quality Ladder Rungs A & B.',
  },
  'not-an-error': {
    category: 'audit_engine',
    action: 'Review deterministic audit rules; verify carrier tariff baseline rules and customer-specific negotiated exclusions.',
  },
  'duplicate-false-positive': {
    category: 'audit_engine',
    action: 'Tighten check_duplicates time window; verify BOL matching requirements and carrier PRO re-use rules.',
  },
  'fsc-table-wrong-month': {
    category: 'fsc_engine',
    action: 'Audit FSCTable and EIA benchmark alignment. Verify Monday DOE benchmark price windowing and carrier monthly lag rules.',
  },
  'rate-effective-date-mismatch': {
    category: 'contract_parser',
    action: 'Verify rate_matrices effective date windows. Ensure annual GRI amendments do not audit out-of-scope historical invoices.',
  },
  'other': {
    category: 'audit_engine',
    action: 'Manual engineering investigation of ad-hoc rejection notes in review_events.',
  },
};

export function computePrecisionScore(approved: number, rejected: number): number {
  const total = approved + rejected;
  if (total <= 0) return 0.0;
  return Math.round((approved / total) * 1000) / 10;
}

export function evaluateTrajectoryStatus(precision: number, totalReviewed: number): string {
  if (totalReviewed <= 0) return 'NO_REVIEWS_RECORDED';
  if (precision >= 98.0) return 'ENTERPRISE_MET';
  if (precision >= 95.0) return 'SCALE_TARGET_MET';
  if (precision >= 90.0) return 'PILOT_GATE_PASSED';
  return 'BELOW_TARGET';
}

/**
 * Computes precision metrics overall, by carrier, and by check type.
 */
export async function getPrecisionAnalytics(
  supabase: SupabaseClient,
  month?: string,
  customerId?: string
): Promise<{
  overall: PrecisionReportItem;
  byCheckType: Record<string, PrecisionReportItem>;
  byCarrier: Record<string, PrecisionReportItem>;
  trajectoryStatus: string;
}> {
  let query = supabase.from('flags').select(`
    id,
    check_type,
    review_status,
    reject_reason_code,
    reviewed_at,
    created_at,
    invoices (
      carrier,
      customer_id,
      invoice_date
    )
  `);

  const { data: flags, error } = await query;
  if (error || !flags) {
    const emptyOverall: PrecisionReportItem = {
      category: 'overall',
      name: 'OVERALL',
      approved_count: 0,
      rejected_count: 0,
      pending_count: 0,
      research_count: 0,
      total_reviewed: 0,
      precision_pct: 0.0,
      meets_pilot_target: false,
      meets_scale_target: false,
      meets_enterprise_target: false,
    };
    return {
      overall: emptyOverall,
      byCheckType: {},
      byCarrier: {},
      trajectoryStatus: 'NO_REVIEWS_RECORDED',
    };
  }

  let overallApproved = 0;
  let overallRejected = 0;
  let overallPending = 0;
  let overallResearch = 0;

  const byCheck: Record<string, { approved: number; rejected: number; pending: number; research: number }> = {};
  const byCarrier: Record<string, { approved: number; rejected: number; pending: number; research: number }> = {};

  for (const f of flags) {
    const inv: any = f.invoices || {};
    if (customerId && inv.customer_id !== customerId) continue;
    if (month) {
      const dt = f.reviewed_at || f.created_at || inv.invoice_date || '';
      if (!dt.startsWith(month)) continue;
    }

    const st = f.review_status || 'pending';
    const ctype = f.check_type || 'UNKNOWN';
    const carrier = inv.carrier || 'Unknown';

    if (!byCheck[ctype]) byCheck[ctype] = { approved: 0, rejected: 0, pending: 0, research: 0 };
    if (!byCarrier[carrier]) byCarrier[carrier] = { approved: 0, rejected: 0, pending: 0, research: 0 };

    if (st === 'approved') {
      overallApproved++;
      byCheck[ctype].approved++;
      byCarrier[carrier].approved++;
    } else if (st === 'rejected') {
      overallRejected++;
      byCheck[ctype].rejected++;
      byCarrier[carrier].rejected++;
    } else if (st === 'research') {
      overallResearch++;
      byCheck[ctype].research++;
      byCarrier[carrier].research++;
    } else {
      overallPending++;
      byCheck[ctype].pending++;
      byCarrier[carrier].pending++;
    }
  }

  const totalReviewed = overallApproved + overallRejected;
  const overallPrec = computePrecisionScore(overallApproved, overallRejected);

  const overall: PrecisionReportItem = {
    category: 'overall',
    name: 'OVERALL',
    approved_count: overallApproved,
    rejected_count: overallRejected,
    pending_count: overallPending,
    research_count: overallResearch,
    total_reviewed: totalReviewed,
    precision_pct: overallPrec,
    meets_pilot_target: overallPrec >= 90.0 && totalReviewed > 0,
    meets_scale_target: overallPrec >= 95.0 && totalReviewed > 0,
    meets_enterprise_target: overallPrec >= 98.0 && totalReviewed > 0,
  };

  const byCheckType: Record<string, PrecisionReportItem> = {};
  for (const [ctype, counts] of Object.entries(byCheck)) {
    const rev = counts.approved + counts.rejected;
    const prec = computePrecisionScore(counts.approved, counts.rejected);
    byCheckType[ctype] = {
      category: 'check_type',
      name: ctype,
      approved_count: counts.approved,
      rejected_count: counts.rejected,
      pending_count: counts.pending,
      research_count: counts.research,
      total_reviewed: rev,
      precision_pct: prec,
      meets_pilot_target: prec >= 90.0 && rev > 0,
      meets_scale_target: prec >= 95.0 && rev > 0,
      meets_enterprise_target: prec >= 98.0 && rev > 0,
    };
  }

  const byCarrierResult: Record<string, PrecisionReportItem> = {};
  for (const [carrier, counts] of Object.entries(byCarrier)) {
    const rev = counts.approved + counts.rejected;
    const prec = computePrecisionScore(counts.approved, counts.rejected);
    byCarrierResult[carrier] = {
      category: 'carrier',
      name: carrier,
      approved_count: counts.approved,
      rejected_count: counts.rejected,
      pending_count: counts.pending,
      research_count: counts.research,
      total_reviewed: rev,
      precision_pct: prec,
      meets_pilot_target: prec >= 90.0 && rev > 0,
      meets_scale_target: prec >= 95.0 && rev > 0,
      meets_enterprise_target: prec >= 98.0 && rev > 0,
    };
  }

  return {
    overall,
    byCheckType,
    byCarrier: byCarrierResult,
    trajectoryStatus: evaluateTrajectoryStatus(overallPrec, totalReviewed),
  };
}

/**
 * Generates prioritized parser and prompt fix tickets based on rejection reason codes.
 */
export async function generateFixTickets(
  supabase: SupabaseClient,
  month?: string
): Promise<FeedbackTicket[]> {
  let query = supabase.from('flags').select(`
    id,
    check_type,
    review_status,
    reject_reason_code,
    reviewed_at,
    created_at,
    invoices (
      carrier,
      invoice_date
    )
  `).eq('review_status', 'rejected');

  const { data: rejectedFlags } = await query;
  if (!rejectedFlags || rejectedFlags.length === 0) return [];

  const rejectionGroups: Record<string, {
    count: number;
    carriers: Record<string, number>;
    checkTypes: Record<string, number>;
    flagIds: string[];
  }> = {};

  let totalRejections = 0;

  for (const f of rejectedFlags) {
    const inv: any = f.invoices || {};
    if (month) {
      const dt = f.reviewed_at || f.created_at || inv.invoice_date || '';
      if (!dt.startsWith(month)) continue;
    }

    const code = (f.reject_reason_code || 'other').trim().toLowerCase();
    const carrier = inv.carrier || 'Unknown';
    const ctype = f.check_type || 'UNKNOWN';

    totalRejections++;
    if (!rejectionGroups[code]) {
      rejectionGroups[code] = { count: 0, carriers: {}, checkTypes: {}, flagIds: [] };
    }

    rejectionGroups[code].count++;
    rejectionGroups[code].flagIds.push(f.id);
    rejectionGroups[code].carriers[carrier] = (rejectionGroups[code].carriers[carrier] || 0) + 1;
    rejectionGroups[code].checkTypes[ctype] = (rejectionGroups[code].checkTypes[ctype] || 0) + 1;
  }

  const tickets: FeedbackTicket[] = [];
  const sorted = Object.entries(rejectionGroups).sort((a, b) => b[1].count - a[1].count);

  for (const [code, data] of sorted) {
    const pct = totalRejections > 0 ? Math.round((data.count / totalRejections) * 1000) / 10 : 0.0;
    let priority: 'HIGH' | 'MEDIUM' | 'LOW' = 'LOW';
    if (data.count >= 5 || pct >= 30.0) priority = 'HIGH';
    else if (data.count >= 2 || pct >= 15.0) priority = 'MEDIUM';

    const remedy = TAXONOMY_REMEDIATION_MAP[code] || TAXONOMY_REMEDIATION_MAP['other'];
    const topCarrier = Object.entries(data.carriers).sort((a, b) => b[1] - a[1])[0]?.[0] || null;
    const topCheck = Object.entries(data.checkTypes).sort((a, b) => b[1] - a[1])[0]?.[0] || null;

    tickets.push({
      ticket_id: `TICKET-${remedy.category.toUpperCase()}-${code.replace(/-/g, '_').toUpperCase()}`,
      reason_code: code,
      rejection_count: data.count,
      percentage_of_rejections: pct,
      category: remedy.category,
      priority,
      affected_carrier: topCarrier,
      affected_check_type: topCheck,
      recommended_action: remedy.action,
      sample_flag_ids: data.flagIds.slice(0, 5),
      created_at: new Date().toISOString(),
    });
  }

  return tickets;
}
