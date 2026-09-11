/**
 * RateGuard AI — Dispute Letter Service (Phase 5.2).
 * TypeScript service for drafting carrier dispute notices, constructing mailto links,
 * and managing dispute status state machine in Next.js / Supabase.
 */

import { SupabaseClient } from '@supabase/supabase-js';
import {
  DisputeBatchPacket,
  DisputeLetterItem,
  DisputeStatus,
  ReviewQueueItem,
} from '../../../packages/schemas';

export const DEFAULT_CARRIER_CONTACTS: Record<string, { dispute_email: string; billing_phone?: string }> = {
  'ABF Freight': {
    dispute_email: 'freightbilling@abf.com',
    billing_phone: '800-610-5544',
  },
  'XPO Logistics': {
    dispute_email: 'ltlclaims@xpo.com',
    billing_phone: '800-755-2728',
  },
  'Roadrunner': {
    dispute_email: 'billingdisputes@rrts.com',
    billing_phone: '800-435-0777',
  },
};

export const VALID_DISPUTE_TRANSITIONS: Record<string, string[]> = {
  drafted: ['sent'],
  sent: ['responded', 'credit_issued', 'denied'],
  responded: ['credit_issued', 'denied', 'sent'],
  credit_issued: [],
  denied: ['sent'],
};

export function resolveCarrierContact(carrier: string, overrideEmail?: string) {
  if (overrideEmail) {
    return { dispute_email: overrideEmail };
  }
  for (const [cname, info] of Object.entries(DEFAULT_CARRIER_CONTACTS)) {
    if (carrier.toLowerCase().includes(cname.toLowerCase()) || cname.toLowerCase().includes(carrier.toLowerCase())) {
      return info;
    }
  }
  const clean = carrier.toLowerCase().replace(/\s+/g, '').replace(/-/g, '');
  return {
    dispute_email: `billing-disputes@${clean}.com`,
    billing_phone: '800-555-0100',
  };
}

export function transitionDisputeStatus(current: string, next: string): DisputeStatus {
  const allowed = VALID_DISPUTE_TRANSITIONS[current];
  if (!allowed) {
    throw new Error(`Unknown dispute status: '${current}'`);
  }
  if (!allowed.includes(next)) {
    throw new Error(`Invalid status transition: '${current}' -> '${next}'. Allowed: [${allowed.join(', ')}]`);
  }
  return next as DisputeStatus;
}

