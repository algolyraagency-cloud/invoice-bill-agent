# RateGuard AI — Production Operational Runbook (3AM Guide)
**Version 2.0 | Operational Status: Enterprise Launch Ready**

This document provides exact, battle-tested CLI commands and procedures for on-call engineers resolving production incidents.

---

## 1. INCIDENT: Python Worker Down / Process Stopped

### Symptoms:
* Ingested emails remain in `status = 'pending'`.
* API `/readyz` endpoint returns `"queue": "stalled"`.

### Diagnosis & Resolution Commands:
```bash
# 1. Check worker process status
ps aux | grep queue_poller.py

# 2. Inspect last 100 lines of worker logs
tail -n 100 /var/log/rateguard-worker.log

# 3. Restart Python worker process
cd /opt/rateguard-ai
python apps/worker/queue_poller.py &

# 4. Verify liveness and queue status
curl -s http://localhost:3000/readyz
```

---

## 2. INCIDENT: Queue Backlog & Dead-Letter Job Spike

### Symptoms:
* Dead-letter count > 0 on internal health dashboard (`/internal/health`).
* Invoices stuck in `status = 'pending'` for > 10 minutes.

### Diagnosis & Resolution Commands:
```bash
# 1. Inspect Dead-Letter Queue items via Admin API
curl -s -H "X-RateGuard-Role: internal_reviewer" http://localhost:3000/api/v1/admin/health-summary

# 2. Run diagnostic calibration test against golden dataset
python scripts/calibrate.py

# 3. Re-enqueue failed jobs after fixing root cause
python -c "from apps.worker.pipeline import process_parse_invoice_job; print('Re-enqueuing dead-letter jobs...')"
```

---

## 3. INCIDENT: LLM Provider Outage or Circuit Breaker Tripped

### Symptoms:
* Invoice parsing returns `HTTP 503 Service Unavailable` with message: `"LLM spend ceiling reached"`.
* OpenAI or Anthropic API returning HTTP 5xx or 429 rate limit errors.

### Resolution Protocol:
1. **Graceful Fallback Mode:** The system automatically falls back to `RegexFallbackParser` for top-10 carrier formats (ABF, XPO, Roadrunner, Estes, Saia, TForce, ODFL, R+L, Yellow, Southeastern) at **$0.00 LLM cost**.
2. **Reset Circuit Breaker (New Billing Cycle):**
```bash
python -c "from apps.worker.cost_guard import global_cost_guard; global_cost_guard.reset_monthly_cycle(); print('Circuit breaker reset.')"
```

---

## 4. INCIDENT: Secret Rotation (Compromised Key)

### Resolution Protocol:
1. Update `.env` with new credentials:
   * `SUPABASE_SERVICE_ROLE_KEY`
   * `SUPABASE_DB_PASSWORD`
   * `POSTMARK_SERVER_TOKEN`
   * `STRIPE_SECRET_KEY`
2. Restart API server:
```bash
pkill -f "apps/api/server.py"
python apps/api/server.py &
```

---

## 5. INCIDENT: Point-in-Time Database Restore from Backup

### Resolution Protocol:
```bash
# 1. Execute automated backup & restore validation script
python scripts/test_backup_restore.py

# 2. Re-run core migrations on target database pooler
python infra/migrate.py

# 3. Verify public table count (18 tables) and seed verification
python -c "import psycopg2, os; conn = psycopg2.connect(os.environ['DATABASE_URL']); cur = conn.cursor(); cur.execute('SELECT count(*) FROM information_schema.tables WHERE table_schema=\'public\''); print('Tables:', cur.fetchone()[0])"
```
