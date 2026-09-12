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
  id: z.string().optional().nullable(),
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
  bol_number: z.string().optional().nullable(),
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

export const AuditRunStatsSchema = z.object({
  total_invoices_audited: z.number().int().default(0),
  clean_invoices_count: z.number().int().default(0),
  flagged_invoices_count: z.number().int().default(0),
  total_flags_count: z.number().int().default(0),
  total_overcharge_cents: z.number().int().default(0),
  flags_by_check_type: z.record(z.number().int()).default({}),
  flags_by_carrier: z.record(z.number().int()).default({}),
  overcharge_by_check_type: z.record(z.number().int()).default({}),
  duration_seconds: z.number().default(0),
});

export const AuditRunResultSchema = z.object({
  audit_run_id: z.string(),
  customer_id: z.string(),
  scope: z.record(z.any()).default({}),
  started_at: z.string(),
  completed_at: z.string(),
  stats: AuditRunStatsSchema,
  flags_by_invoice: z.record(z.array(FlagSchema)).default({}),
  all_flags: z.array(FlagSchema).default([]),
});

export const ReviewActionSchema = z.enum(['approve', 'reject', 'research', 'resolve_research']);

export const ReviewActionRequestSchema = z.object({
  flag_id: z.string(),
  action: ReviewActionSchema,
  reviewer_id: z.string(),
  reason_code: z.string().optional().nullable(),
  notes: z.string().optional().nullable(),
  duration_seconds: z.number().optional().nullable(),
});

export const ReviewQueueItemSchema = z.object({
  id: z.string(),
  invoice_id: z.string(),
  check_type: z.string(),
  overcharge_cents: z.number().int(),
  confidence: z.number().min(0).max(1).default(1.0),
  evidence_json: z.record(z.any()).default({}),
  review_status: z.enum(['pending', 'approved', 'rejected', 'research']).default('pending'),
  reject_reason_code: z.string().optional().nullable(),
  reviewed_by: z.string().optional().nullable(),
  reviewed_at: z.string().optional().nullable(),
  carrier: z.string(),
  pro_number: z.string(),
  invoice_number: z.string(),
  invoice_date: z.string(),
  invoice_total: z.number(),
  file_path: z.string().optional().nullable(),
  signed_pdf_url: z.string().optional().nullable(),
  customer_id: z.string().optional().nullable(),
  created_at: z.string().optional().nullable(),
});

export const ReviewQueueSummarySchema = z.object({
  pending_count: z.number().int().default(0),
  approved_count: z.number().int().default(0),
  rejected_count: z.number().int().default(0),
  research_count: z.number().int().default(0),
  total_reviewed_count: z.number().int().default(0),
  total_approved_overcharge_cents: z.number().int().default(0),
  avg_duration_seconds: z.number().default(0),
  flags_by_check_type: z.record(z.number().int()).default({}),
  flags_by_carrier: z.record(z.number().int()).default({}),
});

