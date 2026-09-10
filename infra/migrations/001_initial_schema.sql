-- ==============================================================================
-- Migration 001: RateGuard AI Core MVP Schema
-- Aligned with PRD v2.0 and Implementation Plan v1.0
-- ==============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. Customers (Shippers)
CREATE TABLE IF NOT EXISTS customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(64) UNIQUE NOT NULL, -- local part for inbound email: {slug}@in.rateguard.app
    industry VARCHAR(128),
    freight_spend_est NUMERIC(12, 2),
    recovery_agreement_signed_at TIMESTAMPTZ, -- Launch gate for dispute generation
    status VARCHAR(32) NOT NULL DEFAULT 'active', -- active, onboarding, suspended
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Users (Customer users & internal reviewers)
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID REFERENCES customers(id) ON DELETE CASCADE,
    email VARCHAR(255) UNIQUE NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT 'ap_clerk', -- owner, ap_clerk, internal_reviewer
    supabase_auth_id UUID UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. Inbound Emails (Postmark Webhook Payload Vault)
CREATE TABLE IF NOT EXISTS inbound_emails (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID REFERENCES customers(id) ON DELETE CASCADE,
    sender VARCHAR(255) NOT NULL,
    subject TEXT,
    raw_eml_path TEXT,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_status VARCHAR(32) NOT NULL DEFAULT 'pending', -- pending, processed, failed, duplicate
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 4. Invoices
CREATE TABLE IF NOT EXISTS invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    source VARCHAR(32) NOT NULL DEFAULT 'email', -- email, upload, manual
    carrier VARCHAR(64) NOT NULL,
    pro_number VARCHAR(64) NOT NULL,
    invoice_number VARCHAR(64) NOT NULL,
    invoice_date DATE NOT NULL,
    invoice_total NUMERIC(10, 2) NOT NULL,
    parsed_json JSONB, -- Canonical InvoiceJSON
    parse_confidence NUMERIC(4, 3) DEFAULT 1.000,
    file_path TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'pending', -- pending, parsed, audited, flagged, clean, failed
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- DEDUP CONSTRAINT: DB last line of defense against double billing
CREATE UNIQUE INDEX IF NOT EXISTS idx_invoices_dedup 
ON invoices(customer_id, carrier, invoice_number, pro_number);

CREATE INDEX IF NOT EXISTS idx_invoices_customer_date ON invoices(customer_id, invoice_date);
CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);

-- 5. Contracts
CREATE TABLE IF NOT EXISTS contracts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    carrier VARCHAR(64) NOT NULL,
    rung CHAR(1) NOT NULL DEFAULT 'A', -- A, B, C (Rung D is disqualified)
    file_path TEXT,
    rate_matrix_json JSONB,
    contract_validation_json JSONB,
    parse_confidence NUMERIC(4, 3) DEFAULT 1.000,
    effective_date DATE,
    parsed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 6. Rate Matrices (Materialized from contracts)
CREATE TABLE IF NOT EXISTS rate_matrices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id UUID NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    carrier VARCHAR(64) NOT NULL,
    origin_zip_prefix VARCHAR(10) NOT NULL, -- 3-digit or 5-digit zip/prefix
    dest_zip_prefix VARCHAR(10) NOT NULL,
    weight_break VARCHAR(16) NOT NULL, -- L5C, M5C, M1M, M2M, M5M, M10M, etc.
    min_weight NUMERIC(8, 2) NOT NULL DEFAULT 0,
    rate NUMERIC(10, 4) NOT NULL, -- $/cwt or flat rate
    min_charge NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    deficit_weight_eligible BOOLEAN NOT NULL DEFAULT true,
    effective_date_start DATE NOT NULL,
    effective_date_end DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rate_matrices_lookup 
ON rate_matrices(carrier, origin_zip_prefix, dest_zip_prefix, effective_date_start, effective_date_end);

-- 7. EIA Diesel Price Indices (Weekly DOE Diesel Benchmark)
CREATE TABLE IF NOT EXISTS eia_diesel_indices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    week_date DATE UNIQUE NOT NULL,
    national_average_price_cents INTEGER NOT NULL, -- e.g. 385 ($3.85/gal)
    source_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 8. FSC Tables (Carrier Fuel Surcharge Scales)
