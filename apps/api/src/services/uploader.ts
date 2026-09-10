import crypto from 'crypto';
import zlib from 'zlib';
import { SupabaseClient } from '@supabase/supabase-js';

export interface UploadedFileItem {
  filename: string;
  buffer: Buffer;
  size: number;
}

export interface CsvManifestRow {
  carrier?: string;
  invoice_number?: string;
  pro_number?: string;
  invoice_total?: number;
  invoice_date?: string;
  file_name: string;
}

export interface BatchUploadResult {
  totalProcessed: number;
  successfulInvoices: string[];
  skippedNonPdfs: number;
  errors: string[];
}

/**
 * Validates that the buffer starts with PDF magic bytes (%PDF-).
 */
export function isPdfMagicBytes(buffer: Buffer): boolean {
  if (buffer.length < 5) return false;
  return (
    buffer[0] === 0x25 && // %
    buffer[1] === 0x50 && // P
    buffer[2] === 0x44 && // D
    buffer[3] === 0x46 && // F
    buffer[4] === 0x2d    // -
  );
}

/**
 * Sanitizes zip entry path to prevent directory traversal / zip-slip attacks.
 */
export function sanitizePath(entryName: string): string {
  const normalized = entryName.replace(/\\/g, '/');
  // Strip leading slashes and any ../
  const clean = normalized.replace(/^\/+/, '').split('/').filter(p => p !== '..' && p !== '.').join('/');
  return clean;
}

/**
 * Parses CSV text manifest into structured rows.
 * Supports headers: carrier, invoice_number, pro_number, invoice_total (or amount), invoice_date (or date), file_name (or filename)
 */
export function parseCsvManifest(csvText: string): Map<string, CsvManifestRow> {
  const rows = new Map<string, CsvManifestRow>();
  const lines = csvText.split(/\r?\n/).filter(line => line.trim().length > 0);
  if (lines.length < 2) return rows;

  const headers = lines[0].split(',').map(h => h.trim().toLowerCase().replace(/['"]/g, ''));
  const fileIdx = headers.findIndex(h => h.includes('file') || h.includes('name'));
  if (fileIdx === -1) return rows;

  const carrierIdx = headers.findIndex(h => h.includes('carrier'));
  const invNumIdx = headers.findIndex(h => h.includes('invoice') && (h.includes('num') || h.includes('#')));
  const proIdx = headers.findIndex(h => h.includes('pro'));
  const totalIdx = headers.findIndex(h => h.includes('total') || h.includes('amount') || h.includes('charge'));
  const dateIdx = headers.findIndex(h => h.includes('date'));

  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i].split(',').map(c => c.trim().replace(/^["']|["']$/g, ''));
    const fileName = cols[fileIdx];
    if (!fileName) continue;

    rows.set(fileName.toLowerCase(), {
      file_name: fileName,
      carrier: carrierIdx !== -1 ? cols[carrierIdx] : undefined,
      invoice_number: invNumIdx !== -1 ? cols[invNumIdx] : undefined,
      pro_number: proIdx !== -1 ? cols[proIdx] : undefined,
      invoice_total: totalIdx !== -1 && !isNaN(parseFloat(cols[totalIdx])) ? parseFloat(cols[totalIdx]) : undefined,
      invoice_date: dateIdx !== -1 ? cols[dateIdx] : undefined,
    });
  }

  return rows;
}

/**
 * Processes batch uploaded files (individual PDFs or unpacks extracted ZIP items).
 */
export async function processBatchUpload(
  customerId: string,
  files: UploadedFileItem[],
  manifestCsvContent: string | null,
  supabase: SupabaseClient
): Promise<BatchUploadResult> {
  const result: BatchUploadResult = {
    totalProcessed: 0,
    successfulInvoices: [],
    skippedNonPdfs: 0,
    errors: []
  };

  const manifestMap = manifestCsvContent ? parseCsvManifest(manifestCsvContent) : new Map<string, CsvManifestRow>();

  for (const file of files) {
    result.totalProcessed += 1;

    // Safety checks: reject files larger than 25MB
    if (file.size > 25 * 1024 * 1024) {
      result.errors.push(`File ${file.filename} exceeds 25MB size limit.`);
      continue;
    }

    // Magic bytes sniffing
    if (!isPdfMagicBytes(file.buffer)) {
      result.skippedNonPdfs += 1;
      continue;
    }

    try {
      const fileHash = crypto.createHash('sha256').update(file.buffer).digest('hex');
      const invoiceId = crypto.randomUUID();
      const storagePath = `${customerId}/${invoiceId}.pdf`;

      // Check manifest match
      const baseName = file.filename.split('/').pop() || file.filename;
      const meta = manifestMap.get(baseName.toLowerCase()) || {};

      // Upload to Supabase Storage
      const { error: uploadError } = await supabase.storage
        .from('invoice-files')
        .upload(storagePath, file.buffer, {
          contentType: 'application/pdf',
          upsert: true
        });

      if (uploadError) {
        result.errors.push(`Storage upload failed for ${baseName}: ${uploadError.message}`);
        continue;
      }

      // Insert record in invoices table
      const { data: invoiceRecord, error: dbError } = await supabase
        .from('invoices')
        .insert({
          id: invoiceId,
          customer_id: customerId,
          source: 'upload',
          carrier: meta.carrier || 'Pending Extraction',
          pro_number: meta.pro_number || 'PENDING',
          invoice_number: meta.invoice_number || baseName.replace(/\.pdf$/i, ''),
          invoice_date: meta.invoice_date || new Date().toISOString().split('T')[0],
          invoice_total: meta.invoice_total || 0.00,
          file_path: storagePath,
          status: 'pending',
          parse_confidence: 1.0,
          parsed_json: {
            raw_text_hash: fileHash,
            original_filename: baseName,
            manifest_matched: !!meta.file_name
          }
        })
        .select('id')
        .single();

      if (dbError) {
        result.errors.push(`DB record creation failed for ${baseName}: ${dbError.message}`);
      } else if (invoiceRecord) {
        result.successfulInvoices.push(invoiceRecord.id);
      }

    } catch (err: any) {
      result.errors.push(`Processing error on ${file.filename}: ${err.message}`);
    }
  }

  return result;
}
