# RateGuard AI — Engineering Memory & Context Handoff
**Document:** `memory.md`  
**Current Milestone:** Phase 1 Complete (Week 1 Ingestion Phase Gate = GO)  
**Target:** Ready for Week 2 (Phase 2.0: Validation Layer, Parsers, Golden Harness)  
**Repository:** `https://github.com/algolyraagency-cloud/invoice-bill-agent`  
**Default Branch:** `main` (Latest commit: `3f3c8a3`)

---

## 1. Executive Context & Product Identity

### 1.1 What We Are Building
**RateGuard AI** is a concierge freight audit and recovery service for mid-market US shippers ($2M–$50M annual freight spend, ~500–10,000 carrier invoices/month).
* **The Pitch:** Shippers lose 3–7% of freight spend to carrier overbilling. We find it and recover it.
* **Pricing Model:** Pure contingency: **35% of recovered dollars** (verified on credit memos, Net-15). Nothing recovered = nothing owed.
* **Core Rule #1:** **LLMs understand, code calculates. Never the reverse.**
  * LLMs extract messy documents into structured JSON schemas.
  * Pure deterministic code runs all mathematical checks, lookups, and validations.
* **Core Rule #2:** **Concierge-First GTM.**
  * We do not build complex self-serve onboarding before Week 6. The software does the reading and math; internal humans do the review; the customer does the dispute sending.
* **Core Rule #3:** **"We draft, customer sends."**
  * RateGuard never acts as a legal party or communicates directly with carriers without the customer in Phase 1.
* **Core Rule #4:** **$200/mo operating ceiling** until first revenue.

---

## 2. Infrastructure & Connected Services

| Service | Configuration & Status | Notes |
| :--- | :--- | :--- |
| **GitHub Repository** | `https://github.com/n3xus1725-oss/ltl-startup` | Authenticated and pushed to `main`. |
| **Supabase Project** | Project Ref: `ojolpdbveutbaxqmaffv`<br>URL: `https://ojolpdbveutbaxqmaffv.supabase.co` | REST API (HTTP 200 OK) & Service Role Key active. |
| **Supabase Postgres** | Host: `aws-0-ap-southeast-2.pooler.supabase.com`<br>Port: `6543` (Supavisor IPv4 pooler)<br>Database: `postgres`<br>User: `postgres.ojolpdbveutbaxqmaffv` | 18 tables created, constraints applied, seed data loaded via Migration 001. |
| **Local Secrets** | Stored in `.env` (Ignored by `.gitignore`) | Template provided in `infra/.env.example`. |

---

## 3. Database Schema (Migration 001 Applied)

All 18 core tables are active in Supabase:
1. `customers`: Shippers organization records (`name`, `slug`, `freight_spend_est`, `recovery_agreement_signed_at`, `status`).
2. `users`: Customer users and internal reviewers (`email`, `role`, `customer_id`).
3. `inbound_emails`: Raw Postmark webhook logs (`sender`, `subject`, `raw_eml_path`, `processed_status`).
4. `invoices`: Canonical invoice records (`customer_id`, `carrier`, `pro_number`, `invoice_number`, `invoice_date`, `invoice_total`, `parsed_json`, `parse_confidence`, `file_path`, `status`).
   * **Dedup Unique Index:** `UNIQUE(customer_id, carrier, invoice_number, pro_number)` — guarantees zero duplicate billing.