CREATE TABLE IF NOT EXISTS fsc_tables (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    carrier VARCHAR(64) NOT NULL,
    effective_week_start DATE,
    effective_week_end DATE,
    month VARCHAR(7), -- YYYY-MM for monthly pegging
    min_diesel_price NUMERIC(6, 3), -- Dollar range min
    max_diesel_price NUMERIC(6, 3), -- Dollar range max
    fsc_pct NUMERIC(5, 2) NOT NULL, -- Percentage e.g. 34.50%
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_fsc_carrier_dates ON fsc_tables(carrier, effective_week_start, effective_week_end);

-- 9. Audit Runs
CREATE TABLE IF NOT EXISTS audit_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    scope VARCHAR(128) NOT NULL DEFAULT 'all_invoices',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    stats_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 10. Audit Flags (Errors Detected)
CREATE TABLE IF NOT EXISTS flags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_run_id UUID REFERENCES audit_runs(id) ON DELETE CASCADE,
    invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    check_type VARCHAR(32) NOT NULL, -- DUP, RATE, FSC, ACCESSORIAL, REWEIGH, GUARANTEE, ARITH, TAX
    overcharge_cents INTEGER NOT NULL,
    confidence NUMERIC(4, 3) NOT NULL DEFAULT 1.000,
    evidence_json JSONB NOT NULL, -- invoice_ref, contract_clause, page_number, billed_value, correct_value
    review_status VARCHAR(32) NOT NULL DEFAULT 'pending', -- pending, approved, rejected, research
    reject_reason_code VARCHAR(64),
    reviewed_by UUID REFERENCES users(id),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_flags_invoice ON flags(invoice_id);
CREATE INDEX IF NOT EXISTS idx_flags_review_status ON flags(review_status);

-- 11. Reason Codes (Review Queue Taxonomy)
CREATE TABLE IF NOT EXISTS reason_codes (
    code VARCHAR(64) PRIMARY KEY,
    description TEXT NOT NULL,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
    count INTEGER NOT NULL DEFAULT 0
);

-- 12. Review Events (Audit Trail & Training Data Log)
CREATE TABLE IF NOT EXISTS review_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    flag_id UUID NOT NULL REFERENCES flags(id) ON DELETE CASCADE,
    action VARCHAR(32) NOT NULL, -- approve, reject, research
    reason_code VARCHAR(64),
    reviewer UUID REFERENCES users(id),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 13. Carrier Contacts Directory (For 1-Click Dispute Card)
CREATE TABLE IF NOT EXISTS carrier_contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    carrier VARCHAR(64) UNIQUE NOT NULL,
    dispute_email VARCHAR(255) NOT NULL,
    billing_phone VARCHAR(32),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 14. Disputes
CREATE TABLE IF NOT EXISTS disputes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    flag_id UUID NOT NULL REFERENCES flags(id) ON DELETE CASCADE,
    letter_path TEXT,
    sent_by UUID REFERENCES users(id),
    sent_at TIMESTAMPTZ,
    status VARCHAR(32) NOT NULL DEFAULT 'drafted', -- drafted, sent, responded, denied, credit_issued
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 15. Credit Memos
CREATE TABLE IF NOT EXISTS credit_memos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dispute_id UUID REFERENCES disputes(id) ON DELETE SET NULL,
    carrier VARCHAR(64) NOT NULL,
    memo_number VARCHAR(64) NOT NULL,
    original_invoice_ref VARCHAR(64) NOT NULL,
    amount_cents INTEGER NOT NULL,
    kind VARCHAR(32) NOT NULL DEFAULT 'credit_memo', -- credit_memo, refund_check
    verification_status VARCHAR(32) NOT NULL DEFAULT 'pending', -- pending, verified, rejected
    detected_via VARCHAR(32) NOT NULL DEFAULT 'stream', -- stream, forwarded, manual
    verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_credit_memos_unique ON credit_memos(carrier, memo_number);

-- 16. Commission Invoices (Our Revenue Trigger: 35% of Verified Memos)
CREATE TABLE IF NOT EXISTS commission_invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    credit_memo_id UUID REFERENCES credit_memos(id) ON DELETE RESTRICT,
    amount_cents INTEGER NOT NULL, -- 35% of memo value (or 40% concierge)
    stripe_invoice_id VARCHAR(128),
    status VARCHAR(32) NOT NULL DEFAULT 'draft', -- draft, sent, paid, overdue, void
    net_terms_due_at DATE NOT NULL, -- Net-15 terms
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 17. Golden Cases (Calibration Benchmark Dataset)
CREATE TABLE IF NOT EXISTS golden_cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    carrier VARCHAR(64) NOT NULL,
    fixture_path TEXT NOT NULL,
    ground_truth_json JSONB NOT NULL,
    planted_errors JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 18. Calibration Runs (CI Scoreboard)
CREATE TABLE IF NOT EXISTS calibration_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    commit_sha VARCHAR(64) NOT NULL,
    golden_set_version VARCHAR(32) NOT NULL,
    precision_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ==============================================================================
-- SEED DATA
-- ==============================================================================

-- Reason codes taxonomy v1 (PRD §5.5, Phase 2.0.4)
INSERT INTO reason_codes (code, description) VALUES
('wrong-matrix-row', 'Extractor or lookup selected the incorrect tariff row/lane'),
('misread-pdf-field', 'OCR or LLM incorrectly extracted a numeric total or identifier'),
('contract-exception-misapplied', 'A contracted tariff exception or rider was misidentified'),
('not-an-error', 'Carrier billed correctly per valid tariff adjustment'),
('duplicate-false-positive', 'Distinct shipments flagged erroneously as duplicates'),
('fsc-table-wrong-month', 'Fuel index applied to incorrect weekly or monthly bracket'),
('rate-effective-date-mismatch', 'Invoice occurred outside contract matrix effective window'),
('other', 'Other manual correction required')
ON CONFLICT (code) DO NOTHING;

-- Top 3 Carrier Contacts (ABF, XPO, Roadrunner)
INSERT INTO carrier_contacts (carrier, dispute_email, billing_phone, notes) VALUES
('ABF Freight', 'freightbilling@abf.com', '800-610-5544', 'Requires PRO# in subject line'),
('XPO Logistics', 'ltlclaims@xpo.com', '800-755-2728', 'Credit memos issued within 10 business days'),
('Roadrunner', 'billingdisputes@rrts.com', '800-435-0777', 'Prefers invoice PDF attached with dispute')
ON CONFLICT (carrier) DO NOTHING;

-- Seed weekly diesel prices (Recent EIA benchmark data)
INSERT INTO eia_diesel_indices (week_date, national_average_price_cents, source_url) VALUES
('2026-08-03', 378, 'https://www.eia.gov/petroleum/gasdiesel/'),
('2026-08-10', 382, 'https://www.eia.gov/petroleum/gasdiesel/'),
('2026-08-17', 385, 'https://www.eia.gov/petroleum/gasdiesel/'),
('2026-08-24', 389, 'https://www.eia.gov/petroleum/gasdiesel/'),
('2026-08-31', 384, 'https://www.eia.gov/petroleum/gasdiesel/'),
('2026-09-07', 381, 'https://www.eia.gov/petroleum/gasdiesel/')
ON CONFLICT (week_date) DO NOTHING;

-- Seed FSC tables for ABF, XPO, Roadrunner
INSERT INTO fsc_tables (carrier, min_diesel_price, max_diesel_price, fsc_pct) VALUES
('ABF Freight', 3.70, 3.749, 32.50),
('ABF Freight', 3.75, 3.799, 33.00),
('ABF Freight', 3.80, 3.849, 33.50),
('ABF Freight', 3.85, 3.899, 34.00),
('XPO Logistics', 3.70, 3.749, 31.80),
('XPO Logistics', 3.75, 3.799, 32.40),
('XPO Logistics', 3.80, 3.849, 33.00),
('XPO Logistics', 3.85, 3.899, 33.60),
('Roadrunner', 3.70, 3.749, 30.50),
('Roadrunner', 3.75, 3.799, 31.00),
('Roadrunner', 3.80, 3.849, 31.50),
('Roadrunner', 3.85, 3.899, 32.00);
