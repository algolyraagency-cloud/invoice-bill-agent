"""
Shared Pydantic v2 schemas for RateGuard AI.
Mirrored in TypeScript via Zod (packages/schemas/index.ts).
"""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str = Field(..., description="Line item description")
    charge_code: Optional[str] = Field(None, description="Charge code (e.g., 400, FSC, LGT)")
    amount: float = Field(..., description="Line item dollar amount")


class Accessorial(BaseModel):
    type: str = Field(..., description="Accessorial code/type (e.g. liftgate, residential, limited_access)")
    amount: float = Field(..., description="Accessorial charge amount in dollars")
    authorized: Optional[bool] = Field(None, description="Whether explicitly authorized on BOL/contract")


class InvoiceJSON(BaseModel):
    id: Optional[str] = Field(None, description="Invoice unique ID")
    carrier: str = Field(..., description="Carrier name (e.g. ABF Freight, XPO Logistics, Roadrunner)")
    pro_number: str = Field(..., description="Carrier PRO tracking number")
    invoice_number: str = Field(..., description="Carrier invoice number")
    invoice_date: str = Field(..., description="Invoice billing date (YYYY-MM-DD)")
    origin_zip: str = Field(..., description="Origin 5-digit or 3-digit zip code")
    dest_zip: str = Field(..., description="Destination 5-digit or 3-digit zip code")
    billed_weight: float = Field(..., ge=0, description="Total billed weight in pounds")
    billed_class: Optional[float] = Field(None, description="Billed NMFC freight class (e.g. 50, 70, 92.5)")
    line_items: List[LineItem] = Field(default_factory=list, description="Extracted line charges")
    accessorials: List[Accessorial] = Field(default_factory=list, description="Accessorial charges")
    fsc_amount: Optional[float] = Field(None, description="Fuel surcharge dollar amount")
    fsc_pct: Optional[float] = Field(None, description="Fuel surcharge percentage applied")
    invoice_total: float = Field(..., description="Total invoice amount billed by carrier")
    bol_number: Optional[str] = Field(None, description="Bill of Lading tracking number")
    raw_text_hash: Optional[str] = Field(None, description="SHA256 of raw invoice document text")


class RateMatrixRow(BaseModel):
    origin_zip_prefix: str = Field(..., description="Origin 3-digit or 5-digit zip prefix")
    dest_zip_prefix: str = Field(..., description="Destination 3-digit or 5-digit zip prefix")
    weight_break: str = Field(..., description="Weight break tier (L5C, M5C, M1M, M2M, M5M, M10M)")
    min_weight: float = Field(default=0.0, description="Minimum weight in lbs for this break")
    rate: float = Field(..., description="Rate in $/cwt (or flat rate)")
    min_charge: float = Field(default=0.0, description="Absolute minimum charge floor")
    deficit_weight_eligible: bool = Field(default=True, description="Whether deficit weight bumping applies")
    effective_date_start: str = Field(..., description="Effective start date (YYYY-MM-DD)")
    effective_date_end: str = Field(..., description="Effective end date (YYYY-MM-DD)")


class RateMatrixJSON(BaseModel):
    carrier: str = Field(..., description="Carrier name")
    contract_id: Optional[str] = Field(None, description="Associated contract UUID")
    effective_dates: Dict[str, str] = Field(default_factory=dict, description="start and end dates")
    rates: List[RateMatrixRow] = Field(default_factory=list, description="Materialized lane matrix rows")
    discount_pct: float = Field(default=0.0, description="Negotiated discount percentage from base tariff")
    absolute_min_charge: float = Field(default=0.0, description="Contract floor minimum charge")
    fak_mappings: Dict[str, float] = Field(default_factory=dict, description="FAK class tier substitutions")
    approved_accessorials: Dict[str, float] = Field(default_factory=dict, description="Contract accessorial rates")
    exceptions: List[str] = Field(default_factory=list, description="Contractual exceptions and riders")


class FSCEntry(BaseModel):
    carrier: str
    effective_week_start: Optional[str] = None
    effective_week_end: Optional[str] = None
    month: Optional[str] = None
    min_diesel_price: float
    max_diesel_price: float
    fsc_pct: float