5. `contracts`: Carrier rate agreements and addenda (`carrier`, `rung`, `file_path`, `rate_matrix_json`, `contract_validation_json`).
6. `rate_matrices`: Materialized lane matrix rows with **effective date windowing** (`origin_zip_prefix`, `dest_zip_prefix`, `weight_break`, `rate`, `min_charge`, `deficit_weight_eligible`, `effective_date_start`, `effective_date_end`).
7. `fsc_tables`: Carrier fuel surcharge scales supporting weekly EIA diesel price brackets and monthly indices (`min_diesel_price`, `max_diesel_price`, `fsc_pct`).
8. `eia_diesel_indices`: Official weekly DOE on-highway diesel price benchmarks.
9. `audit_runs`: Batch audit execution tracker.
10. `flags`: Audit discrepancies detected (`check_type`, `overcharge_cents`, `evidence_json`, `review_status`, `reject_reason_code`).
11. `disputes`: Pre-drafted dispute packets (`letter_path`, `status`: drafted $\to$ sent $\to$ responded $\to$ credit_issued).
12. `credit_memos`: Carrier issued credit memos matched against disputes (`memo_number`, `original_invoice_ref`, `amount_cents`, `verification_status`).
13. `commission_invoices`: 35% commission invoicing triggered **only** upon verified credit memos (Net-15).
14. `reason_codes`: Standardized review queue rejection taxonomy (seeded with 8 codes).
15. `review_events`: Audit trail and training data feedback loop.
16. `carrier_contacts`: Carrier dispute emails for 1-click mailto card (ABF, XPO, Roadrunner seeded).
17. `golden_cases`: Benchmark fixtures for CI calibration.
18. `calibration_runs`: Precision/recall scoreboard.

---

## 4. Completed Work: Phase-by-Phase Breakdown

### Phase 0: Foundation & Spikes
* **Phase 0.1 (Repo & Infra Bootstrap):** Scaffolding of monorepo (`apps/web`, `apps/api`, `apps/worker`, `packages/schemas`, `packages/audit-engine`, `packages/prompts`), pnpm workspaces, Python test harness, and database migration runner `infra/migrate.py`.
* **Phase 0.2 (Document Pipeline Spike):** Benchmark document in `docs/spikes/document-pipeline.md` selecting **IBM Docling** as primary table/matrix extractor and **PyPDF** as sub-second text fallback.
* **Tier-1 Spikes Completed:**
  * `docs/spikes/supabase.md`: Storage buckets (`invoice-files`, `contract-files`, `eml-raw`, `generated-pdfs`), 15-minute signed URLs, and RLS tenant isolation.
  * `docs/spikes/pg-boss.md`: Native Postgres `SKIP LOCKED` job queue pattern for async workers.
  * `docs/spikes/instructor.md`: Pydantic v2 validation loops and cost-control laddering.

### Phase 1: Ingestion & Storage
* **Phase 1.1 (Channel A: Inbound Email):**
  * `apps/api/src/webhooks/postmark.ts` & `apps/worker/ingestion.py`:
  * Parses Postmark Inbound Webhooks.
  * Recipient slug resolution: extracts `{slug}` from `{slug}@in.rateguard.app`.
  * Carrier dispute CC routing: routes `disputes+{slug}@in.rateguard.app` to dispute tracking.
  * Base64 attachment decoding, magic byte sniffing (`%PDF-`), and `SHA256` deduplication.
  * Saves `.eml` to `eml-raw` and PDF to `invoice-files` in Supabase Storage.
  * Enqueues `parse-invoice` tasks in `pgboss.job`.
  * Customer forwarding setup guide created in `apps/web/public/setup-forwarding.html` (FR-1.4).
* **Phase 1.2 (Channel B: Batch Upload):**
  * `apps/api/src/services/uploader.ts`:
  * Handles 500+ invoices per batch (FR-1.2).
  * Server-side streaming ZIP unpacker with zip-slip directory traversal protection (`../`) and 25MB file limits.
  * CSV manifest parser linking payment exports directly to extracted PDF invoices.
* **Phase 1.3 (Manual Entry Fallback):**
  * `apps/api/src/services/manual_entry.ts` & `apps/worker/manual_entry.py`:
  * Minimal form for stragglers/faxes during concierge onboarding.
  * Guarantees manual invoices enter the exact same pipeline state (`status = 'pending'`, `source = 'manual'`).
  * Enforces duplicate protection.
* **Phase 1.4 (Org Onboarding & Ingestion Phase Gate):**
  * `apps/api/src/services/onboarding.ts` & `apps/worker/onboarding.py`: Customer organization creation (<10 min setup), automated slug provisioning, and primary user registration.
  * `apps/api/src/services/invoice_view.ts`: Paginated multi-tenant invoice list view with signed PDF URLs.
  * `scripts/verify_ingestion_phase_gate.py`: End-to-end integration test executed against Supabase.
  * **Result:** **`PHASE GATE DECISION: GO`** (All 3 channels validated).