export function generateDisputeLetter(
  flag: ReviewQueueItem,
  customerName: string,
  customerSlug: string,
  carrierEmailOverride?: string
): DisputeLetterItem {
  const overchargeCents = flag.overcharge_cents || 0;
  const overchargeDollars = Math.round((overchargeCents / 100) * 100) / 100;

  let billedAmount = flag.invoice_total || 0;
  if (billedAmount <= 0) {
    billedAmount = flag.evidence_json?.billed_amount || overchargeDollars;
  }

  let contractAmount = flag.evidence_json?.correct_amount || 0;
  if (contractAmount <= 0) {
    contractAmount = Math.max(0, Math.round((billedAmount - overchargeDollars) * 100) / 100);
  }

  const contractClause = flag.evidence_json?.contract_clause || 'Tariff Schedule Rules & Provisions';
  const pageStr = flag.evidence_json?.page_number ? ` (Page ${flag.evidence_json.page_number})` : '';

  let explanation = flag.evidence_json?.explanation;
  if (!explanation) {
    if (flag.check_type === 'RATE') {
      explanation = `The billed freight rate of $${billedAmount.toFixed(2)} exceeded the contracted lane rate of $${contractAmount.toFixed(2)} per ${contractClause}${pageStr}. Overcharge discrepancy is $${overchargeDollars.toFixed(2)}.`;
    } else if (flag.check_type === 'FSC') {
      explanation = `Fuel surcharge calculation discrepancy: Surcharge rate does not match the published DOE/EIA diesel index benchmark for the shipment date under ${contractClause}${pageStr}. Disputed difference is $${overchargeDollars.toFixed(2)}.`;
    } else if (flag.check_type === 'DUP') {
      explanation = `Duplicate billing identified: Invoice #${flag.invoice_number} duplicates prior billing for PRO #${flag.pro_number}. Full overbilled amount is $${overchargeDollars.toFixed(2)}.`;
    } else {
      explanation = `Billing discrepancy identified under ${contractClause}${pageStr}. Disputed amount: $${overchargeDollars.toFixed(2)}.`;
    }
  }

  const contact = resolveCarrierContact(flag.carrier, carrierEmailOverride);
  const ccEmail = `disputes+${customerSlug}@in.rateguard.app`;
  const emailSubject = `Billing Dispute: Invoice #${flag.invoice_number} / PRO #${flag.pro_number} — ${customerName}`;
  const now = new Date().toISOString();
  const disputeId = `DISP-${now.substring(0, 7).replace(/-/g, '')}-${Math.random().toString(36).substring(2, 8).toUpperCase()}`;

  const emailBodyText = `To: ${flag.carrier} Billing & Claims Department
Dispute Email: ${contact.dispute_email}
From: Accounts Payable, ${customerName}
Subject: ${emailSubject}

Dear Billing Department,

We have audited freight billing on invoice #${flag.invoice_number} (PRO #${flag.pro_number}) dated ${flag.invoice_date} and identified an overcharge discrepancy totaling $${overchargeDollars.toFixed(2)}.

DISPUTE DETAILS:
- Carrier: ${flag.carrier}
- Invoice Number: ${flag.invoice_number}
- PRO Tracking Number: ${flag.pro_number}
- Billing Date: ${flag.invoice_date}
- Billed Total: $${billedAmount.toFixed(2)}
- Contract Rate: $${contractAmount.toFixed(2)}
- Disputed Overcharge: $${overchargeDollars.toFixed(2)}
- Audit Category: ${flag.check_type}
- Governing Authority: ${contractClause}${pageStr}

AUDIT FINDINGS & EVIDENCE:
${explanation}

REQUESTED ACTION:
Pursuant to our contracted pricing agreement and standard industry billing practices, please issue an itemized Credit Memo in the amount of $${overchargeDollars.toFixed(2)} referencing Invoice #${flag.invoice_number} and PRO #${flag.pro_number} within 30 days.

Please reply to this email or send confirmed credit memo documentation to:
${ccEmail}

Thank you,
Freight Accounts Payable
${customerName}
`;

  const emailBodyHtml = `
    <div style="font-family: Arial, sans-serif; font-size: 14px; color: #111; line-height: 1.5;">
      <p><strong>To:</strong> ${flag.carrier} Billing & Claims Department (${contact.dispute_email})<br>
      <strong>From:</strong> Accounts Payable, ${customerName}<br>
      <strong>Subject:</strong> ${emailSubject}</p>

      <p>Dear Billing Department,</p>
      <p>We have audited invoice <strong>#${flag.invoice_number}</strong> (PRO <strong>#${flag.pro_number}</strong>) and identified an overcharge of <strong>$${overchargeDollars.toFixed(2)}</strong>.</p>
      
      <p><strong>Contract Clause:</strong> ${contractClause}${pageStr}<br>
      <strong>Audit Finding:</strong> ${explanation}</p>

      <p>Please issue a Credit Memo for <strong>$${overchargeDollars.toFixed(2)}</strong> within 30 days to <a href="mailto:${ccEmail}">${ccEmail}</a>.</p>

      <p>Sincerely,<br>Freight Accounts Payable<br><strong>${customerName}</strong></p>
    </div>
  `;

  const mailtoParams = new URLSearchParams({
    cc: ccEmail,
    subject: emailSubject,
    body: emailBodyText,
  });
  const mailtoLink = `mailto:${contact.dispute_email}?${mailtoParams.toString()}`;

  return {
    dispute_id: disputeId,
    flag_id: flag.id,
    invoice_id: flag.invoice_id,
    customer_id: flag.customer_id || '',
    customer_name: customerName,
    customer_slug: customerSlug,
    carrier: flag.carrier,
    carrier_dispute_email: contact.dispute_email,
    carrier_phone: contact.billing_phone,
    invoice_number: flag.invoice_number,
    pro_number: flag.pro_number,
    invoice_date: flag.invoice_date,
    billed_amount: billedAmount,
    contract_amount: contractAmount,
    overcharge_dollars: overchargeDollars,
    check_type: flag.check_type,
    contract_clause: `${contractClause}${pageStr}`,
    dispute_reason_text: explanation,
    evidence_details: flag.evidence_json || {},
    status: 'drafted',
    letter_pdf_path: null,
    mailto_link: mailtoLink,
    email_subject: emailSubject,
    email_body_text: emailBodyText,
    email_body_html: emailBodyHtml,
    created_at: now,
    updated_at: now,
  };
}

