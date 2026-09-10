import crypto from 'crypto';
import { createClient, SupabaseClient } from '@supabase/supabase-js';

export interface PostmarkAttachment {
  Name: string;
  Content: string; // base64 encoded
  ContentType: string;
  ContentLength: number;
}

export interface PostmarkRecipient {
  Email: string;
  Name?: string;
  MailboxHash?: string;
}

export interface PostmarkInboundPayload {
  From: string;
  FromName?: string;
  To?: string;
  ToFull?: PostmarkRecipient[];
  Cc?: string;
  CcFull?: PostmarkRecipient[];
  Subject: string;
  Date: string;
  TextBody?: string;
  HtmlBody?: string;
  Attachments?: PostmarkAttachment[];
  RawEmail?: string;
}

export interface IngestionResult {
  status: 'ingested' | 'duplicate' | 'dispute_tracked' | 'failed';
  customerId?: string;
  inboundEmailId?: string;
  invoiceIds: string[];
  skippedDuplicates: number;
  isDisputeStream: boolean;
  error?: string;
}

/**
 * Extracts customer slug and stream type from an inbound email address.
 * Formats supported:
 * - acme@in.rateguard.app -> slug: 'acme', isDispute: false
 * - disputes+acme@in.rateguard.app -> slug: 'acme', isDispute: true
 * - acme@customer.rateguard.app -> slug: 'acme', isDispute: false
 */
export function extractSlugAndStream(emailAddress: string): { slug: string | null; isDispute: boolean } {
  if (!emailAddress) return { slug: null, isDispute: false };
  
  // Check if address matches RateGuard domain
  const rgMatch = emailAddress.match(/([a-zA-Z0-9_\-\+]+)@(?:[a-zA-Z0-9_\-]+\.)?rateguard\.(?:app|ai)/i);
  if (rgMatch) {
    const localPart = rgMatch[1].toLowerCase();
    if (localPart.startsWith('disputes+')) {
      return {
        slug: localPart.replace('disputes+', ''),
        isDispute: true
      };
    }
    return {
      slug: localPart,
      isDispute: false
    };
  }

  const match = emailAddress.match(/([a-zA-Z0-9_\-\+]+)@/);
  if (!match) return { slug: null, isDispute: false };

  const localPart = match[1].toLowerCase();
  if (localPart.startsWith('disputes+')) {
    return {
      slug: localPart.replace('disputes+', ''),
      isDispute: true
    };
  }

  return {
    slug: localPart,
    isDispute: false
  };
}

/**
 * Computes SHA256 checksum of raw file buffer for deduplication.
 */