export const ReviewEventRecordSchema = z.object({
  id: z.string().optional().nullable(),
  flag_id: z.string(),
  action: z.string(),
  reason_code: z.string().optional().nullable(),
  reviewer: z.string(),
  notes: z.string().optional().nullable(),
  duration_seconds: z.number().optional().nullable(),
  created_at: z.string().optional().nullable(),
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
export type AuditRunStats = z.infer<typeof AuditRunStatsSchema>;
export type AuditRunResult = z.infer<typeof AuditRunResultSchema>;
export type ReviewAction = z.infer<typeof ReviewActionSchema>;
export type ReviewActionRequest = z.infer<typeof ReviewActionRequestSchema>;
export type ReviewQueueItem = z.infer<typeof ReviewQueueItemSchema>;
export type ReviewQueueSummary = z.infer<typeof ReviewQueueSummarySchema>;
export type ReviewEventRecord = z.infer<typeof ReviewEventRecordSchema>;

export const PrecisionReportItemSchema = z.object({
  category: z.string(),
  name: z.string(),
  approved_count: z.number().int().default(0),
  rejected_count: z.number().int().default(0),
  pending_count: z.number().int().default(0),
  research_count: z.number().int().default(0),
  total_reviewed: z.number().int().default(0),
  precision_pct: z.number().default(0),
  meets_pilot_target: z.boolean().default(false),
  meets_scale_target: z.boolean().default(false),
  meets_enterprise_target: z.boolean().default(false),
});

export const FeedbackTicketSchema = z.object({
  ticket_id: z.string(),
  reason_code: z.string(),
  rejection_count: z.number().int().default(0),
  percentage_of_rejections: z.number().default(0),
  category: z.string(),
  priority: z.enum(['HIGH', 'MEDIUM', 'LOW']).default('MEDIUM'),
  affected_carrier: z.string().optional().nullable(),
  affected_check_type: z.string().optional().nullable(),
  recommended_action: z.string(),
  sample_flag_ids: z.array(z.string()).default([]),
  created_at: z.string(),
});

export const MonthlyRetroReportSchema = z.object({
  month: z.string(),
  total_flags_reviewed: z.number().int().default(0),
  total_approved: z.number().int().default(0),
  total_rejected: z.number().int().default(0),
  overall_precision_pct: z.number().default(0),
  trajectory_status: z.string().default('PILOT_GATE_PASSED'),
  precision_by_check_type: z.record(PrecisionReportItemSchema).default({}),
  precision_by_carrier: z.record(PrecisionReportItemSchema).default({}),
  top_reason_codes: z.array(z.record(z.any())).default([]),
  generated_tickets: z.array(FeedbackTicketSchema).default([]),
  generated_at: z.string(),
});

export type PrecisionReportItem = z.infer<typeof PrecisionReportItemSchema>;
export type FeedbackTicket = z.infer<typeof FeedbackTicketSchema>;
export type MonthlyRetroReport = z.infer<typeof MonthlyRetroReportSchema>;

export const DisputeStatusSchema = z.enum(['drafted', 'sent', 'responded', 'credit_issued', 'denied']);

export const RecoveryReportClaimItemSchema = z.object({
  flag_id: z.string(),
  invoice_id: z.string(),
  pro_number: z.string(),
  invoice_number: z.string(),
  invoice_date: z.string(),
  carrier: z.string(),
  check_type: z.string(),
  billed_amount: z.number(),
  contract_amount: z.number(),
  overcharge_cents: z.number().int(),
  overcharge_dollars: z.number(),
  contract_clause: z.string(),
  evidence_summary: z.string(),
  page_number: z.number().int().optional().nullable(),
});

export const RecoveryReportSummarySchema = z.object({
  report_id: z.string(),
  customer_id: z.string(),
  customer_name: z.string(),
  report_title: z.string().default('Freight Audit & Recovery Report'),
  period_start: z.string(),
  period_end: z.string(),
  generated_at: z.string(),
  total_invoices_audited: z.number().int().default(0),
  total_flagged_invoices: z.number().int().default(0),
  total_approved_claims: z.number().int().default(0),
  total_recoverable_cents: z.number().int().default(0),
  total_recoverable_dollars: z.number().default(0),
  estimated_shipper_recovery_dollars: z.number().default(0),
  contingency_fee_dollars: z.number().default(0),
  by_carrier: z.record(z.record(z.any())).default({}),
  by_check_type: z.record(z.record(z.any())).default({}),
  claims: z.array(RecoveryReportClaimItemSchema).default([]),
});

export const DisputeLetterItemSchema = z.object({
  dispute_id: z.string(),
  flag_id: z.string(),
  invoice_id: z.string(),
  customer_id: z.string(),
  customer_name: z.string(),
  customer_slug: z.string(),
  carrier: z.string(),
  carrier_dispute_email: z.string(),
  carrier_phone: z.string().optional().nullable(),
  invoice_number: z.string(),
  pro_number: z.string(),
  invoice_date: z.string(),
  billed_amount: z.number(),
  contract_amount: z.number(),
  overcharge_dollars: z.number(),
  check_type: z.string(),
  contract_clause: z.string(),
  dispute_reason_text: z.string(),
  evidence_details: z.record(z.any()).default({}),
  status: DisputeStatusSchema.default('drafted'),
  letter_pdf_path: z.string().optional().nullable(),
  mailto_link: z.string(),
  email_subject: z.string(),
  email_body_text: z.string(),
  email_body_html: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const DisputeBatchPacketSchema = z.object({
  carrier: z.string(),
  carrier_dispute_email: z.string(),
  customer_name: z.string(),
  customer_slug: z.string(),
  disputes_count: z.number().int().default(0),
  total_disputed_dollars: z.number().default(0),
  disputes: z.array(DisputeLetterItemSchema).default([]),
  combined_mailto_link: z.string(),
  created_at: z.string(),
});

export type DisputeStatus = z.infer<typeof DisputeStatusSchema>;
export type RecoveryReportClaimItem = z.infer<typeof RecoveryReportClaimItemSchema>;
export type RecoveryReportSummary = z.infer<typeof RecoveryReportSummarySchema>;
export type DisputeLetterItem = z.infer<typeof DisputeLetterItemSchema>;
export type DisputeBatchPacket = z.infer<typeof DisputeBatchPacketSchema>;

export const OnboardingChecklistStepSchema = z.object({
  step_key: z.string(),
  title: z.string(),
  description: z.string(),
  status: z.enum(['pending', 'in_progress', 'completed', 'signed', 'ready']).default('pending'),
  action_label: z.string().optional().nullable(),
  action_tab: z.string().optional().nullable(),
});

export const OnboardingChecklistSchema = z.object({
  forwarding_rule: OnboardingChecklistStepSchema,
  contracts_uploaded: OnboardingChecklistStepSchema,
  first_invoices_in: OnboardingChecklistStepSchema,
  recovery_agreement: OnboardingChecklistStepSchema,
  report_ready: OnboardingChecklistStepSchema,
  completed_steps_count: z.number().int().default(0),
  total_steps_count: z.number().int().default(5),
  is_fully_onboarded: z.boolean().default(false),
});

export const CustomerDashboardKPIsSchema = z.object({
  total_recoverable_cents: z.number().int().default(0),
  total_recoverable_dollars: z.number().default(0),
  estimated_shipper_net_dollars: z.number().default(0),
  contingency_fee_dollars: z.number().default(0),
  total_invoices_audited: z.number().int().default(0),
  total_flagged_invoices: z.number().int().default(0),
  open_disputes_count: z.number().int().default(0),
  verified_credit_memos_count: z.number().int().default(0),
  verified_credit_memos_dollars: z.number().default(0),
  active_contracts_count: z.number().int().default(0),
});

export const CustomerDashboardResponseSchema = z.object({
  customer_id: z.string(),
  name: z.string(),
  slug: z.string(),
  inbound_email: z.string(),
  dispute_tracking_email: z.string(),
  kpis: CustomerDashboardKPIsSchema,
  checklist: OnboardingChecklistSchema,
  carrier_summary: z.record(z.any()).default({}),
  recent_activity: z.array(z.record(z.any())).default([]),
});

export const ContractIntakeRequestSchema = z.object({
  carrier: z.string(),
  rung: z.enum(['A', 'B', 'C', 'D']).default('A'),
  has_signed_agreement: z.boolean().default(true),
  notes: z.string().optional().nullable(),
});

export const ContractListItemSchema = z.object({
  id: z.string(),
  carrier: z.string(),
  rung: z.enum(['A', 'B', 'C', 'D']),
  file_path: z.string().optional().nullable(),
  file_name: z.string(),
  effective_date: z.string().optional().nullable(),
  parsed_lanes_count: z.number().int().default(0),
  validation_status: z.enum(['valid', 'needs_spot_check', 'rejected']).default('valid'),
  spot_checks_count: z.number().int().default(0),
  created_at: z.string(),
});

export const CreditMemoIntakeRequestSchema = z.object({
  carrier: z.string(),
  memo_number: z.string(),
  original_invoice_ref: z.string(),
  amount_dollars: z.number(),
  kind: z.enum(['credit_memo', 'refund_check']).default('credit_memo'),
  notes: z.string().optional().nullable(),
});

export const CreditMemoListItemSchema = z.object({
  id: z.string(),
  carrier: z.string(),
  memo_number: z.string(),
  original_invoice_ref: z.string(),
  amount_cents: z.number().int(),
  amount_dollars: z.number(),
  kind: z.string(),
  verification_status: z.enum(['pending', 'verified', 'rejected']).default('pending'),
  matched_dispute_id: z.string().optional().nullable(),
  verified_at: z.string().optional().nullable(),
  created_at: z.string(),
});

export const CustomerPortalSessionSchema = z.object({
  user_id: z.string(),
  customer_id: z.string(),
  email: z.string(),
  role: z.enum(['owner', 'ap_clerk', 'internal_reviewer']),
  customer_name: z.string(),
  customer_slug: z.string(),
});

export type OnboardingChecklistStep = z.infer<typeof OnboardingChecklistStepSchema>;
export type OnboardingChecklist = z.infer<typeof OnboardingChecklistSchema>;
export type CustomerDashboardKPIs = z.infer<typeof CustomerDashboardKPIsSchema>;
export type CustomerDashboardResponse = z.infer<typeof CustomerDashboardResponseSchema>;
export type ContractIntakeRequest = z.infer<typeof ContractIntakeRequestSchema>;
export type ContractListItem = z.infer<typeof ContractListItemSchema>;
export type CreditMemoIntakeRequest = z.infer<typeof CreditMemoIntakeRequestSchema>;
export type CreditMemoListItem = z.infer<typeof CreditMemoListItemSchema>;
export type CustomerPortalSession = z.infer<typeof CustomerPortalSessionSchema>;

export const RecoveryAgreementSignInputSchema = z.object({
  customer_id: z.string(),
  signer_name: z.string(),
  signer_title: z.string(),
  concierge_handling: z.boolean().default(false),
  agree_terms: z.boolean(),
});

export const RecoveryAgreementRecordSchema = z.object({
  agreement_id: z.string(),
  customer_id: z.string(),
  customer_name: z.string(),
  contingency_fee_pct: z.number().default(35.0),
  signed_at: z.string(),
  signer_name: z.string(),
  signer_title: z.string(),
  pdf_path: z.string(),
  is_active: z.boolean().default(true),
});

export type RecoveryAgreementSignInput = z.infer<typeof RecoveryAgreementSignInputSchema>;
export type RecoveryAgreementRecord = z.infer<typeof RecoveryAgreementRecordSchema>;

export const CreditMemoDetectionCandidateSchema = z.object({
  carrier: z.string(),
  memo_number: z.string(),
  original_invoice_ref: z.string(),
  amount_cents: z.number().int(),
  amount_dollars: z.number(),
  kind: z.enum(['credit_memo', 'refund_check']).default('credit_memo'),
  detected_via: z.enum(['stream', 'forwarded', 'manual']).default('stream'),
  raw_text_snippet: z.string().optional().nullable(),
  confidence_score: z.number().default(1.0),
});

export const CreditMemoVerificationResultSchema = z.object({
  credit_memo_id: z.string(),
  verification_status: z.enum(['verified', 'pending', 'rejected', 'unmatched']),
  matched_dispute_id: z.string().optional().nullable(),
  carrier: z.string(),
  original_invoice_ref: z.string(),
  memo_amount_dollars: z.number(),
  dispute_amount_dollars: z.number().optional().nullable(),
  discrepancy_dollars: z.number().default(0.0),
  verified_at: z.string().optional().nullable(),
  notes: z.string().default(''),
});

export const CommissionInvoiceItemSchema = z.object({
  credit_memo_id: z.string(),
  dispute_id: z.string(),
  carrier: z.string(),
  pro_number: z.string(),
  original_invoice_ref: z.string(),
  gross_credit_cents: z.number().int(),
  gross_credit_dollars: z.number(),
  commission_rate_pct: z.number().default(35.0),
  commission_cents: z.number().int(),
  commission_dollars: z.number(),
});

export const CommissionInvoiceRecordSchema = z.object({
  id: z.string(),
  customer_id: z.string(),
  customer_name: z.string(),
  billing_period: z.string(),
  items: z.array(CommissionInvoiceItemSchema).default([]),
  total_gross_credit_cents: z.number().int().default(0),
  total_gross_credit_dollars: z.number().default(0.0),
  total_commission_cents: z.number().int().default(0),
  total_commission_dollars: z.number().default(0.0),
  stripe_invoice_id: z.string().optional().nullable(),
  stripe_hosted_url: z.string().optional().nullable(),
  status: z.enum(['draft', 'sent', 'paid', 'overdue', 'void']).default('draft'),
  net_terms_due_at: z.string(),
  pdf_path: z.string().optional().nullable(),
  created_at: z.string(),
});

export const ResendDisputeInputSchema = z.object({
  dispute_id: z.string(),
  stronger_evidence_notes: z.string(),
  additional_tariff_clauses: z.array(z.string()).default([]),
});

export const UnrecoverableDisputeRecordSchema = z.object({
  dispute_id: z.string(),
  customer_id: z.string(),
  carrier: z.string(),
  pro_number: z.string(),
  original_invoice_number: z.string(),
  overcharge_dollars: z.number(),
  denial_reason: z.string(),
  marked_unrecoverable_at: z.string(),
});

export type CreditMemoDetectionCandidate = z.infer<typeof CreditMemoDetectionCandidateSchema>;
export type CreditMemoVerificationResult = z.infer<typeof CreditMemoVerificationResultSchema>;
export type CommissionInvoiceItem = z.infer<typeof CommissionInvoiceItemSchema>;
export type CommissionInvoiceRecord = z.infer<typeof CommissionInvoiceRecordSchema>;
export type ResendDisputeInput = z.infer<typeof ResendDisputeInputSchema>;
export type UnrecoverableDisputeRecord = z.infer<typeof UnrecoverableDisputeRecordSchema>;