class Flag(BaseModel):
    invoice_id: Optional[str] = None
    check_type: str = Field(..., description="DUP, RATE, FSC, ACCESSORIAL, REWEIGH, GUARANTEE, ARITH, TAX")
    overcharge_cents: int = Field(..., description="Discrepancy in integer cents")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_json: Dict[str, Any] = Field(..., description="Evidence data for dispute generator")
    review_status: str = Field(default="pending", description="pending, approved, rejected, research")
    reject_reason_code: Optional[str] = None


class CreditMemo(BaseModel):
    id: Optional[str] = None
    dispute_id: Optional[str] = None
    carrier: str
    memo_number: str
    original_invoice_ref: str
    amount_cents: int
    kind: str = Field(default="credit_memo", description="credit_memo or refund_check")
    verification_status: str = Field(default="pending", description="pending, verified, rejected")
    detected_via: str = Field(default="stream", description="stream, forwarded, manual")


class ExtractionCheckDetail(BaseModel):
    check_name: str
    passed: bool
    billed_value: Optional[float] = None
    calculated_value: Optional[float] = None
    discrepancy: Optional[float] = None
    message: str


class InvoiceValidationResult(BaseModel):
    invoice_number: str
    carrier: str
    is_valid: bool
    composite_confidence: float = Field(..., ge=0.0, le=1.0)
    needs_calibration_queue: bool
    arithmetic_sum_match: bool
    linehaul_fsc_accessorial_match: bool
    checks: List[ExtractionCheckDetail] = Field(default_factory=list)
    reconciliation_notes: List[str] = Field(default_factory=list)


class ContractSanityIssue(BaseModel):
    issue_type: str = Field(..., description="duplicate_lane, monotonicity_violation, overlapping_breaks, missing_fsc_month, min_charge_anomaly")
    severity: str = Field(default="error", description="error or warning")
    details: Dict[str, Any] = Field(default_factory=dict)
    message: str


class SpotCheckItem(BaseModel):
    sample_index: int
    origin_zip_prefix: str
    dest_zip_prefix: str
    weight_break: str
    matrix_rate: float
    matrix_min_charge: float
    page_ref_hint: Optional[str] = None


class SpotVerificationResult(BaseModel):
    sample_index: int
    matched: bool
    actual_page_rate: Optional[float] = None
    reviewer_notes: Optional[str] = None


class ContractValidationResult(BaseModel):
    contract_id: Optional[str] = None
    carrier: str
    is_valid: bool
    status: str = Field(default="valid", description="valid, warning, rejected")
    total_lanes_checked: int = 0
    issues: List[ContractSanityIssue] = Field(default_factory=list)
    spot_checks: List[SpotCheckItem] = Field(default_factory=list)
    spot_verification_passed: Optional[bool] = None
    contract_validation_json: Dict[str, Any] = Field(default_factory=dict)


class CalibrationMetric(BaseModel):
    category: str = Field(..., description="check_type, carrier, or overall")
    name: str
    total_cases: int = 0
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    true_negatives: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    gate_passed: bool = False


class AuditRunStats(BaseModel):
    total_invoices_audited: int = 0
    clean_invoices_count: int = 0
    flagged_invoices_count: int = 0
    total_flags_count: int = 0
    total_overcharge_cents: int = 0
    flags_by_check_type: Dict[str, int] = Field(default_factory=dict)
    flags_by_carrier: Dict[str, int] = Field(default_factory=dict)
    overcharge_by_check_type: Dict[str, int] = Field(default_factory=dict)
    duration_seconds: float = 0.0


class AuditRunResult(BaseModel):
    audit_run_id: str
    customer_id: str
    scope: Dict[str, Any] = Field(default_factory=dict)
    started_at: str
    completed_at: str
    stats: AuditRunStats
    flags_by_invoice: Dict[str, List[Flag]] = Field(default_factory=dict)
    all_flags: List[Flag] = Field(default_factory=list)


ReviewAction = Literal["approve", "reject", "research", "resolve_research"]