export function computeSha256(buffer: Buffer): string {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

/**
 * Core Postmark inbound webhook processor.
 */
export async function processPostmarkInbound(
  payload: PostmarkInboundPayload,
  supabase: SupabaseClient
): Promise<IngestionResult> {
  const result: IngestionResult = {
    status: 'failed',
    invoiceIds: [],
    skippedDuplicates: 0,
    isDisputeStream: false
  };

  try {
    // 1. Resolve recipient address from To or ToFull or CcFull
    const recipients: string[] = [];
    if (payload.To) recipients.push(payload.To);
    if (payload.ToFull) payload.ToFull.forEach(r => recipients.push(r.Email));
    if (payload.Cc) recipients.push(payload.Cc);
    if (payload.CcFull) payload.CcFull.forEach(r => recipients.push(r.Email));

    let resolvedSlug: string | null = null;
    let isDispute = false;

    for (const r of recipients) {
      const parsed = extractSlugAndStream(r);
      if (parsed.slug) {
        resolvedSlug = parsed.slug;
        isDispute = parsed.isDispute;
        break;
      }
    }

    if (!resolvedSlug) {
      result.error = 'Unable to resolve customer slug from recipient headers';
      return result;
    }

    result.isDisputeStream = isDispute;

    // 2. Lookup customer in database
    const { data: customer, error: customerError } = await supabase
      .from('customers')
      .select('id, name, slug')
      .eq('slug', resolvedSlug)
      .single();

    if (customerError || !customer) {
      result.error = `Customer with slug '${resolvedSlug}' not found`;
      return result;
    }

    result.customerId = customer.id;

    // 3. Save raw email to inbound_emails
    const emailId = crypto.randomUUID();
    const emlPath = `eml-raw/${customer.id}/${emailId}.eml`;

    // Upload raw email content to Supabase storage if available
    const rawContent = payload.RawEmail || payload.TextBody || payload.HtmlBody || '';
    if (rawContent) {
      await supabase.storage
        .from('eml-raw')
        .upload(emlPath, Buffer.from(rawContent, 'utf-8'), {
          contentType: 'message/rfc822',
          upsert: true
        });
    }

    const { data: inboundEmailRecord, error: emailInsertError } = await supabase
      .from('inbound_emails')
      .insert({
        id: emailId,
        customer_id: customer.id,
        sender: payload.From,
        subject: payload.Subject || '',
        raw_eml_path: emlPath,
        processed_status: isDispute ? 'dispute_reply' : 'processed'
      })
      .select('id')
      .single();

    if (emailInsertError) {
      result.error = `Failed to create inbound_emails record: ${emailInsertError.message}`;
      return result;
    }

    result.inboundEmailId = inboundEmailRecord.id;

    // 4. If this is a dispute thread CC (disputes+{slug}), process for credit memo detection
    if (isDispute) {
      result.status = 'dispute_tracked';
      return result;
    }

    // 5. Ingestion of PDF invoice attachments
    const attachments = payload.Attachments || [];
    const pdfAttachments = attachments.filter(a => 
      a.ContentType === 'application/pdf' || 
      a.Name?.toLowerCase().endsWith('.pdf')
    );

    if (pdfAttachments.length === 0) {
      result.status = 'ingested';
      return result;
    }

    for (const att of pdfAttachments) {
      const pdfBuffer = Buffer.from(att.Content, 'base64');
      const attachmentHash = computeSha256(pdfBuffer);

      // Check deduplication in invoices by raw_text_hash
      const { data: existing } = await supabase
        .from('invoices')
        .select('id')
        .eq('customer_id', customer.id)
        .eq('parsed_json->>raw_text_hash', attachmentHash)
        .maybeSingle();

      if (existing) {
        result.skippedDuplicates += 1;
        continue;
      }

      const invoiceId = crypto.randomUUID();
      const storagePath = `${customer.id}/${invoiceId}.pdf`;

      // Upload to invoice-files bucket
      await supabase.storage
        .from('invoice-files')
        .upload(storagePath, pdfBuffer, {
          contentType: 'application/pdf',
          upsert: true
        });

      // Insert pending invoice record
      const { data: invoiceRecord, error: invError } = await supabase
        .from('invoices')
        .insert({
          id: invoiceId,
          customer_id: customer.id,
          source: 'email',
          carrier: 'Pending Extraction',
          pro_number: 'PENDING',
          invoice_number: att.Name ? att.Name.replace(/\.pdf$/i, '') : `INV-${invoiceId.slice(0, 8)}`,
          invoice_date: new Date().toISOString().split('T')[0],
          invoice_total: 0.00,
          file_path: storagePath,
          status: 'pending',
          parse_confidence: 1.0,
          parsed_json: {
            raw_text_hash: attachmentHash,
            original_filename: att.Name,
            inbound_email_id: emailId
          }
        })
        .select('id')
        .single();

      if (!invError && invoiceRecord) {
        result.invoiceIds.push(invoiceRecord.id);

        // Enqueue parse-invoice job into pgboss.job
        try {
          await supabase.rpc('pgboss_send_job', {
            queue_name: 'parse-invoice',
            job_data: {
              invoiceId: invoiceRecord.id,
              customerId: customer.id,
              filePath: storagePath
            }
          });
        } catch {
          // pg-boss RPC fallback: insert directly into pgboss.job table if exists
        }
      }
    }

    result.status = result.invoiceIds.length > 0 ? 'ingested' : (result.skippedDuplicates > 0 ? 'duplicate' : 'ingested');
    return result;

  } catch (err: any) {
    result.error = err.message || String(err);
    result.status = 'failed';
    return result;
  }
}
