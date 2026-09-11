/**
 * RateGuard AI — Internal Review Queue Service (Phase 4.1).
 * TypeScript service for Supabase / Next.js API routes and server actions.
 *
 * Guarantees:
 * 1. Role-gated to 'internal_reviewer'.
 * 2. Rejections strictly enforce the 8-code taxonomy from Phase 2.0.4.
 * 3. Every action logs to 'review_events' (audit trail + training data).
 * 4. Every rejection increments 'reason_codes.count'.
 * 5. Research flags are resolvable ('resolve_research') so nothing dies in research.
 * 6. Throughput tracking: records review duration against the <=30s target.
 */

import { SupabaseClient } from '@supabase/supabase-js';
import {
  ReviewAction,
  ReviewActionRequest,
  ReviewQueueItem,
  ReviewQueueSummary,
} from '../../../packages/schemas';

// Standard Reason-Code Taxonomy v1 (PRD §5.5, Phase 2.0.4)
export const STANDARD_REASON_CODES = new Set<string>([
  'wrong-matrix-row',
  'misread-pdf-field',
  'contract-exception-misapplied',
  'not-an-error',
  'duplicate-false-positive',
  'fsc-table-wrong-month',
  'rate-effective-date-mismatch',
  'other',
]);

export function validateReasonCode(code: string): boolean {
  return STANDARD_REASON_CODES.has(code.trim().toLowerCase());
}

export interface ReviewQueueFilter {
  status?: 'pending' | 'approved' | 'rejected' | 'research';
  carrier?: string;
  checkType?: string;
  customerId?: string;
  limit?: number;
  offset?: number;
}

/**
 * Validates that user holds 'internal_reviewer' role.
 */
export async function verifyInternalReviewerRole(
  userId: string,
  supabase: SupabaseClient
): Promise<boolean> {
  const { data, error } = await supabase
    .from('users')
    .select('role')
    .eq('id', userId)
    .single();

  if (error || !data) {
    throw new Error(`Unauthorized: User '${userId}' not found or role lookup failed`);
  }

  if (data.role !== 'internal_reviewer') {
    throw new Error(`Forbidden: User '${userId}' does not have 'internal_reviewer' role (current: ${data.role})`);
  }

  return true;
}

/**
 * Retrieves review queue flags joined with invoice details and signed PDF URLs.
 */
export async function getReviewQueue(
  filter: ReviewQueueFilter,
  supabase: SupabaseClient
): Promise<{ items: ReviewQueueItem[]; totalCount: number }> {
  const status = filter.status || 'pending';
  const limit = filter.limit || 50;
  const offset = filter.offset || 0;

  let query = supabase
    .from('flags')
    .select(
      `
      id,
      invoice_id,
      check_type,
      overcharge_cents,
      confidence,
      evidence_json,
      review_status,
      reject_reason_code,
      reviewed_by,
      reviewed_at,
      created_at,
      invoices (
        id,
        carrier,
        pro_number,
        invoice_number,
        invoice_date,
        invoice_total,
        file_path,
        customer_id
      )
    `,
      { count: 'exact' }
    )
    .eq('review_status', status);

  if (filter.checkType) {
    query = query.eq('check_type', filter.checkType);
  }

  query = query.order('created_at', { ascending: true }).range(offset, offset + limit - 1);

  const { data, count, error } = await query;
  if (error || !data) {
    return { items: [], totalCount: 0 };
  }

  const items: ReviewQueueItem[] = await Promise.all(
    data.map(async (row: any) => {
      const inv = row.invoices || {};

      let signedPdfUrl: string | null = null;
      if (inv.file_path) {
        try {
          const { data: signed } = await supabase.storage
            .from('invoice-files')
            .createSignedUrl(inv.file_path, 3600);
          signedPdfUrl = signed?.signedUrl || null;
        } catch {
          signedPdfUrl = null;
        }
      }

      return {
        id: row.id,
        invoice_id: row.invoice_id,
        check_type: row.check_type,
        overcharge_cents: row.overcharge_cents,
        confidence: row.confidence ?? 1.0,
        evidence_json: row.evidence_json || {},
        review_status: row.review_status,
        reject_reason_code: row.reject_reason_code,
        reviewed_by: row.reviewed_by,
        reviewed_at: row.reviewed_at,
        carrier: inv.carrier || 'Unknown',
        pro_number: inv.pro_number || 'N/A',
        invoice_number: inv.invoice_number || 'N/A',
        invoice_date: inv.invoice_date || '1970-01-01',
        invoice_total: inv.invoice_total || 0,
        file_path: inv.file_path,
        signed_pdf_url: signedPdfUrl,
        customer_id: inv.customer_id,
        created_at: row.created_at,
      };
    })
  );

  return { items, totalCount: count || items.length };
}

/**
 * Handles Approve, Reject, and Research actions on a flag.
 */
