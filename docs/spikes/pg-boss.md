# pg-boss Queue Architecture Spike (Tier-1 Dependency)

## 1. Why pg-boss Over BullMQ / Redis
* **Serverless Redis Failure Mode:** BullMQ relies heavily on Redis blocking commands (`BRPOPLPUSH`, `BLMOVE`). Serverless Redis providers like Upstash do not reliably support persistent blocking connections on their free tier, leading to dropped jobs and socket terminations.
* **Zero Infrastructure Cost ($0):** `pg-boss` runs directly inside our existing Supabase PostgreSQL instance using PostgreSQL's native `FOR UPDATE SKIP LOCKED` concurrency control pattern.
* **Transactional Reliability:** Enqueuing jobs can participate in database transactions (e.g. saving an invoice and queueing its parse job atomically).

## 2. Queue Lifecycle & Pipeline Jobs

The RateGuard AI pipeline defines three primary job types:
1. `parse-invoice`: Ingests an invoice file path, runs text extraction and LLM structured parsing, and writes `InvoiceJSON`.
2. `run-audit-for-invoice`: Triggered immediately upon successful invoice parsing to run deterministic audit checks (Checks 1–4).
3. `run-audit-batch`: Runs retrospective batch audits across an entire date range (e.g. 6-month historical onboarding backfills).

## 3. Node.js Producer Setup (`apps/api` or Next.js Route)
```typescript
import PgBoss from 'pg-boss';

const boss = new PgBoss(process.env.DATABASE_URL!);

export async function initQueue() {
  await boss.start();
}

export async function enqueueInvoiceParse(invoiceId: string, customerId: string, filePath: string) {
  return await boss.send('parse-invoice', {
    invoiceId,
    customerId,
    filePath
  }, {
    retryLimit: 3,
    retryDelay: 30, // seconds
    expireInSeconds: 300
  });
}
```

## 4. Python Worker Consumer Pattern
Because our document extraction pipeline is written in Python (for Docling and Pydantic/Instructor), the Python worker consumes jobs directly from the `pgboss.job` table without needing Node.js wrappers:

```sql
-- Worker atomic job claim query
UPDATE pgboss.job
SET state = 'active', startedon = now()
WHERE id = (
  SELECT id FROM pgboss.job
  WHERE name = 'parse-invoice' AND state = 'created'
  ORDER BY priority DESC, createdon ASC
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
RETURNING id, data;
```

```python
# Worker completion query
def complete_job(cur, job_id, output_data):
    cur.execute("""
        UPDATE pgboss.job 
        SET state = 'completed', completedon = now(), output = %s 
        WHERE id = %s
    """, (json.dumps(output_data), job_id))
```

## 5. Dead-Letter & Failure Alerting
* Failed jobs automatically transition to `state = 'failed'` after exceeding `retryLimit`.
* An automated query flags persistent errors and notifies internal engineers via Slack webhook.