class ReviewActionRequest(BaseModel):
    flag_id: str = Field(..., description="Target flag UUID")
    action: ReviewAction = Field(..., description="Review action to perform")
    reviewer_id: str = Field(..., description="User ID performing review")
    reason_code: Optional[str] = Field(None, description="Required for reject action from 8-code taxonomy")
    notes: Optional[str] = Field(None, description="Reviewer notes (mandatory for research)")
    duration_seconds: Optional[float] = Field(None, description="Time spent reviewing this flag in seconds")


class ReviewQueueItem(BaseModel):
    id: str = Field(..., description="Flag UUID")
    invoice_id: str = Field(..., description="Associated invoice UUID")
    check_type: str = Field(..., description="DUP, RATE, FSC, ARITH, etc.")
    overcharge_cents: int = Field(..., description="Calculated overcharge discrepancy")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_json: Dict[str, Any] = Field(default_factory=dict)
    review_status: str = Field(default="pending", description="pending, approved, rejected, research")
    reject_reason_code: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    # Joined invoice metadata
    carrier: str = Field(..., description="Carrier name")
    pro_number: str = Field(..., description="PRO tracking number")
    invoice_number: str = Field(..., description="Carrier invoice number")
    invoice_date: str = Field(..., description="Invoice billing date")
    invoice_total: float = Field(..., description="Billed invoice total amount in dollars")
    file_path: Optional[str] = None
    signed_pdf_url: Optional[str] = None
    customer_id: Optional[str] = None
    created_at: Optional[str] = None


class ReviewQueueSummary(BaseModel):
    pending_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    research_count: int = 0
    total_reviewed_count: int = 0
    total_approved_overcharge_cents: int = 0
    avg_duration_seconds: float = 0.0
    flags_by_check_type: Dict[str, int] = Field(default_factory=dict)
    flags_by_carrier: Dict[str, int] = Field(default_factory=dict)


class ReviewEventRecord(BaseModel):
    id: Optional[str] = None
    flag_id: str
    action: str
    reason_code: Optional[str] = None
    reviewer: str
    notes: Optional[str] = None
    duration_seconds: Optional[float] = None
    created_at: Optional[str] = None


class PrecisionReportItem(BaseModel):
    category: str = Field(..., description="overall, check_type, or carrier")
    name: str = Field(..., description="e.g. OVERALL, RATE, FSC, ABF Freight")
    approved_count: int = 0
    rejected_count: int = 0
    pending_count: int = 0
    research_count: int = 0
    total_reviewed: int = 0
    precision_pct: float = 0.0
    meets_pilot_target: bool = False  # >= 90.0%
    meets_scale_target: bool = False  # >= 95.0%
    meets_enterprise_target: bool = False  # >= 98.0%


class FeedbackTicket(BaseModel):
    ticket_id: str = Field(..., description="Unique ticket ID e.g. TICKET-CONTRACT-001")
    reason_code: str = Field(..., description="Rejection reason code from 8-code taxonomy")
    rejection_count: int = 0
    percentage_of_rejections: float = 0.0
    category: str = Field(..., description="contract_parser, invoice_parser, fsc_engine, or audit_engine")
    priority: str = Field(default="MEDIUM", description="HIGH, MEDIUM, LOW")
    affected_carrier: Optional[str] = None
    affected_check_type: Optional[str] = None
    recommended_action: str = Field(..., description="Concrete prompt/code fix recommendation")
    sample_flag_ids: List[str] = Field(default_factory=list)
    created_at: str = Field(..., description="Timestamp ISO string")


class MonthlyRetroReport(BaseModel):
    month: str = Field(..., description="YYYY-MM period e.g. 2026-08")
    total_flags_reviewed: int = 0
    total_approved: int = 0
    total_rejected: int = 0
    overall_precision_pct: float = 0.0
    trajectory_status: str = Field(default="PILOT_GATE_PASSED", description="BELOW_TARGET, PILOT_GATE_PASSED, SCALE_TARGET_MET, ENTERPRISE_MET")
    precision_by_check_type: Dict[str, PrecisionReportItem] = Field(default_factory=dict)
    precision_by_carrier: Dict[str, PrecisionReportItem] = Field(default_factory=dict)
    top_reason_codes: List[Dict[str, Any]] = Field(default_factory=list)
    generated_tickets: List[FeedbackTicket] = Field(default_factory=list)
    generated_at: str = Field(..., description="Generation timestamp ISO string")


