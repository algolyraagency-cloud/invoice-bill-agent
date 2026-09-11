# RateGuard AI — Engineering Memory & Context Handoff
**Document:** `memory.md`  
**Current Milestone:** Phase 5.1 & 5.2 Complete (Branded Recovery Report PDF & Dispute Letter Generator = GO)  
**Target:** Ready for Phase 5.4 (1-Page Recovery Agreement Gate) & Phase 5.5 (Minimum Customer Portal)  
**Repository:** `https://github.com/algolyraagency-cloud/invoice-bill-agent.git`  
**Default Branch:** `main`

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
* **Core Rule #3:** **"We draft, customer sends. Always."**
  * RateGuard never acts as a direct legal party or sends emails to carriers on behalf of shippers without them in Phase 1 (PRD §5.6).
* **Core Rule #4:** **$200/mo operating ceiling** until first revenue ($150/mo LLM cap).

---

## 2. Infrastructure & Connected Services

| Service | Configuration & Status | Notes |
| :--- | :--- | :--- |
| **GitHub Repository** | `https://github.com/algolyraagency-cloud/invoice-bill-agent.git` | Authenticated and pushed to `main`. |
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
11. `disputes`: Pre-drafted dispute packets (`letter_path`, `status`: `drafted` $\to$ `sent` $\to$ `responded` $\to$ `credit_issued` \| `denied`).
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

### Phase 2: Parsers, Validation Layer & Calibration Harness
* **Phase 2.0 (Validation Layer & Quality Gates):**
  * Built dual-runtime schema contracts: Pydantic v2 (`packages/schemas/models.py`) and TypeScript Zod (`packages/schemas/index.ts`).
  * Arithmetic reconciliation ($\sum \text{line items} == \text{total}$) with $\$0.05$ rounding tolerance.
  * Automated rejection taxonomy: 8 standardized codes with exact parser mapping.
  * Golden Dataset benchmark and calibration harness (`scripts/calibrate.py`) validating precision and recall.
* **Phase 2.1 (Invoice Parser):**
  * `apps/worker/invoice_parser.py`: Robust extraction pipeline with prompt instructions (`packages/prompts/invoice_v1.md`), fallback regex, and confidence scoring.
* **Phase 2.2 (Contract Parser & Rate Matrix Ingestion):**
  * `apps/worker/contract_parser.py`: Multi-page contract and addenda parser. Rung detection (Rung A/B/C) with automatic lane rate matrix materialization.
* **Phase 2.3 (FSC Engine & EIA Fuel Index Sync):**
  * `packages/audit-engine/fsc.py` & `apps/worker/fsc_ingestion.py`: Weekly DOE diesel benchmark integration, carrier bracket interpolation, and net-freight FSC calculation.

### Phase 3: Audit Engine Core, Pipeline Wiring & LLM Cost Guard
* **Phase 3.1 (Audit Engine Core & Batch Orchestrator):**
  * `packages/audit-engine/engine.py`: Enhanced with BOL duplicate matching, ±3-day identical amount window, chronological directionality, deficit weight rating ("As" weight bumping), 5-digit vs 3-digit prefix matching, AMC floor, contract discount, and net freight FSC base calculation.
  * Standardized `evidence_json` citing exact carrier tariff clauses, document page numbers, and itemized overcharge cents.
  * `packages/audit-engine/orchestrator.py`: Single-invoice audit (`audit_invoice`) and customer historical backfill batch runner (`audit_batch`), aggregating comprehensive `AuditRunStats` (clean vs flagged breakdown, category distribution, latency).
* **Phase 3.2 (Pipeline Wiring & Worker Handlers):**
  * `apps/worker/pipeline.py`: Event-driven queue handlers (`parse-invoice`, `run-audit-for-invoice`, `run-audit-batch`).
  * Audit idempotency keys (`{invoice_id}:{check_type}`) preventing duplicate flags on re-audits.
  * Dead-Letter Queue (`DeadLetterQueue`) capturing job exceptions, alerting internal team, and updating invoice status to `error`.
  * Guarantees all invoices end in canonical terminal statuses: `audited`, `parse_failed`, or `error`.