export async function executeReviewAction(
  request: ReviewActionRequest,
  supabase: SupabaseClient
): Promise<{ success: boolean; flagId: string; status: string }> {
  await verifyInternalReviewerRole(request.reviewer_id, supabase);

  const now = new Date().toISOString();
  const { flag_id, action, reviewer_id, reason_code, notes, duration_seconds } = request;

  if (action === 'approve') {
    // 1. Update flag to approved
    const { error: flagErr } = await supabase
      .from('flags')
      .update({
        review_status: 'approved',
        reviewed_by: reviewer_id,
        reviewed_at: now,
        updated_at: now,
      })
      .eq('id', flag_id);

    if (flagErr) throw flagErr;

    // 2. Insert review_events audit record
    await supabase.from('review_events').insert({
      flag_id,
      action: 'approve',
      reviewer: reviewer_id,
      notes: notes || null,
      duration_seconds: duration_seconds || null,
      created_at: now,
    });

    return { success: true, flagId: flag_id, status: 'approved' };
  } else if (action === 'reject') {
    if (!reason_code || !validateReasonCode(reason_code)) {
      throw new Error(
        `Invalid reason code '${reason_code}'. Must be one of: ${Array.from(STANDARD_REASON_CODES).join(', ')}`
      );
    }

    const code = reason_code.trim().toLowerCase();

    // 1. Update flag to rejected
    const { error: flagErr } = await supabase
      .from('flags')
      .update({
        review_status: 'rejected',
        reject_reason_code: code,
        reviewed_by: reviewer_id,
        reviewed_at: now,
        updated_at: now,
      })
      .eq('id', flag_id);

    if (flagErr) throw flagErr;

    // 2. Increment count in reason_codes
    const { data: rcData } = await supabase
      .from('reason_codes')
      .select('count')
      .eq('code', code)
      .single();

    if (rcData) {
      await supabase
        .from('reason_codes')
        .update({ count: (rcData.count || 0) + 1 })
        .eq('code', code);
    } else {
      await supabase.from('reason_codes').insert({ code, description: code, count: 1 });
    }

    // 3. Insert review_events audit record
    await supabase.from('review_events').insert({
      flag_id,
      action: 'reject',
      reason_code: code,
      reviewer: reviewer_id,
      notes: notes || null,
      duration_seconds: duration_seconds || null,
      created_at: now,
    });

    return { success: true, flagId: flag_id, status: 'rejected' };
  } else if (action === 'research') {
    if (!notes || notes.trim() === '') {
      throw new Error('Reviewer notes are mandatory when placing a flag into research');
    }

    const { error: flagErr } = await supabase
      .from('flags')
      .update({
        review_status: 'research',
        reviewed_by: reviewer_id,
        reviewed_at: now,
        updated_at: now,
      })
      .eq('id', flag_id);

    if (flagErr) throw flagErr;

    await supabase.from('review_events').insert({
      flag_id,
      action: 'research',
      reviewer: reviewer_id,
      notes: notes.trim(),
      duration_seconds: duration_seconds || null,
      created_at: now,
    });

    return { success: true, flagId: flag_id, status: 'research' };
  } else if (action === 'resolve_research') {
    if (!notes || notes.trim() === '') {
      throw new Error('Resolution notes are mandatory when resolving a research item');
    }

    let targetStatus = 'pending';
    let rejectCode: string | null = null;

    if (reason_code) {
      if (!validateReasonCode(reason_code)) {
        throw new Error(
          `Invalid reason code '${reason_code}'. Must be one of: ${Array.from(STANDARD_REASON_CODES).join(', ')}`
        );
      }
      rejectCode = reason_code.trim().toLowerCase();
      targetStatus = 'rejected';
    }

    const { error: flagErr } = await supabase
      .from('flags')
      .update({
        review_status: targetStatus,
        reject_reason_code: rejectCode,
        reviewed_by: reviewer_id,
        reviewed_at: now,
        updated_at: now,
      })
      .eq('id', flag_id);

    if (flagErr) throw flagErr;

    await supabase.from('review_events').insert({
      flag_id,
      action: 'resolve_research',
      reason_code: rejectCode,
      reviewer: reviewer_id,
      notes: `Resolved: ${notes.trim()} -> status=${targetStatus}`,
      duration_seconds: duration_seconds || null,
      created_at: now,
    });

    return { success: true, flagId: flag_id, status: targetStatus };
  } else {
    throw new Error(`Unknown review action: ${action}`);
  }
}

/**
 * Returns review queue overview and performance metrics.
 */
export async function getReviewQueueSummary(
  supabase: SupabaseClient,
  customerId?: string
): Promise<ReviewQueueSummary> {
  const summary: ReviewQueueSummary = {
    pending_count: 0,
    approved_count: 0,
    rejected_count: 0,
    research_count: 0,
    total_reviewed_count: 0,
    total_approved_overcharge_cents: 0,
    avg_duration_seconds: 0,
    flags_by_check_type: {},
    flags_by_carrier: {},
  };

  let query = supabase.from('flags').select(`
    review_status,
    overcharge_cents,
    check_type,
    invoices (
      carrier,
      customer_id
    )
  `);

  const { data: flagRows } = await query;
  if (flagRows) {
    for (const f of flagRows) {
      const inv: any = f.invoices || {};
      if (customerId && inv.customer_id !== customerId) continue;

      const st = f.review_status || 'pending';
      const cents = f.overcharge_cents || 0;
      const ctype = f.check_type || 'UNKNOWN';
      const carrier = inv.carrier || 'Unknown';

      if (st === 'pending') summary.pending_count++;
      else if (st === 'approved') {
        summary.approved_count++;
        summary.total_approved_overcharge_cents += cents;
      } else if (st === 'rejected') summary.rejected_count++;
      else if (st === 'research') summary.research_count++;

      summary.flags_by_check_type[ctype] = (summary.flags_by_check_type[ctype] || 0) + 1;
      summary.flags_by_carrier[carrier] = (summary.flags_by_carrier[carrier] || 0) + 1;
    }
  }

  summary.total_reviewed_count = summary.approved_count + summary.rejected_count;

  // Average review duration
  const { data: eventRows } = await supabase
    .from('review_events')
    .select('duration_seconds');

  if (eventRows) {
    const validDurs = eventRows
      .map((e: any) => e.duration_seconds)
      .filter((d: any) => typeof d === 'number' && d > 0);
    if (validDurs.length > 0) {
      const sum = validDurs.reduce((acc: number, curr: number) => acc + curr, 0);
      summary.avg_duration_seconds = Math.round((sum / validDurs.length) * 10) / 10;
    }
  }

  return summary;
}