DisputeStatus = Literal["drafted", "sent", "responded", "credit_issued", "denied"]


class RecoveryReportClaimItem(BaseModel):
    flag_id: str = Field(..., description="Flag UUID")
    invoice_id: str = Field(..., description="Invoice UUID")
    pro_number: str = Field(..., description="Carrier PRO number")
    invoice_number: str = Field(..., description="Invoice number")
    invoice_date: str = Field(..., description="Invoice billing date")
    carrier: str = Field(..., description="Carrier name e.g. ABF Freight")
    check_type: str = Field(..., description="RATE, FSC, DUP, ARITH")
    billed_amount: float = Field(..., description="Original billed dollars")
    contract_amount: float = Field(..., description="Correct contract dollars")
    overcharge_cents: int = Field(..., description="Overcharge in cents")
    overcharge_dollars: float = Field(..., description="Overcharge in dollars")
    contract_clause: str = Field(..., description="Cited contract clause or tariff rule")
    evidence_summary: str = Field(..., description="Human-readable mathematical or factual proof")
    page_number: Optional[int] = Field(None, description="Page number in contract or invoice")


class RecoveryReportSummary(BaseModel):
    report_id: str = Field(..., description="Unique report ID e.g. REP-202609-001")
    customer_id: str = Field(..., description="Customer organization UUID")
    customer_name: str = Field(..., description="Customer company name")
    report_title: str = Field(default="Freight Audit & Recovery Report")
    period_start: str = Field(..., description="Audit start date YYYY-MM-DD")
    period_end: str = Field(..., description="Audit end date YYYY-MM-DD")
    generated_at: str = Field(..., description="Generation timestamp ISO string")
    total_invoices_audited: int = 0
    total_flagged_invoices: int = 0
    total_approved_claims: int = 0
    total_recoverable_cents: int = 0
    total_recoverable_dollars: float = 0.0
    estimated_shipper_recovery_dollars: float = 0.0  # 65% share
    contingency_fee_dollars: float = 0.0  # 35% fee
    by_carrier: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    by_check_type: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    claims: List[RecoveryReportClaimItem] = Field(default_factory=list)


class DisputeLetterItem(BaseModel):
    dispute_id: str = Field(..., description="Dispute UUID e.g. DISP-2026-001")
    flag_id: str = Field(..., description="Flag UUID")
    invoice_id: str = Field(..., description="Invoice UUID")
    customer_id: str = Field(..., description="Customer organization UUID")
    customer_name: str = Field(..., description="Customer company name")
    customer_slug: str = Field(..., description="Customer slug for dispute email routing")
    carrier: str = Field(..., description="Carrier name")
    carrier_dispute_email: str = Field(..., description="Carrier dispute contact email")
    carrier_phone: Optional[str] = Field(None, description="Carrier billing phone")
    invoice_number: str = Field(..., description="Invoice number")
    pro_number: str = Field(..., description="PRO number")
    invoice_date: str = Field(..., description="Invoice date")
    billed_amount: float = Field(..., description="Billed total dollars")
    contract_amount: float = Field(..., description="Correct contract total dollars")
    overcharge_dollars: float = Field(..., description="Overcharge discrepancy dollars")
    check_type: str = Field(..., description="Audit check category")
    contract_clause: str = Field(..., description="Contract clause or tariff reference")
    dispute_reason_text: str = Field(..., description="Detailed factual explanation")
    evidence_details: Dict[str, Any] = Field(default_factory=dict)
    status: DisputeStatus = Field(default="drafted")
    letter_pdf_path: Optional[str] = None
    mailto_link: str = Field(..., description="Pre-encoded mailto: link for 1-click launch")
    email_subject: str = Field(..., description="Standard dispute subject line")
    email_body_text: str = Field(..., description="Plain-text formatted letter body")
    email_body_html: str = Field(..., description="HTML formatted letter body")
    created_at: str = Field(..., description="Creation ISO string")
    updated_at: str = Field(..., description="Last updated ISO string")