* **Phase 3.3 (LLM Cost Guard & Circuit Breaker):**
  * `apps/worker/cost_guard.py`: Enforces PRD §9 $200/mo operating ceiling ($150/mo LLM cap).
  * SHA-256 parse cache: Returns identical extraction results with $0.00 spend on re-scans.
  * Model ladder: Cheap models (`gpt-4o-mini`) by default; escalates to flagship models (`gpt-4o`) only on validation failure.
  * Monthly circuit breaker: Trips at configured threshold, dispatches alert callback, and raises `CircuitBreakerTrippedError` to halt external API spend.

### Phase 4: Internal Review UI & Reason-Code Feedback Loop
* **Phase 4.1 (Internal Review UI & Review Queue Service):**
  * `apps/worker/review_queue.py` & `apps/api/src/services/review_queue.ts`:
  * Flag lifecycle state machine (`pending` $\to$ `approved` \| `rejected` \| `research` $\to$ `resolved`).
  * Role gating: Strictly verifies `internal_reviewer` role claim before any review action executes.
  * Rejection Taxonomy: Strictly enforces 8-code taxonomy, incrementing `reason_codes.count`.
  * Zero-Death Research Queue: Allows placing flags into `research` with mandatory notes.
  * Audit Trail: Logs every action (`approve`, `reject`, `research`, `resolve_research`) with reviewer ID, timestamp, notes, and duration to `review_events`.
  * Review UI at `public/internal/review.html`: Flag cards with side-by-side billed vs. contracted comparisons, overcharge callouts, evidence citations, signed PDF links, and hotkeys (`A`, `R`, `S`).
* **Phase 4.2 (Reason-Code Feedback Loop & Precision Engine):**
  * `apps/worker/feedback_loop.py` & `apps/api/src/services/feedback_loop.ts`:
  * Computes post-review human precision (Approved / (Approved + Rejected)) overall, per carrier, and per check type.
  * Quality Gate Trajectory Benchmarking (PRD §10): Evaluates metrics against the three-tier quality ladder (≥90.0% Pilot, ≥95.0% Scale, ≥98.0% Enterprise).
  * Automated Fix Ticket Generator: Maps top rejection failure modes into prioritized engineering tickets.
  * Monthly Retrospective Job (`run_monthly_retro`): Compiles structured `MonthlyRetroReport` and exports markdown summaries.
  * UI Tab: Added **"📈 Precision & Feedback"** tab in review dashboard.

### Phase 5: Customer-Facing Output & Dispute Generation
* **Phase 5.1 (Branded Recovery Report PDF Generator - COMPLETE):**
  * `apps/worker/report_generator.py` & `apps/api/src/services/recovery_report.ts`:
  * Core Rule & FR-3.1 Compliance: Bottom-line recoverable amount prominent on Page 1, readable by a CFO in <5 minutes.
  * Full financial accounting: Gross recoverable amount, estimated shipper net recovery (65%), and RateGuard contingency fee (35%).
  * Itemized breakdown by carrier (ABF Freight, XPO Logistics, Roadrunner) and check category (RATE, FSC, DUP, ARITH).
  * Native sub-second vector PDF generation via `pymupdf` (fitz) with zero headless browser or heavy binary dependencies.
  * Standalone printable HTML report generator (`render_report_html`) with print-optimized CSS and page breaks.
  * Review Workspace UI: Integrated **"📄 Recovery Report"** tab with 1-click **"🖨️ Print / Save PDF"** and **"📋 Copy Summary"**.
