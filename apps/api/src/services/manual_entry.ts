import crypto from 'crypto';
import { SupabaseClient } from '@supabase/supabase-js';

export interface ManualLineItemInput {
  description: string;
  charge_code?: string;
  amount: number;
}

export interface ManualAccessorialInput {
  type: string;
  amount: number;
  authorized?: boolean;
}

export interface ManualInvoiceInput {
  customerId: string;
  carrier: string;
  pro_number: string;
  invoice_number: string;
  invoice_date: string; // YYYY-MM-DD
  origin_zip: string;
  dest_zip: string;
  billed_weight: number;
  billed_class?: number;
  line_items: ManualLineItemInput[];
  accessorials?: ManualAccessorialInput[];
  fsc_amount?: number;
  fsc_pct?: number;
  invoice_total: number;
  notes?: string;
}

export interface ManualEntryResult {
  success: boolean;
  invoiceId?: string;
  error?: string;
  isDuplicate?: boolean;
}

/**
 * Validates and stores a manually entered freight invoice.
 * Enters the same pipeline state ('pending') as an emailed/uploaded invoice.
 */
export async function createManualInvoice(
  input: ManualInvoiceInput,
  supabase: SupabaseClient
): Promise<ManualEntryResult> {
  // 1. Basic validation
  if (!input.customerId || !input.carrier || !input.pro_number || !input.invoice_number) {
    return { success: false, error: 'Missing required fields (carrier, pro_number, invoice_number)' };
  }

  if (input.invoice_total <= 0) {
    return { success: false, error: 'Invoice total must be greater than zero' };
  }

  // 2. Dedup constraint check against DB unique index (customer_id, carrier, invoice_number, pro_number)
  const { data: existing } = await supabase
    .from('invoices')
    .select('id')
    .eq('customer_id', input.customerId)
    .eq('carrier', input.carrier)
    .eq('invoice_number', input.invoice_number)
    .eq('pro_number', input.pro_number)
    .maybeSingle();

  if (existing) {
    return { 
      success: false, 
      isDuplicate: true, 
      error: `Invoice ${input.invoice_number} (PRO ${input.pro_number}) already exists for this carrier` 
    };
  }

  // 3. Construct canonical InvoiceJSON structure
  const invoiceId = crypto.randomUUID();
  const canonicalInvoiceJson = {
    carrier: input.carrier,
    pro_number: input.pro_number,
    invoice_number: input.invoice_number,
    invoice_date: input.invoice_date,
    origin_zip: input.origin_zip,
    dest_zip: input.dest_zip,
    billed_weight: input.billed_weight,
    billed_class: input.billed_class,
    line_items: input.line_items || [],
    accessorials: input.accessorials || [],
    fsc_amount: input.fsc_amount,
    fsc_pct: input.fsc_pct,
    invoice_total: input.invoice_total,
    notes: input.notes,
    raw_text_hash: crypto.createHash('sha256').update(JSON.stringify(input)).digest('hex'),
    manual_entry: true
  };

  // 4. Insert into invoices table
  const { data: inserted, error } = await supabase
    .from('invoices')
    .insert({
      id: invoiceId,
      customer_id: input.customerId,
      source: 'manual',
      carrier: input.carrier,
      pro_number: input.pro_number,
      invoice_number: input.invoice_number,
      invoice_date: input.invoice_date,
      invoice_total: input.invoice_total,
      parsed_json: canonicalInvoiceJson,
      parse_confidence: 1.0, // Human entered and confirmed
      file_path: null, // No source PDF for pure manual stragglers/faxes
      status: 'pending' // Ready for audit engine execution
    })
    .select('id')
    .single();

  if (error) {
    return { success: false, error: error.message };
  }

  return {
    success: true,
    invoiceId: inserted.id
  };
}