class DisputeBatchPacket(BaseModel):
    carrier: str = Field(..., description="Carrier name")
    carrier_dispute_email: str = Field(..., description="Carrier dispute email")
    customer_name: str = Field(..., description="Shipper organization name")
    customer_slug: str = Field(..., description="Shipper slug for CC routing")
    disputes_count: int = 0
    total_disputed_dollars: float = 0.0
    disputes: List[DisputeLetterItem] = Field(default_factory=list)
    combined_mailto_link: str = Field(..., description="Consolidated mailto link")
    created_at: str = Field(..., description="Creation timestamp")


class OnboardingChecklistStep(BaseModel):
    step_key: str = Field(..., description="forwarding_rule, contracts_uploaded, first_invoices_in, recovery_agreement, report_ready")
    title: str = Field(..., description="Display title")
    description: str = Field(..., description="Actionable instruction")
    status: Literal["pending", "in_progress", "completed", "signed", "ready"] = "pending"
    action_label: Optional[str] = None
    action_tab: Optional[str] = None


class OnboardingChecklist(BaseModel):
    forwarding_rule: OnboardingChecklistStep
    contracts_uploaded: OnboardingChecklistStep
    first_invoices_in: OnboardingChecklistStep
    recovery_agreement: OnboardingChecklistStep
    report_ready: OnboardingChecklistStep
    completed_steps_count: int = 0
    total_steps_count: int = 5
    is_fully_onboarded: bool = False


class CustomerDashboardKPIs(BaseModel):
    total_recoverable_cents: int = 0
    total_recoverable_dollars: float = 0.0
    estimated_shipper_net_dollars: float = 0.0  # 65% share
    contingency_fee_dollars: float = 0.0       # 35% fee
    total_invoices_audited: int = 0
    total_flagged_invoices: int = 0
    open_disputes_count: int = 0
    verified_credit_memos_count: int = 0
    verified_credit_memos_dollars: float = 0.0
    active_contracts_count: int = 0


class CustomerDashboardResponse(BaseModel):
    customer_id: str
    name: str
    slug: str
    inbound_email: str
    dispute_tracking_email: str
    kpis: CustomerDashboardKPIs
    checklist: OnboardingChecklist
    carrier_summary: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    recent_activity: List[Dict[str, Any]] = Field(default_factory=list)


class ContractIntakeRequest(BaseModel):
    carrier: str
    rung: Literal["A", "B", "C", "D"] = "A"
    has_signed_agreement: bool = True
    notes: Optional[str] = None


class ContractListItem(BaseModel):
    id: str
    carrier: str
    rung: Literal["A", "B", "C", "D"]
    file_path: Optional[str] = None
    file_name: str
    effective_date: Optional[str] = None
    parsed_lanes_count: int = 0
    validation_status: Literal["valid", "needs_spot_check", "rejected"] = "valid"
    spot_checks_count: int = 0
    created_at: str


class CreditMemoIntakeRequest(BaseModel):
    carrier: str
    memo_number: str
    original_invoice_ref: str
    amount_dollars: float
    kind: Literal["credit_memo", "refund_check"] = "credit_memo"
    notes: Optional[str] = None


class CreditMemoListItem(BaseModel):
    id: str
    carrier: str
    memo_number: str
    original_invoice_ref: str
    amount_cents: int
    amount_dollars: float
    kind: str
    verification_status: Literal["pending", "verified", "rejected"] = "pending"
    matched_dispute_id: Optional[str] = None
    verified_at: Optional[str] = None
    created_at: str


class CustomerPortalSession(BaseModel):
    user_id: str
    customer_id: str
    email: str
    role: Literal["owner", "ap_clerk", "internal_reviewer"]
    customer_name: str
    customer_slug: str


class RecoveryAgreementRequiredError(Exception):
    """Raised when an operation requiring a signed recovery agreement is attempted before signature."""
    def __init__(self, customer_name: str = "Customer"):
        self.customer_name = customer_name
        super().__init__(
            f"Recovery Agreement Launch Gate: Customer '{customer_name}' has not signed the 1-page "
            "contingency recovery agreement. Dispute letter generation and carrier exports are strictly "
            "gated until agreement signature (PRD Flow A & Implementation §5.4)."
        )