* **Phase 5.2 (Dispute Letter Generator: "We Draft, Shipper Sends" - COMPLETE):**
  * `apps/worker/dispute_generator.py` & `apps/api/src/services/dispute_service.ts`:
  * Strict PRD §5.6 & Core Rule #3 Enforcement: RateGuard never communicates directly with carriers. Every letter is addressed from the shipper's AP department.
  * Pre-drafted dispute notice cites exact carrier tariff rules (`Item 100-D`, `Item 220-A`), billed vs correct amounts, and requests credit memo within 30 days.
  * 1-Click `mailto:` generator with RFC 2368 pre-encoded link: recipient carrier dispute desk (`freightbilling@abf.com`, `ltlclaims@xpo.com`, `billingdisputes@rrts.com`), CC to `disputes+{customer_slug}@in.rateguard.app`, subject line, and formatted body.
  * Carrier batch consolidator (`generate_carrier_dispute_batch`) packaging multiple approved invoices per carrier into a unified dispute packet.
  * Dispute lifecycle state machine: `drafted` $\to$ `sent` $\to$ `responded` $\to$ `credit_issued` \| `denied`.
  * Shipper Letterhead vector PDF generator (`render_dispute_pdf`) via `pymupdf`.
  * Review Workspace UI: Integrated **"✉️ Dispute Letters"** tab with carrier packet cards, 1-click mailto launch, clipboard copy buttons, and status transition selector.

---

## 5. Verification Status & Test Suite

All **90 automated unit and integration tests** run clean and green (0.67s):
```bash
pytest
```
* `apps/api/tests/test_batch_upload.py` (3/3 tests passed)
* `apps/api/tests/test_manual_and_onboarding.py` (3/3 tests passed)
* `apps/api/tests/test_postmark_webhook.py` (3/3 tests passed)
* `packages/audit-engine/tests/test_audit_engine.py` (17/17 tests passed)
* `packages/audit-engine/tests/test_validation.py` (12/12 tests passed)
* `packages/audit-engine/tests/test_orchestrator.py` (5/5 tests passed)
* `packages/audit-engine/tests/test_fsc.py` (7/7 tests passed)
* `apps/worker/tests/test_pipeline.py` (5/5 tests passed)
* `apps/worker/tests/test_cost_guard.py` (4/4 tests passed)
* `apps/worker/tests/test_review_queue.py` (7/7 tests passed)
* `apps/worker/tests/test_feedback_loop.py` (5/5 tests passed)
* `apps/worker/tests/test_contract_parser.py` (5/5 tests passed)
* `apps/worker/tests/test_invoice_parser.py` (5/5 tests passed)
* `apps/worker/tests/test_report_generator.py` (4/4 tests passed)
* `apps/worker/tests/test_dispute_generator.py` (5/5 tests passed)

### Quality Gate Calibration Scoreboard (`scripts/calibrate.py`):
```text
================================================================================
RATEGUARD AI — CALIBRATION HARNESS SCOREBOARD (PHASE 2.0.3)
Commit SHA: 13272278 | Total Invoices Audited: 14
================================================================================
CHECK TYPE      | TP   | FP   | FN   | TN   | PRECISION  | RECALL     | F1    
--------------------------------------------------------------------------------
DUP             | 2    | 0    | 0    | 12   |    100.0% |    100.0% | 100.0
RATE            | 2    | 0    | 0    | 12   |    100.0% |    100.0% | 100.0
FSC             | 3    | 0    | 0    | 11   |    100.0% |    100.0% | 100.0
ARITH           | 2    | 0    | 0    | 12   |    100.0% |    100.0% | 100.0
--------------------------------------------------------------------------------

CARRIER         | TP   | FP   | FN   | TN   | PRECISION  | RECALL     | F1    
--------------------------------------------------------------------------------
ABF Freight     | 4    | 0    | 0    | 20   |    100.0% |    100.0% | 100.0
Roadrunner      | 2    | 0    | 0    | 10   |    100.0% |    100.0% | 100.0
XPO Logistics   | 3    | 0    | 0    | 17   |    100.0% |    100.0% | 100.0
================================================================================
OVERALL ACCURACY: Precision: 100.0% (Gate >= 90%) | Recall: 100.0% (Gate >= 80%)
DECISION: GATE PASSED [GO FOR PHASE 5]
```

---

## 6. Monorepo File Structure

