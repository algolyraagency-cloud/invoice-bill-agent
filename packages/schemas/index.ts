import { z } from 'zod';

export const LineItemSchema = z.object({
  description: z.string(),
  charge_code: z.string().optional().nullable(),
  amount: z.number(),
});

export const AccessorialSchema = z.object({
  type: z.string(),
  amount: z.number(),
  authorized: z.boolean().optional().nullable(),
});

export const InvoiceJSONSchema = z.object({
  carrier: z.string(),
  pro_number: z.string(),
  invoice_number: z.string(),
  invoice_date: z.string(),
  origin_zip: z.string(),
  dest_zip: z.string(),
  billed_weight: z.number().nonnegative(),
  billed_class: z.number().optional().nullable(),
  line_items: z.array(LineItemSchema).default([]),
  accessorials: z.array(AccessorialSchema).default([]),
  fsc_amount: z.number().optional().nullable(),
  fsc_pct: z.number().optional().nullable(),
  invoice_total: z.number(),
  raw_text_hash: z.string().optional().nullable(),
});

export const RateMatrixRowSchema = z.object({
  origin_zip_prefix: z.string(),
  dest_zip_prefix: z.string(),
  weight_break: z.string(),
  min_weight: z.number().default(0),
  rate: z.number(),
  min_charge: z.number().default(0),
  deficit_weight_eligible: z.boolean().default(true),
  effective_date_start: z.string(),
  effective_date_end: z.string(),
});

export const RateMatrixJSONSchema = z.object({
  carrier: z.string(),
  contract_id: z.string().optional().nullable(),
  effective_dates: z.record(z.string()).default({}),
  rates: z.array(RateMatrixRowSchema).default([]),
  discount_pct: z.number().default(0),
  absolute_min_charge: z.number().default(0),
  fak_mappings: z.record(z.number()).default({}),
  approved_accessorials: z.record(z.number()).default({}),
  exceptions: z.array(z.string()).default([]),
});

export const FlagSchema = z.object({
  invoice_id: z.string().optional().nullable(),
  check_type: z.enum(['DUP', 'RATE', 'FSC', 'ACCESSORIAL', 'REWEIGH', 'GUARANTEE', 'ARITH', 'TAX']),
  overcharge_cents: z.number().int(),
  confidence: z.number().min(0).max(1).default(1.0),
  evidence_json: z.record(z.any()),
  review_status: z.enum(['pending', 'approved', 'rejected', 'research']).default('pending'),
  reject_reason_code: z.string().optional().nullable(),
});

export const CreditMemoSchema = z.object({
  id: z.string().optional().nullable(),
  dispute_id: z.string().optional().nullable(),
  carrier: z.string(),
  memo_number: z.string(),
  original_invoice_ref: z.string(),
  amount_cents: z.number().int(),
  kind: z.enum(['credit_memo', 'refund_check']).default('credit_memo'),
  verification_status: z.enum(['pending', 'verified', 'rejected']).default('pending'),
  detected_via: z.enum(['stream', 'forwarded', 'manual']).default('stream'),
});

export const ExtractionCheckDetailSchema = z.object({
  check_name: z.string(),
  passed: z.boolean(),
  billed_value: z.number().optional().nullable(),
  calculated_value: z.number().optional().nullable(),
  discrepancy: z.number().optional().nullable(),
  message: z.string(),
});

export const InvoiceValidationResultSchema = z.object({
  invoice_number: z.string(),
  carrier: z.string(),
  is_valid: z.boolean(),
  composite_confidence: z.number().min(0).max(1),
  needs_calibration_queue: z.boolean(),
  arithmetic_sum_match: z.boolean(),
  linehaul_fsc_accessorial_match: z.boolean(),
  checks: z.array(ExtractionCheckDetailSchema).default([]),
  reconciliation_notes: z.array(z.string()).default([]),
});

export const ContractSanityIssueSchema = z.object({
  issue_type: z.enum([
    'duplicate_lane',
    'monotonicity_violation',
    'overlapping_breaks',
    'missing_fsc_month',
    'min_charge_anomaly'
  ]),
  severity: z.enum(['error', 'warning']).default('error'),
  details: z.record(z.any()).default({}),
  message: z.string(),
});

export const SpotCheckItemSchema = z.object({
  sample_index: z.number().int(),
  origin_zip_prefix: z.string(),
  dest_zip_prefix: z.string(),
  weight_break: z.string(),
  matrix_rate: z.number(),
  matrix_min_charge: z.number(),
  page_ref_hint: z.string().optional().nullable(),
});

export const SpotVerificationResultSchema = z.object({
  sample_index: z.number().int(),
  matched: z.boolean(),
  actual_page_rate: z.number().optional().nullable(),
  reviewer_notes: z.string().optional().nullable(),
});

export const ContractValidationResultSchema = z.object({
  contract_id: z.string().optional().nullable(),
  carrier: z.string(),
  is_valid: z.boolean(),
  status: z.enum(['valid', 'warning', 'rejected']).default('valid'),
  total_lanes_checked: z.number().int().default(0),
  issues: z.array(ContractSanityIssueSchema).default([]),
  spot_checks: z.array(SpotCheckItemSchema).default([]),
  spot_verification_passed: z.boolean().optional().nullable(),
  contract_validation_json: z.record(z.any()).default({}),
});

export const CalibrationMetricSchema = z.object({
  category: z.enum(['check_type', 'carrier', 'overall']),
  name: z.string(),
  total_cases: z.number().int().default(0),
  true_positives: z.number().int().default(0),
  false_positives: z.number().int().default(0),
  false_negatives: z.number().int().default(0),
  true_negatives: z.number().int().default(0),
  precision: z.number().default(0),
  recall: z.number().default(0),
  f1_score: z.number().default(0),
  gate_passed: z.boolean().default(false),
});

export type LineItem = z.infer<typeof LineItemSchema>;
export type Accessorial = z.infer<typeof AccessorialSchema>;
export type InvoiceJSON = z.infer<typeof InvoiceJSONSchema>;
export type RateMatrixRow = z.infer<typeof RateMatrixRowSchema>;
export type RateMatrixJSON = z.infer<typeof RateMatrixJSONSchema>;
export type Flag = z.infer<typeof FlagSchema>;
export type CreditMemo = z.infer<typeof CreditMemoSchema>;
export type ExtractionCheckDetail = z.infer<typeof ExtractionCheckDetailSchema>;
export type InvoiceValidationResult = z.infer<typeof InvoiceValidationResultSchema>;
export type ContractSanityIssue = z.infer<typeof ContractSanityIssueSchema>;
export type SpotCheckItem = z.infer<typeof SpotCheckItemSchema>;
export type SpotVerificationResult = z.infer<typeof SpotVerificationResultSchema>;
export type ContractValidationResult = z.infer<typeof ContractValidationResultSchema>;
export type CalibrationMetric = z.infer<typeof CalibrationMetricSchema>;

