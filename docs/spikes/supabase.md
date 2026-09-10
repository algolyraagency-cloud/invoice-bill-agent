# Supabase Integration Spike (Tier-1 Dependency)

## 1. Overview & Architecture Surface
Supabase serves as the primary database (PostgreSQL 17), authentication provider, and object storage engine for RateGuard AI. 
To honor the strict **$200/mo operating ceiling**, we utilize the Supabase Free Tier ($0/mo for up to 500MB database, 2GB object storage, and 50,000 monthly active users).

## 2. Integration Surface

### 2.1 Storage Buckets
Four distinct storage buckets are defined with explicit security boundaries:
* `invoice-files`: Raw ingested carrier invoice PDFs (private, authenticated read via signed URLs).
* `contract-files`: Signed customer carrier contracts and rate addenda (private, authenticated read via signed URLs).
* `eml-raw`: Unprocessed inbound `.eml` email files from Postmark (internal ops only).
* `generated-pdfs`: Outbound CFO "Found Money" reports and dispute letter PDFs (private, signed download URLs generated on demand).

### 2.2 Signed URLs
To prevent unauthorized access to sensitive financial documents without proxying heavy file streams through application servers:
```typescript
import { createClient } from '@supabase/supabase-js';

const supabase = createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!);

// Generate 15-minute temporary secure access link
export async function getSignedInvoiceUrl(filePath: string): Promise<string> {
  const { data, error } = await supabase.storage
    .from('invoice-files')
    .createSignedUrl(filePath, 900); // 15 minutes
  if (error) throw error;
  return data.signedUrl;
}
```

### 2.3 Row-Level Security (RLS) Multi-Tenant Isolation
Every application table enforces Postgres Row-Level Security (RLS). 
Tenancy is strictly partitioned using the customer's UUID extracted from the verified JWT claim:
```sql
ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;

-- Customer users can only view their own organization's invoices
CREATE POLICY tenant_isolation_invoices ON invoices
  FOR ALL
  USING (
    customer_id = (auth.jwt() -> 'app_metadata' ->> 'customer_id')::uuid
    OR (auth.jwt() -> 'app_metadata' ->> 'role') = 'internal_reviewer'
  );
```

## 3. Runtimes & Connection Modes
* **Next.js Web / API:** Uses `@supabase/supabase-js` (REST / PostgREST) with anon key for customer sessions and service-role key for internal jobs and ingestion webhooks.
* **Python Async Worker:** Connects to PostgreSQL directly via connection pooler or executing parameterized queries through `psycopg2` / `asyncpg`.

## 4. Risks & Mitigations
* **Risk:** IPv6-only routing timeouts on certain client networks when connecting directly to port 5432.
* **Mitigation:** Fall back to the Supavisor IPv4 pooler (`aws-0-ap-southeast-2.pooler.supabase.com:6543`) or Supabase PostgREST API endpoints.
