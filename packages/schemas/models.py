"""
Shared Pydantic v2 schemas for RateGuard AI.
Mirrored in TypeScript via Zod (packages/schemas/index.ts).
"""
from typing import Any, Dict, List, Optional

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
