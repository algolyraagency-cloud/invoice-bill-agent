"""
Supabase Database Audit & Verification Script for RateGuard AI
Directly verifies Supabase Postgres instance against implementation.md schema requirements.
"""

import urllib.parse

import psycopg2

RAW_URL = 'postgresql://postgres:99NRU%25$4.YY6-eg@db.ojolpdbveutbaxqmaffv.supabase.co:5432/postgres'

parsed = urllib.parse.urlparse(RAW_URL)
pwd = urllib.parse.unquote(parsed.password)

conn = psycopg2.connect(
    dbname=parsed.path.lstrip('/'),
    user=parsed.username,
    password=pwd,
    host=parsed.hostname,
    port=parsed.port
)
conn.autocommit = True
cur = conn.cursor()

print("======================================================================")
print("1. VERIFYING PUBLIC SCHEMA TABLES IN SUPABASE")
print("======================================================================")

EXPECTED_TABLES = [
    "customers", "users", "inbound_emails", "invoices", "contracts",
    "rate_matrices", "eia_diesel_indices", "fsc_tables", "audit_runs",
    "flags", "disputes", "credit_memos", "commission_invoices",
    "reason_codes", "review_events", "carrier_contacts", "golden_cases",
    "calibration_runs", "onboarding_wizard_state"
]

cur.execute("""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public'
    ORDER BY table_name;
""")
existing_tables = [r[0] for r in cur.fetchall()]

missing_tables = [t for t in EXPECTED_TABLES if t not in existing_tables]
print(f"Total tables found: {len(existing_tables)} / {len(EXPECTED_TABLES)} expected")
if missing_tables:
    print("MISSING TABLES:", missing_tables)
else:
    print("ALL 19 EXPECTED TABLES ARE PRESENT IN SUPABASE!")

print("\n======================================================================")
print("2. VERIFYING DEDUP & PERFORMANCE INDEXES")
print("======================================================================")

EXPECTED_INDEXES = [
    "idx_invoices_dedup",
    "idx_invoices_customer_date",
    "idx_invoices_status",
    "idx_rate_matrices_lookup",
    "idx_fsc_carrier_dates",
    "idx_flags_invoice",
    "idx_flags_review_status",
    "idx_credit_memos_unique",
    "idx_inbound_emails_dedup",
    "idx_credit_memos_dedup"
]

cur.execute("""
    SELECT indexname, indexdef
    FROM pg_indexes
    WHERE schemaname = 'public';
""")
existing_indexes = {r[0]: r[1] for r in cur.fetchall()}

for idx_name in EXPECTED_INDEXES:
    if idx_name in existing_indexes:
        print(f"  [OK] Index '{idx_name}' exists.")
    else:
        print(f"  [MISSING] Index '{idx_name}' missing!")

print("\n======================================================================")
print("3. VERIFYING ROW LEVEL SECURITY (RLS) STATUS & POLICIES")
print("======================================================================")

RLS_TABLES = [
    "customers", "users", "inbound_emails", "invoices", "contracts",
    "rate_matrices", "audit_runs", "flags", "disputes", "credit_memos",
    "commission_invoices", "onboarding_wizard_state"
]

cur.execute("""
    SELECT relname, relrowsecurity
    FROM pg_class
    JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace
    WHERE pg_namespace.nspname = 'public' AND relkind = 'r';
""")
rls_map = {r[0]: r[1] for r in cur.fetchall()}

for t in RLS_TABLES:
    status = rls_map.get(t, False)
    if status:
        print(f"  [OK] RLS Enabled on '{t}'")
    else:
        print(f"  [WARNING] RLS NOT Enabled on '{t}'!")

cur.execute("""
    SELECT tablename, policyname, cmd
    FROM pg_policies
    WHERE schemaname = 'public';
""")
policies = cur.fetchall()
print(f"\nTotal Active RLS Policies: {len(policies)}")
for p in policies:
    print(f"  - Policy '{p[1]}' on table '{p[0]}' (Command: {p[2]})")

print("\n======================================================================")
print("4. VERIFYING SEED DATA IN SUPABASE")
print("======================================================================")

cur.execute("SELECT count(*) FROM reason_codes;")
print(f"  - reason_codes row count: {cur.fetchone()[0]}")

cur.execute("SELECT count(*) FROM carrier_contacts;")
print(f"  - carrier_contacts row count: {cur.fetchone()[0]}")

cur.execute("SELECT count(*) FROM eia_diesel_indices;")
print(f"  - eia_diesel_indices row count: {cur.fetchone()[0]}")

cur.execute("SELECT count(*) FROM fsc_tables;")
print(f"  - fsc_tables row count: {cur.fetchone()[0]}")

conn.close()
print("\nAUDIT COMPLETED CLEANLY.")