### Deterministic Audit Engine Core (`packages/audit-engine/engine.py`)
Pure functions implemented and tested:
1. `check_duplicates`: Hash matching on carrier + PRO# + amount + 30-day window.
2. `check_arithmetic`: Validates $\sum \text{line items} == \text{invoice total}$.
3. `check_rates`: 
   * Selects rate matrix in effect on invoice date (GRI safe).
   * Matches 3-digit Zip prefixes.
   * Applies **Deficit Weight Bumping** (if bumping to higher weight break is cheaper, carrier must bill lower rate).
   * Applies contracted discounts and minimum charge floor.
4. `check_fsc`: Evaluates weekly EIA diesel benchmark price brackets against carrier fuel scales.

---

## 5. Verification Status & Test Suite

All 17 automated unit tests run clean and green (0.27s):
```bash
python -m pytest apps/api/tests/ packages/audit-engine/tests/ -v
```
* `apps/api/tests/test_batch_upload.py` (3/3 tests passed)
* `apps/api/tests/test_manual_and_onboarding.py` (3/3 tests passed)
* `apps/api/tests/test_postmark_webhook.py` (3/3 tests passed)
* `packages/audit-engine/tests/test_audit_engine.py` (8/8 tests passed)

---

## 6. Monorepo File Structure

```text
c:/Users/krish/Downloads/LTL startup/
├── apps/
│   ├── api/
│   │   ├── package.json
│   │   ├── src/
│   │   │   ├── services/
│   │   │   │   ├── invoice_view.ts
│   │   │   │   ├── manual_entry.ts
│   │   │   │   ├── onboarding.ts
│   │   │   │   └── uploader.ts
│   │   │   └── webhooks/
│   │   │       └── postmark.ts
│   │   └── tests/
│   │       ├── test_batch_upload.py
│   │       ├── test_manual_and_onboarding.py
│   │       └── test_postmark_webhook.py
│   ├── web/
│   │   ├── package.json
│   │   └── public/
│   │       └── setup-forwarding.html
│   └── worker/
│       ├── extractor.py
│       ├── ingestion.py
│       ├── manual_entry.py
│       ├── onboarding.py
│       ├── queue_poller.py
│       └── requirements.txt
├── docs/
│   └── spikes/
│       ├── document-pipeline.md
│       ├── instructor.md
│       ├── pg-boss.md
│       └── supabase.md
├── infra/
│   ├── .env.example
│   ├── migrate.py
│   └── migrations/
│       └── 001_initial_schema.sql
├── packages/
│   ├── audit-engine/
│   │   ├── engine.py
│   │   └── tests/
│   │       └── test_audit_engine.py
│   ├── prompts/
│   │   ├── contract_v1.md
│   │   └── invoice_v1.md
│   └── schemas/
│       ├── index.ts
│       ├── models.py
│       └── package.json
├── scripts/
│   └── verify_ingestion_phase_gate.py
├── .env
├── .gitignore
├── IMPLEMENTATION_PLAN.md
├── implementation.md
├── memory.md
├── package.json
├── pnpm-workspace.yaml
└── PRD.md
```

---

## 7. Next Immediate Tasks (Week 2 Roadmap)

When starting a new session, the immediate next step is **Phase 2.0 (Validation Layer, Calibration Harness & Golden Dataset)**:
1. **Phase 2.0.1 (Extraction Self-Validation):** Deterministic re-derivation of line items ($\sum == \text{total}$) before entering the audit engine.
2. **Phase 2.0.2 (Contract Sanity Suite):** Sanity checks on parsed rate matrices (non-monotonic rates, missing FSC months, spot-verification protocol).
3. **Phase 2.0.3 (Calibration Harness & Golden Dataset):** Setup `fixtures/golden/` with human-labeled benchmark invoices and `scripts/calibrate.py` to enforce the $\ge 90\%$ precision / $\ge 80\%$ recall gate before Phase 3.
4. **Phase 2.1 (Invoice Parser):** Docling text extraction + Instructor Pydantic response models for ABF, XPO, and Roadrunner.
5. **Phase 2.2 (Contract Parser):** 20–40 page contract extraction into `RateMatrixJSON`.
6. **Phase 2.3 (FSC Ingestion):** Automated EIA index and carrier scale synchronizer.