class RecoveryAgreementSignInput(BaseModel):
    customer_id: str = Field(..., description="Customer organization UUID")
    signer_name: str = Field(..., description="Full legal name of authorised officer")
    signer_title: str = Field(..., description="Corporate title e.g. CFO, VP Finance, Controller")
    concierge_handling: bool = Field(default=False, description="If true, 40% concierge fee applies; default 35%")
    agree_terms: bool = Field(..., description="Explicit acknowledgement of 35% fee and Net-15 memo-basis terms")


class RecoveryAgreementRecord(BaseModel):
    agreement_id: str = Field(..., description="Agreement document UUID")
    customer_id: str = Field(..., description="Customer organization UUID")
    customer_name: str = Field(..., description="Customer company name")
    contingency_fee_pct: float = Field(default=35.0, description="Contingency fee percentage")
    signed_at: str = Field(..., description="Timestamp ISO string of signature")
    signer_name: str = Field(..., description="Signer full name")
    signer_title: str = Field(..., description="Signer corporate title")
    pdf_path: str = Field(..., description="Path to generated agreement PDF in storage")
    is_active: bool = Field(default=True, description="Active contract status")


class UnverifiedMemoBillingError(Exception):
    """Raised when commission invoicing is attempted for credit memos that are not verified."""
    def __init__(self, memo_number: str = "Unknown"):
        self.memo_number = memo_number
        super().__init__(
            f"Revenue Integrity Violation: Credit Memo '{memo_number}' is not verified. "
            "Commission invoices can ONLY be generated from credit memos with verification_status='verified' "
            "(PRD Flow A & Implementation §6.1)."
        )


class CreditMemoDetectionCandidate(BaseModel):
    carrier: str
    memo_number: str
    original_invoice_ref: str
    amount_cents: int
    amount_dollars: float
    kind: Literal["credit_memo", "refund_check"] = "credit_memo"
    detected_via: Literal["stream", "forwarded", "manual"] = "stream"
    raw_text_snippet: Optional[str] = None
    confidence_score: float = 1.0


class CreditMemoVerificationResult(BaseModel):
    credit_memo_id: str
    verification_status: Literal["verified", "pending", "rejected", "unmatched"]
    matched_dispute_id: Optional[str] = None
    carrier: str
    original_invoice_ref: str
    memo_amount_dollars: float
    dispute_amount_dollars: Optional[float] = None
    discrepancy_dollars: float = 0.0
    verified_at: Optional[str] = None
    notes: str = ""


class CommissionInvoiceItem(BaseModel):
    credit_memo_id: str
    dispute_id: str
    carrier: str
    pro_number: str
    original_invoice_ref: str
    gross_credit_cents: int
    gross_credit_dollars: float
    commission_rate_pct: float = 35.0
    commission_cents: int
    commission_dollars: float


class CommissionInvoiceRecord(BaseModel):
    id: str
    customer_id: str
    customer_name: str
    billing_period: str
    items: List[CommissionInvoiceItem] = Field(default_factory=list)
    total_gross_credit_cents: int = 0
    total_gross_credit_dollars: float = 0.0
    total_commission_cents: int = 0
    total_commission_dollars: float = 0.0
    stripe_invoice_id: Optional[str] = None
    stripe_hosted_url: Optional[str] = None
    status: Literal["draft", "sent", "paid", "overdue", "void"] = "draft"
    net_terms_due_at: str
    pdf_path: Optional[str] = None
    created_at: str


class ResendDisputeInput(BaseModel):
    dispute_id: str
    stronger_evidence_notes: str
    additional_tariff_clauses: List[str] = Field(default_factory=list)


class UnrecoverableDisputeRecord(BaseModel):
    dispute_id: str
    customer_id: str
    carrier: str
    pro_number: str
    original_invoice_number: str
    overcharge_dollars: float
    denial_reason: str
    marked_unrecoverable_at: str





