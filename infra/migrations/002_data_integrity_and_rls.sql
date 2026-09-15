-- ==============================================================================
-- Migration 002: Data Integrity Fixes, Idempotency Constraints & Postgres RLS
-- Phase B & Phase C Security Hardening for RateGuard AI Multi-Tenant Core
-- ==============================================================================

-- 1. Onboarding Wizard State Persistence Table
CREATE TABLE IF NOT EXISTS onboarding_wizard_state (
    customer_id UUID PRIMARY KEY REFERENCES customers(id) ON DELETE CASCADE,
    current_step INTEGER NOT NULL DEFAULT 1,
    completed_steps JSONB NOT NULL DEFAULT '[]',
    carrier_selections JSONB NOT NULL DEFAULT '[]',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Add customer_id to disputes and credit_memos if not present
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='disputes' AND column_name='customer_id') THEN
        ALTER TABLE disputes ADD COLUMN customer_id UUID REFERENCES customers(id) ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='credit_memos' AND column_name='customer_id') THEN
        ALTER TABLE credit_memos ADD COLUMN customer_id UUID REFERENCES customers(id) ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='inbound_emails' AND column_name='attachment_hash') THEN
        ALTER TABLE inbound_emails ADD COLUMN attachment_hash VARCHAR(64);
    END IF;
END $$;

-- 3. Idempotency Unique Indexes (DB-Level Duplicate Prevention)
CREATE UNIQUE INDEX IF NOT EXISTS idx_inbound_emails_dedup 
ON inbound_emails(customer_id, attachment_hash) 
WHERE attachment_hash IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_credit_memos_dedup 
ON credit_memos(customer_id, carrier, memo_number);

-- 4. Enable Row Level Security (RLS) across all customer-scoped tables
ALTER TABLE customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE inbound_emails ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE contracts ENABLE ROW LEVEL SECURITY;
ALTER TABLE rate_matrices ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE flags ENABLE ROW LEVEL SECURITY;
ALTER TABLE disputes ENABLE ROW LEVEL SECURITY;
ALTER TABLE credit_memos ENABLE ROW LEVEL SECURITY;
ALTER TABLE commission_invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE onboarding_wizard_state ENABLE ROW LEVEL SECURITY;

-- 5. Multi-Tenant RLS Isolation Policies
-- Evaluates against app.current_customer_id setting or service role bypass

DROP POLICY IF EXISTS tenant_isolation_customers ON customers;
CREATE POLICY tenant_isolation_customers ON customers
    FOR ALL
    USING (
        id = NULLIF(current_setting('app.current_customer_id', true), '')::uuid
        OR current_setting('role', true) = 'service_role'
        OR current_setting('app.current_customer_id', true) IS NULL
    );

DROP POLICY IF EXISTS tenant_isolation_invoices ON invoices;
CREATE POLICY tenant_isolation_invoices ON invoices
    FOR ALL
    USING (
        customer_id = NULLIF(current_setting('app.current_customer_id', true), '')::uuid
        OR current_setting('role', true) = 'service_role'
        OR current_setting('app.current_customer_id', true) IS NULL
    );

DROP POLICY IF EXISTS tenant_isolation_contracts ON contracts;
CREATE POLICY tenant_isolation_contracts ON contracts
    FOR ALL
    USING (
        customer_id = NULLIF(current_setting('app.current_customer_id', true), '')::uuid
        OR current_setting('role', true) = 'service_role'
        OR current_setting('app.current_customer_id', true) IS NULL
    );

DROP POLICY IF EXISTS tenant_isolation_disputes ON disputes;
CREATE POLICY tenant_isolation_disputes ON disputes
    FOR ALL
    USING (
        customer_id = NULLIF(current_setting('app.current_customer_id', true), '')::uuid
        OR current_setting('role', true) = 'service_role'
        OR current_setting('app.current_customer_id', true) IS NULL
    );

DROP POLICY IF EXISTS tenant_isolation_credit_memos ON credit_memos;
CREATE POLICY tenant_isolation_credit_memos ON credit_memos
    FOR ALL
    USING (
        customer_id = NULLIF(current_setting('app.current_customer_id', true), '')::uuid
        OR current_setting('role', true) = 'service_role'
        OR current_setting('app.current_customer_id', true) IS NULL
    );

DROP POLICY IF EXISTS tenant_isolation_commission_invoices ON commission_invoices;
CREATE POLICY tenant_isolation_commission_invoices ON commission_invoices
    FOR ALL
    USING (
        customer_id = NULLIF(current_setting('app.current_customer_id', true), '')::uuid
        OR current_setting('role', true) = 'service_role'
        OR current_setting('app.current_customer_id', true) IS NULL
    );

DROP POLICY IF EXISTS tenant_isolation_inbound_emails ON inbound_emails;
CREATE POLICY tenant_isolation_inbound_emails ON inbound_emails
    FOR ALL
    USING (
        customer_id = NULLIF(current_setting('app.current_customer_id', true), '')::uuid
        OR current_setting('role', true) = 'service_role'
        OR current_setting('app.current_customer_id', true) IS NULL
    );

DROP POLICY IF EXISTS tenant_isolation_audit_runs ON audit_runs;
CREATE POLICY tenant_isolation_audit_runs ON audit_runs
    FOR ALL
    USING (
        customer_id = NULLIF(current_setting('app.current_customer_id', true), '')::uuid
        OR current_setting('role', true) = 'service_role'
        OR current_setting('app.current_customer_id', true) IS NULL
    );

DROP POLICY IF EXISTS tenant_isolation_users ON users;
CREATE POLICY tenant_isolation_users ON users
    FOR ALL
    USING (
        customer_id = NULLIF(current_setting('app.current_customer_id', true), '')::uuid
        OR current_setting('role', true) = 'service_role'
        OR current_setting('app.current_customer_id', true) IS NULL
    );

DROP POLICY IF EXISTS tenant_isolation_onboarding_wizard_state ON onboarding_wizard_state;
CREATE POLICY tenant_isolation_onboarding_wizard_state ON onboarding_wizard_state
    FOR ALL
    USING (
        customer_id = NULLIF(current_setting('app.current_customer_id', true), '')::uuid
        OR current_setting('role', true) = 'service_role'
        OR current_setting('app.current_customer_id', true) IS NULL
    );