export function generateCarrierDisputeBatch(
  approvedFlags: ReviewQueueItem[],
  carrier: string,
  customerName: string,
  customerSlug: string
): DisputeBatchPacket {
  const disputes: DisputeLetterItem[] = [];
  let totalDollars = 0;

  for (const flag of approvedFlags) {
    if (flag.carrier.toLowerCase().includes(carrier.toLowerCase()) || carrier.toLowerCase().includes(flag.carrier.toLowerCase())) {
      const letter = generateDisputeLetter(flag, customerName, customerSlug);
      disputes.push(letter);
      totalDollars += letter.overcharge_dollars;
    }
  }

  totalDollars = Math.round(totalDollars * 100) / 100;
  const contact = resolveCarrierContact(carrier);
  const ccEmail = `disputes+${customerSlug}@in.rateguard.app`;
  const batchSubject = `Freight Billing Disputes (${disputes.length} Claims) — Total $${totalDollars.toFixed(2)} — ${customerName}`;

  let claimBullets = '';
  disputes.forEach((d, idx) => {
    claimBullets += `Claim #${idx + 1} [PRO #${d.pro_number} / Inv #${d.invoice_number} / Date: ${d.invoice_date}]:\n  - Billed: $${d.billed_amount.toFixed(2)} | Contract: $${d.contract_amount.toFixed(2)} | Overcharge: $${d.overcharge_dollars.toFixed(2)}\n  - Finding: ${d.dispute_reason_text}\n\n`;
  });

  const batchBody = `To: ${carrier} Billing & Dispute Department
From: Accounts Payable, ${customerName}
Subject: ${batchSubject}

Dear Billing Department,

We have audited freight billing for ${customerName} and identified ${disputes.length} overcharges totaling $${totalDollars.toFixed(2)}.

SUMMARY OF CLAIMS:
${claimBullets}
Please issue itemized credit memos totaling $${totalDollars.toFixed(2)} within 30 days to:
${ccEmail}

Thank you,
Freight Accounts Payable
${customerName}
`;

  const params = new URLSearchParams({
    cc: ccEmail,
    subject: batchSubject,
    body: batchBody,
  });

  return {
    carrier,
    carrier_dispute_email: contact.dispute_email,
    customer_name: customerName,
    customer_slug: customerSlug,
    disputes_count: disputes.length,
    total_disputed_dollars: totalDollars,
    disputes,
    combined_mailto_link: `mailto:${contact.dispute_email}?${params.toString()}`,
    created_at: new Date().toISOString(),
  };
}

export class DisputeService {
  constructor(private supabase?: SupabaseClient) {}

  async saveDispute(dispute: DisputeLetterItem) {
    if (!this.supabase) return dispute;

    const { data, error } = await this.supabase.from('disputes').insert({
      id: dispute.dispute_id,
      flag_id: dispute.flag_id,
      status: dispute.status,
    }).select().single();

    if (error) {
      throw new Error(`Failed to save dispute record: ${error.message}`);
    }
    return data;
  }

  async updateDisputeStatus(disputeId: string, currentStatus: string, nextStatus: string) {
    const validatedNext = transitionDisputeStatus(currentStatus, nextStatus);
    if (!this.supabase) return { dispute_id: disputeId, status: validatedNext };

    const { data, error } = await this.supabase
      .from('disputes')
      .update({ status: validatedNext, updated_at: new Date().toISOString() })
      .eq('id', disputeId)
      .select()
      .single();

    if (error) {
      throw new Error(`Failed to update dispute status: ${error.message}`);
    }
    return data;
  }
}