```text
c:/Users/krish/Downloads/LTL startup/
├── apps/
│   ├── api/
│   │   ├── package.json
│   │   ├── src/
│   │   │   ├── services/
│   │   │   │   ├── dispute_service.ts
│   │   │   │   ├── feedback_loop.ts
│   │   │   │   ├── invoice_view.ts
│   │   │   │   ├── manual_entry.ts
│   │   │   │   ├── onboarding.ts
│   │   │   │   ├── recovery_report.ts
│   │   │   │   ├── review_queue.ts
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
│       ├── contract_parser.py
│       ├── cost_guard.py
│       ├── dispute_generator.py
│       ├── extractor.py
│       ├── feedback_loop.py
│       ├── fsc_ingestion.py
│       ├── ingestion.py
│       ├── invoice_parser.py
│       ├── manual_entry.py
│       ├── onboarding.py
│       ├── pipeline.py
│       ├── queue_poller.py
│       ├── report_generator.py
│       ├── requirements.txt
│       ├── review_queue.py
│       └── tests/
│           ├── test_contract_parser.py
│           ├── test_cost_guard.py
│           ├── test_dispute_generator.py
│           ├── test_feedback_loop.py
│           ├── test_fsc.py
│           ├── test_invoice_parser.py
│           ├── test_pipeline.py
│           ├── test_report_generator.py
│           └── test_review_queue.py
├── docs/
│   └── spikes/
│       ├── document-pipeline.md
│       ├── instructor.md
│       ├── pg-boss.md
│       └── supabase.md
├── fixtures/
│   └── golden/
│       ├── abf_freight.json
│       ├── latest_run.json
│       ├── roadrunner.json
│       └── xpo_logistics.json
├── infra/
│   ├── .env.example
│   ├── migrate.py
│   └── migrations/
│       └── 001_initial_schema.sql
├── packages/
│   ├── audit-engine/
│   │   ├── engine.py
│   │   ├── fsc.py
│   │   ├── orchestrator.py
│   │   ├── validation.py
│   │   └── tests/
│   │       ├── test_audit_engine.py
│   │       ├── test_fsc.py
│   │       ├── test_orchestrator.py
│   │       └── test_validation.py
│   ├── prompts/
│   │   ├── contract_v1.md
│   │   └── invoice_v1.md
│   └── schemas/
│       ├── index.ts
│       ├── models.py
│       └── package.json
├── public/
│   ├── index.html
│   └── internal/
│       └── review.html
├── scripts/
│   ├── calibrate.py
│   └── verify_ingestion_phase_gate.py
├── .env
├── .gitignore
├── IMPLEMENTATION_PLAN.md
├── implementation.md
├── memory.md
├── package.json
├── pnpm-workspace.yaml
├── PRD.md
├── pytest.ini
├── README.md
└── vercel.json
```

---

## 7. Next Immediate Tasks (Week 3 Roadmap)

1. **Phase 5.4 — 1-Page Recovery Agreement Gate (Launch Blocker for Pilot 1):**
   * PRD Flow A requirement: letters are gated on a signed 1-page contingency contract (35% contingency fee, Net-15 terms, "we draft, you send" dispute mechanism, zero direct carrier representation).
   * E-signature in portal (typed name + checkbox + timestamp); generates legal agreement vector PDF into `generated-pdfs`.
   * Hard code gate: Attempting to export or generate dispute letters before `recovery_agreement_signed_at` is set returns a strict blocking error.
2. **Phase 5.5 — Minimum Customer Portal:**
   * Customer magic link auth, contract upload UI with Quality Ladder rung detection (Rung A/B/C), invoice status list with signed PDF viewer, dispute tracking board, and Recovery Report download center.
3. **Phase 5.3 — Pilot 1 Run (The Week-3 Gate):**
   * Run live end-to-end audit for first real pilot customer: onboarding $\to$ forwarding rule $\to$ backfill $\to$ review queue $\to$ Found-Money call with Recovery Report PDF $\to$ signed agreement $\to$ dispute letters handed over.
