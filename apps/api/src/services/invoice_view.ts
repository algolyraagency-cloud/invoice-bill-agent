import { SupabaseClient } from '@supabase/supabase-js';

export interface InvoiceListFilter {
  customerId: string;
  source?: 'email' | 'upload' | 'manual';
  status?: string;
  carrier?: string;
  startDate?: string;
  endDate?: string;
  limit?: number;
  offset?: number;
}

export interface InvoiceListItem {
  id: string;
  carrier: string;
  pro_number: string;
  invoice_number: string;
  invoice_date: string;
  invoice_total: number;
  source: string;
  status: string;
  parse_confidence: number;
  flag_count: number;
  total_overcharge_cents: number;
  file_path: string | null;
  signed_url?: string | null;
  created_at: string;
}

export interface InvoiceListResponse {
  invoices: InvoiceListItem[];
  totalCount: number;
  offset: number;
  limit: number;
}

/**
 * Retrieves paginated invoice list for a customer organization with signed document URLs.
 */
export async function getCustomerInvoices(
  filter: InvoiceListFilter,
  supabase: SupabaseClient
): Promise<InvoiceListResponse> {
  let query = supabase
    .from('invoices')
    .select(`
      id,
      carrier,
      pro_number,
      invoice_number,
      invoice_date,
      invoice_total,
      source,
      status,
      parse_confidence,
      file_path,
      created_at,
      flags (
        id,
        overcharge_cents
      )
    `, { count: 'exact' })
    .eq('customer_id', filter.customerId);

  if (filter.source) query = query.eq('source', filter.source);
  if (filter.status) query = query.eq('status', filter.status);
  if (filter.carrier) query = query.ilike('carrier', `%${filter.carrier}%`);
  if (filter.startDate) query = query.gte('invoice_date', filter.startDate);
  if (filter.endDate) query = query.lte('invoice_date', filter.endDate);

  const limit = filter.limit || 50;
  const offset = filter.offset || 0;

  query = query
    .order('created_at', { ascending: false })
    .range(offset, offset + limit - 1);

  const { data, count, error } = await query;
  if (error || !data) {
    return { invoices: [], totalCount: 0, offset, limit };
  }

  // Map and generate temporary signed URLs for PDF viewing
  const items: InvoiceListItem[] = await Promise.all(
    data.map(async (row: any) => {
      let signedUrl: string | null = null;
      if (row.file_path) {
        try {
          const { data: signed } = await supabase.storage
            .from('invoice-files')
            .createSignedUrl(row.file_path, 3600); // 1-hour expiration
          signedUrl = signed?.signedUrl || null;
        } catch {
          signedUrl = null;
        }
      }

      const flags = row.flags || [];
      const overchargeSum = flags.reduce((sum: number, f: any) => sum + (f.overcharge_cents || 0), 0);

      return {
        id: row.id,
        carrier: row.carrier,
        pro_number: row.pro_number,
        invoice_number: row.invoice_number,
        invoice_date: row.invoice_date,
        invoice_total: parseFloat(row.invoice_total),
        source: row.source,
        status: row.status,
        parse_confidence: parseFloat(row.parse_confidence || 1.0),
        flag_count: flags.length,
        total_overcharge_cents: overchargeSum,
        file_path: row.file_path,
        signed_url: signedUrl,
        created_at: row.created_at
      };
    })
  );

  return {
    invoices: items,
    totalCount: count || items.length,
    offset,
    limit
  };
}
