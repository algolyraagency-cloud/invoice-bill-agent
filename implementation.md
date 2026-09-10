# RATEGUARD AI — MVP IMPLEMENTATION PLAN
## Technical implementation blueprint for the engineering builder
**Version 1.0 | Aligned with PRD v2.0 | Approved for Build**

How to use this file: Every phase and subphase is written as a self-contained, buildable unit.  
You can say "build Phase 1.1" to your engineer/AI agent and this section alone is enough to execute.  
Do not skip phases. Do not reorder them. The dependencies are real.

---

## 0. WHAT WE ARE BUILDING — EXACTLY

RateGuard AI is a concierge freight-audit and recovery service with software underneath (PRD §1, §5.8).  
The software does the reading (LLM) and the math (deterministic code); we humans do the judgment (human-in-the-loop review queue); the customer does the sending (dispute letters drafted by us, sent by them).

The MVP build is scoped to the PRD's 3-week concierge clock (PRD §7):

| Week | Build outcome (what must exist) |
| :--- | :--- |
| **W1** | Ingestion pipeline: per-customer inbound email address, PDF attachment capture, drag-and-drop + CSV/ZIP upload, Supabase storage, manual entry fallback. |
| **W2** | Audit engine v1: duplicate detection, rate check, fuel-surcharge (FSC) check. Contract parser for top-3 carriers (ABF, XPO, Roadrunner) → JSON rate matrix. |
| **W3** | Validation layer (Phase 2.0) hardened against golden set, internal review queue UI (3 buttons + reason codes), branded Recovery Report PDF (CFO-readable, bottom-line on page 1), dispute letter generator (PDF + email body), minimum customer portal (Phase 5.5), first real pilot run end-to-end. |
| **W4–5** | Second/third pilots, refinement loop from rejection reason codes + calibration harness, Stripe invoicing for the 35% commission (memo-verified, net-15). |
| **W6–8** | Self-serve onboarding wizard, top-10 carrier formats, automated credit-memo detection (negative-amount invoice scan), automated dispute status tracking. |

### Explicit NON-GOALS for this plan (PRD §5.9 — do not build, do not scope-creep into):
* ERP/TMS API integrations
* Dashboards/analytics
* Freight payment processing
* Carrier-side features
* Multi-user roles & permissions
* EDI 210 ingestion
* Acting as a dispute party / Power-of-Attorney
* Self-serve onboarding before W6
* Any auto-sending of flags to customers before precision ≥ 90% (post-review)

---

## 1. ARCHITECTURE — HOW WE BUILD IT

### 1.1 The core architectural split (PRD §5.4, codified)
**Rule #1 of this codebase: LLMs understand, code calculates. Never the reverse.**

| Layer | Technology | What runs there |
| :--- | :--- | :--- |
| **Understanding layer (LLM)** | LLM API (OpenAI/Anthropic pay-as-you-go) via structured-output client | Parse invoice PDFs → structured JSON; parse rate contracts → rate matrix JSON; parse PODs for delivery dates; fuzzy-match remittance emails to invoices |
| **Deterministic layer (pure Python/TS, zero LLM, zero variance)** | Application code | Duplicate detection (hash), arithmetic validation ($\sum \text{line items} = \text{total}$), FSC table lookup + calculation, rate matrix lookup (lane + weight break → rate) including deficit weight bumping, date logic |
| **Judgment layer (human)** | Internal review queue UI | Approve / Reject / Needs-research; rejection reason codes feed back into parser fixes |

**Why this split is a hard rule:** A $10M-spend shipper generates ~5,000 invoices/yr.  
LLM-parsing 5,000 invoices + 10 contracts ≈ $50–150 in API calls; deterministic math on 5,000 invoices costs $0.  
LLM-ing everything would 10x the cost with zero accuracy gain on the math.

### 1.2 System architecture (event-driven pipeline)

```text
┌─────────────────────────────────────────────────────────────────┐
│ INGESTION                                                       │
│                                                                 │
│ Email forward │ Postmark Inbound (unique addr per customer)     │ Drag & drop
│ (rule @abf.com│ ──► POST /webhooks/email ──► save raw .eml      │ ◄── or CSV/ZIP
│  → @customer.rateguard.app) │               + attachment ──►    │ upload UI
│                             ▼                                   │
│                  jobs queue (pg-boss) ──► Storage (Supabase)    │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ UNDERSTANDING (LLM, async workers)                              │
│ Docling/pypdf text extraction ──► Instructor + Pydantic          │
│ schema ──► InvoiceJSON { carrier, pro#, charges[], dates }       │
│ Contract PDF ──► RateMatrixJSON { lanes, weight breaks,          │
│ FSC table, accessorials, exceptions } + confidence scores        │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ DETERMINISTIC AUDIT ENGINE (pure code)                          │
│ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌───────────┐      │
│ │  Check 1   │ │  Check 2   │ │  Check 3   │ │  Checks   │      │
│ │ Duplicates │ │ Rate check │ │ FSC check  │ │ 4-8 later │      │
│ └─────┬──────┘ └─────┬──────┘ └─────┬──────┘ └─────┬─────┘      │
└───────┼──────────────┼──────────────┼──────────────┼────────────┘
        ▼              ▼              ▼              ▼
┌─────────────────────────────────────────────────────────────────┐
│ HUMAN REVIEW QUEUE (internal UI)                                │
│ Flag card: invoice ref, check type, $ amount, evidence          │
│ links [✔ Approve] [✘ Reject ▾ reason code] [? Research]         │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼ (only Approved flags)
┌─────────────────────────────────────────────────────────────────┐
│ CUSTOMER-FACING OUTPUT                                          │
│ Recovery Report PDF ──► "Found Money" call ──► Dispute          │
│ letter generator (PDF + email body, from the shipper)           │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ RECOVERY TRACKING + BILLING                                     │
│ Credit-memo detection (negative-amount invoice scan +           │
│ forwarded memos) ──► verification (memo#, invoice ref, $)       │
│ ──► Stripe invoice: 35% of verified memo value, net-15          │
└─────────────────────────────────────────────────────────────────┘
```

### 1.3 Service layout (one monorepo, three deployables)

We run 1 GitHub repo (monorepo) with 3 logical deployables.  
**Rationale:** The team is 1–2 engineers, the payload is small, and the pipeline pieces share types/schemas heavily. Splitting into 3 repos now would be premature optimization; the seams below are clean enough to split later if headcount demands it.

```text
rateguard-ai/
├── apps/
│   ├── web/           # Next.js 15 (App Router) — customer portal + internal review queue
│   ├── api/           # Next.js API routes / Hono — REST endpoints, webhooks
│   └── worker/        # Node/Python async job runner — parsing, audit, report generation
├── packages/
│   ├── schemas/       # Pydantic/zod shared types: InvoiceJSON, RateMatrixJSON, Flag, CreditMemo
│   ├── audit-engine/  # THE deterministic core — pure functions, unit-tested, no LLM, no I/O
│   └── prompts/       # Versioned LLM prompts + Pydantic extraction schemas
├── infra/             # Supabase migrations, Vercel config, env templates
└── docs/              # Carrier format notes, runbook
```

**Language choice:** TypeScript everywhere (Next.js) EXCEPT the worker's document pipeline, which is **Python** — because the best PDF/LLM tooling (Docling, pypdf, Instructor, PaddleOCR) is Python-native.  
The two runtimes talk through the shared schemas package (Pydantic models in Python, mirrored zod schemas in TS, validated against the same JSON fixtures).

---

## 2. TECH STACK — WHAT EXACTLY WE USE

| Concern | Choice | Why / cost |
| :--- | :--- | :--- |
| **Frontend + API** | Next.js 15 (App Router) + TypeScript, on Vercel hobby | $0; one framework for portal + review queue + API routes |
| **DB, auth, storage** | Supabase (Postgres + Auth + Storage) | $0 free tier (500MB DB / 2GB storage — thousands of PDFs); row-level security for per-customer isolation |
| **Job queue** | `pg-boss` on Supabase Postgres (`SKIP LOCKED` pattern — zero new infra; the Python worker polls the same `pgboss.job` table directly) | Async parse/audit jobs, retries, dead-letter. **NOTE: BullMQ was rejected** — it requires Redis blocking commands (`BRPOPLPUSH`) that Upstash serverless Redis does not support. Revisit BullMQ only if we self-host Redis later |
| **Worker runtime** | Python 3.12 worker on Railway (~$5/mo) or Modal free tier — always a hosted process, never a laptop cron | PDF + LLM tooling is Python-native; pilots fail if the pipeline dies when a laptop closes |
| **Document text extraction** | Docling (IBM, ds4sd/docling) primary; pypdf fallback for text PDFs; Tesseract/PaddleOCR only for scanned invoices | Layout-aware PDF→markdown+tables; free, local, no per-page API cost |
| **LLM structured extraction** | Instructor (jxnl/instructor) + Pydantic v2 over OpenAI/Anthropic | Forces validated JSON against schemas — this is the 90%-precision backbone |
| **OCR (scanned PDFs only)** | PaddleOCR or Tesseract 5 | Only ~5–10% of carrier invoices are scans; don't OCR what has a text layer |
| **Inbound email** | Postmark inbound stream | $15/mo for 5,000 emails; unique inbound address per customer (`{customer-slug}@in.rateguard.app`); parses to JSON webhook with attachments |
| **Outbound email (dispute letters, notifications)** | Postmark transactional | Same $15 plan |
| **PDF generation (report + letters)** | React-PDF (diegomura/react-pdf) or Puppeteer HTML→PDF | Branded Recovery Report + dispute letters from the same component |
| **Billing** | Stripe Invoicing | Commission invoicing, net-15 terms; fees only when we bill |
| **LLM API** | OpenAI gpt-4o-mini / gpt-4o or Anthropic claude-haiku/sonnet | Pay-as-you-go; budget ceiling $200/mo total (PRD §9) |
| **Testing** | Vitest (TS) + pytest (Python) + golden-fixture harness | Every parser change re-runs against fixture PDFs; precision is measured, not assumed |

**Total running cost until first revenue: ~$100–150/mo (PRD §9 ceiling: $200).**

---

## 3. GITHUB REPOS TO RESEARCH BEFORE BUILDING

The builder should read/study these (not fork blindly — understand the integration surface):

### Tier 1 — core dependencies (read docs + source before Phase 1)
1. `ds4sd/docling` — https://github.com/DS4SD/docling — layout-aware PDF→structured markdown/tables. Our document front-end. Study: table extraction (rate contracts are 20–40 pages of tables), custom pipelines.
2. `jxnl/instructor` — https://github.com/jxnl/instructor — structured LLM outputs on Pydantic. Study: response_model pattern, retry/validation hooks, mode selection per LLM provider.
3. `supabase/supabase` + `supabase/supabase-js` — DB, storage buckets, RLS policies. Study: storage signed URLs for invoice PDFs, RLS for multi-tenant isolation.
4. `timgit/pg-boss` — https://github.com/timgit/pg-boss — Postgres job queue on `SKIP LOCKED`; our queue. Study: retry/backoff config, dead-letter queues, the `pgboss.job` table schema (the Python worker claims jobs from it with `SELECT ... FOR UPDATE SKIP LOCKED`). *(BullMQ was considered and rejected: it needs Redis blocking commands unsupported by serverless Redis.)*
5. `postmarkapp` inbound docs (not a repo — developer.postmarkapp.com) — inbound webhook JSON shape, attachment handling, wildcard inbound addresses (`*@in.rateguard.app`).

### Tier 2 — patterns and reference implementations
6. `invoice-x/invoice2data` — https://github.com/invoice-x/invoice2data — YAML-template regex invoice extraction. Study as prior art, do not adopt. Its weakness (per-layout templates, brittle on new formats) is exactly why we use LLM extraction; its value to us is the template-per-carrier fallback concept for the top-10 formats in Phase 2.
7. `vercel/nextjs-subscription-payments` — https://github.com/vercel/nextjs-subscription-payments — Supabase + Stripe wiring reference for Phase 2 billing (adapt: we invoice commissions, not subscriptions, but the auth/Stripe skeleton transfers).
8. `diegomura/react-pdf` — PDF generation from React components (report + letters).
9. `mindee/doctr` or `PaddlePaddle/PaddleOCR` — OCR options for scanned invoices (Phase 1.3 decision point; benchmark on 10 real scanned invoices, pick one, don't build both).
10. `unstructured-io/unstructured` — alternative to Docling; benchmark Docling vs unstructured on 20 real carrier invoices + 2 real rate contracts before committing (Phase 1.4 spike).

### Tier 3 — deterministic-engine references (read for check-logic patterns)
11. `tesseract-ocr/tesseract` — OCR fallback.
12. `sbdchd/croniter` or `node-cron` — monthly reason-code review job (light).
13. `zod` — TS-side schema mirror of the Pydantic models.

**Research deliverable:** a 1-page spike note per Tier-1 repo before Phase 1.1 starts: integration surface, license, risk.

---

## 4. DATA MODEL (Supabase Postgres — migration 001)

### Core tables (concierge MVP; minimal but correct):

* **customers:** `id`, `name`, `slug` (→ inbound email local part), `industry`, `freight_spend_est`, `status`, `created_at`
* **users:** `id`, `customer_id`, `email`, `role` (`owner` | `ap_clerk` | `internal_reviewer`), `supabase_auth_id`
* **inbound_emails:** `id`, `customer_id`, `sender`, `subject`, `raw_eml_path`, `received_at`, `processed_status`
* **invoices:** `id`, `customer_id`, `source` (`email` | `upload` | `manual`), `carrier`, `pro_number`, `invoice_number`, `invoice_date`, `invoice_total`, `parsed_json` (`InvoiceJSON`), `parse_confidence`, `file_path`, `status`
* **contracts:** `id`, `customer_id`, `carrier`, `rung` (`A` | `B` | `C`), `file_path`, `rate_matrix_json`, `parse_confidence`, `effective_date`, `parsed_at`
* **rate_matrices:** materialized from `contracts` — `id`, `contract_id`, `carrier`, `origin_zip_prefix` (3-digit or 5-digit prefix/wildcard matching), `dest_zip_prefix`, `weight_break`, `rate`, `min_charge`, `deficit_weight_eligible` (boolean flag for bumping), `effective_date_start`, `effective_date_end` (**CRITICAL:** carriers issue annual GRIs and mid-year amendments — a matrix row must only apply to invoices within its effective window, or every January invoice audited against July rates becomes a false flag. Multiple versions per contract are normal: keep them all, keyed by effective date).
* **fsc_tables:** `id`, `carrier`, `effective_week_start`, `effective_week_end`, `month`, `min_diesel_price`, `max_diesel_price`, `fsc_pct` (seeded weekly EIA diesel price index + carrier bracket scale support)
* **eia_diesel_indices:** `id`, `week_date`, `national_average_price_cents`, `source_url`, `created_at`
* **audit_runs:** `id`, `customer_id`, `scope` (invoice range), `started_at`, `completed_at`, `stats_json`
* **flags:** `id`, `audit_run_id`, `invoice_id`, `check_type` (`DUP` | `RATE` | `FSC` | `ACCESSORIAL` | `REWEIGH` | `GUARANTEE` | `ARITH` | `TAX`), `overcharge_cents`, `confidence`, `evidence_json` (invoice ref + contract clause/page, billed value vs correct value), `review_status` (`pending` | `approved` | `rejected` | `research`), `reject_reason_code`, `reviewed_by`, `reviewed_at`
* **disputes:** `id`, `flag_id`, `letter_path`, `sent_by`, `sent_at`, `status` (`drafted` | `sent` | `responded` | `denied` | `credit_issued`)
* **credit_memos:** `id`, `dispute_id`, `carrier`, `memo_number`, `original_invoice_ref`, `amount_cents`, `kind` (`credit_memo` | `refund_check` — PRD edge case: some carriers cut checks for large amounts; same billing trigger), `verification_status` (`pending` | `verified` | `rejected`), `detected_via` (`stream` | `forwarded` | `manual`)
* **commission_invoices:** `id`, `customer_id`, `credit_memo_id`, `amount_cents` (35%), `stripe_invoice_id`, `status`, `net_terms_due_at`
* **reason_codes:** `code`, `description`, `first_seen`, `count` (fed by review queue; drives parser fixes)
* **review_events:** `id`, `flag_id`, `action`, `reason_code`, `reviewer`, `created_at` (audit trail + training data)
* **carrier_contacts:** `id`, `carrier`, `dispute_email`, `billing_phone`, `notes` (populated during concierge onboarding — the customer knows their carrier rep's billing-dispute address; the one-click mailto card in Phase 5.2 reads from here. Without this table the mailto button has nowhere to send.)
* **golden_cases:** `id`, `carrier`, `fixture_path`, `ground_truth_json`, `planted_errors[]` (labeled benchmark set)
* **calibration_runs:** `id`, `commit_sha`, `golden_set_version`, `precision_json` per check/carrier, `created_at` (CI scoreboard)

### Storage buckets:
* `invoice-files` (raw PDFs)
* `contract-files` (raw PDFs/agreements)
* `eml-raw` (raw incoming emails)
* `generated-pdfs` (reports + letters)

*Every generated artifact is stored — evidence links in flags point at exact pages.*

### Dedup constraint (migration 001):
`unique index on invoices(customer_id, carrier, invoice_number, pro_number)` — ingestion channels (email / upload / manual) can collide, and the DB is the last line of defense against double-billing ourselves into duplicate flags.

---

## 5. THE DETERMINISTIC AUDIT ENGINE (packages/audit-engine) — module contracts

Pure functions. Input: `InvoiceJSON` + `RateMatrixJSON` + `FSCTable`. Output: `Flag[]`.  
**No LLM, no network, no clock (dates injected) — fully unit-testable.**

```python
def check_duplicates(invoice: InvoiceJSON, all_invoices: list[InvoiceJSON]) -> list[Flag]:
    """Hash: carrier + pro# + amount + ±3-day window; also bol# match."""
    pass

def check_rates(invoice: InvoiceJSON, rate_matrix_versions: list[RateMatrixJSON]) -> list[Flag]:
    """
    1. Select the matrix VERSION in effect on invoice.invoice_date (never assume latest — GRI/amendment safe).
    2. Resolve lane by longest matching origin/dest zip prefix (5-digit first, then 3-digit).
    3. Apply in order: FAK mapping → weight break → deficit-weight bumping (if bumping to the next break is cheaper than the billed weight's rate, the carrier must bill the lower bumped rate) → discount % (Rung C: published tariff × (1 − claimed_discount)) → min-charge floor.
    4. Billed charge ≠ computed charge → Flag with both values.
    """
    pass

def check_fsc(invoice: InvoiceJSON, fsc_table: FSCTable, eia_index: EIAIndex = None) -> list[Flag]:
    """
    Billed FSC% ≠ table(effective_date/week); FSC base ≠ net freight.
    Verifies DOE weekly average price bracket lookup against carrier schedule.
    """
    pass

def check_arithmetic(invoice: InvoiceJSON) -> list[Flag]:
    """Σ line items ≠ invoice total."""
    pass

def check_accessorials(invoice: InvoiceJSON, rate_matrix: RateMatrixJSON) -> list[Flag]:
    """Billed accessorial not in contract schedule or billed at rate exceeding contract ceiling."""
    pass

def check_reweigh(invoice: InvoiceJSON) -> list[Flag]:
    """Billed class/weight vs NMFC rules (Phase 2)."""
    pass

def check_guarantee(invoice: InvoiceJSON, pod_date: str) -> list[Flag]:
    """Promised vs actual delivery (Phase 2)."""
    pass

def check_tax(invoice: InvoiceJSON, customer_state: str) -> list[Flag]:
    """Tax errors where applicable (Phase 2)."""
    pass
```

MVP v1 ships **checks 1–3 + arithmetic** (≈70% of recoverable dollars per PRD §7); each flag carries:
```json
evidence_json = {
  "invoice_ref": "INV-2847",
  "carrier": "ABF",
  "contract_clause": "Item 220-A (Fuel Surcharge Index)",
  "page_number": 7,
  "billed_value": 42.0,
  "correct_value": 38.0,
  "overcharge_cents": 1650
}
```
This is what the review queue and dispute letters consume.

---

## 6. BUILD PLAN — PHASES & SUBPHASES

### PHASE 0 — FOUNDATION & RESEARCH SPIKES (Day 1–2)

#### Phase 0.1 — Repo + infra bootstrap
* Create monorepo (structure in §1.3), pnpm workspaces, Python worker venv, CI (GitHub Actions: lint, typecheck, tests).
* Supabase project: run migration 001 (§4), create storage buckets, seed `fsc_tables` and `eia_diesel_indices` for current quarter for ABF/XPO/Roadrunner.
* Vercel deploy of empty Next.js app; env template (`infra/.env.example`).
* **Acceptance:** `pnpm dev` boots web+api; `pytest` runs in `packages/audit-engine`; empty app deploys.

#### Phase 0.2 — Document-pipeline spike (BLOCKING for Phase 1 — do not skip)
* Benchmark Docling vs unstructured on 20 real carrier invoice PDFs + 2 real 20–40-page rate contracts.
* Measure: table extraction fidelity on rate matrices; per-document latency; failure modes on messy scans.
* Decide OCR path for scans: PaddleOCR vs Tesseract, benchmark on 10 scanned invoices.
* **Deliverable:** `docs/spikes/document-pipeline.md` with the decision + numbers.  
* **Acceptance:** chosen pipeline extracts ≥95% of table cells correctly on the benchmark contracts.

---

### PHASE 1 — INGESTION & STORAGE (Week 1) (PRD FR-1.1, FR-1.2, FR-1.4)

#### Phase 1.1 — Per-customer inbound email (Channel A, the main artery)
* Postmark inbound stream with wildcard address `*@in.rateguard.app`; webhook `POST /api/webhooks/postmark-inbound`.
* Parse Postmark JSON: From, To (local part → customer via subdomain/slug), body, attachments.
* Save raw `.eml` + attachments to Supabase Storage (`eml-raw`, `invoice-files`); enqueue BullMQ / pg-boss job `parse-invoice`.
* Dedup on `(customer, attachment hash)` so a re-forwarded email never double-ingests.
* Customer-facing forwarding-rule setup instructions page (static, per-carrier copy-paste steps) — FR-1.4.
* Dedicated dispute CC address: `disputes+{customer_slug}@in.rateguard.app` for carrier response tracking.
* **Acceptance:** email PDF'd from a test gmail to `{slug}@in.rateguard.app` lands in storage + DB within 60s; re-forward creates no duplicate.

#### Phase 1.2 — Upload UI: drag-and-drop, CSV manifest, ZIP of PDFs (Channel B + fallback)
* Upload page: multi-file dropzone (PDF/CSV/ZIP), 500+ file batch without error (FR-1.2), progress + per-file status.
* ZIP: server-side unpack; CSV: parse manifest (invoice #, carrier, amount) → creates invoices rows pre-linked to PDFs.
* Virus/size guards; file type sniffing (reject non-PDFs politely).
* **Acceptance:** 500-PDF ZIP uploads end-to-end in <10 min wall clock with zero lost files.

#### Phase 1.3 — Manual entry fallback
* Minimal form: carrier, pro#, invoice #, date, total, line items. Used for stragglers/faxes during concierge onboarding.
* **Acceptance:** manual invoice enters the same pipeline state as an emailed one.

#### Phase 1.4 — Storage, org & onboarding record (FR-1.1)
* Customer record + inbound slug provisioning (<10 min onboarding), remit-to capture.
* Invoice list view per customer: source, carrier, status, parse confidence.
* **Phase gate:** full ingestion works for one real pilot customer before any audit code merges. Go/no-go review.

---

### PHASE 2 — UNDERSTANDING: INVOICE & CONTRACT PARSERS (Week 2, first half)

#### Phase 2.0 — VALIDATION LAYER: cross-checks, calibration & confidence (THE trust backbone — build before any audit output is shown to a human)
The PRD's entire offer is a number a CFO trusts ("$187,340 recoverable") plus a ≥90% precision guarantee. Neither is possible without verifying two things on every invoice before it reaches the audit engine:
(a) the extraction is right and (b) the contract rate we will judge it against is right.  
This phase is the difference between a demo and a product.

##### Phase 2.0.1 — Extraction self-validation (deterministic re-derivation, no LLM in the loop)
* After the LLM returns `InvoiceJSON`, the worker re-derives every arithmetic field from the extracted line items in pure code: $\sum \text{line items} == \text{invoice total}$, $\text{net} + \text{FSC} + \text{accessorials} == \text{total}$, $\text{billed\_weight} \times \text{rate} \approx \text{line amount}$ (tolerance ±$0.01–0.50 per carrier rounding rule).
* Mismatch → `parse_confidence` dropped and the invoice routed to a calibration queue (lightweight internal screen: extracted fields shown next to the raw PDF page; one-click confirm/fix). Never silently pass a non-reconciling invoice into audits.
* Field-level confidence from the LLM + reconciliation result → composite `parse_confidence` per invoice, stored and shown in the review queue.

##### Phase 2.0.2 — Contract sanity suite (run on every parsed RateMatrixJSON, before it can power audits)
* Deterministic checks: duplicate lane rows; overlapping weight breaks; rates that are non-monotonic (cheaper at higher weight breaks); FSC table missing months in scope; min-charge > any lane rate; currency/rounding anomalies.
* Spot-verification protocol: for each new contract, the reviewer opens N=5 random lanes and compares matrix value vs. contract PDF page image (side-by-side in the UI). All 5 must match exactly, else the whole matrix is sent back for re-parse. This is the contract-side analogue of the review queue and exists because a wrong matrix poisons every downstream flag.
* Output: `contract_validation_json` attached to the contract record (checks passed, spot-verification result, reviewer id).

##### Phase 2.0.3 — Calibration harness & golden dataset (the precision engine)
* `fixtures/golden/`: 100+ real invoices across the top-3 carriers, human-labeled with ground truth (correct totals, correct charges, known-planted errors: wrong FSC month, duplicate, wrong weight break, arithmetic drift).
* `scripts/calibrate.py`: runs the full pipeline (parse → validate → audit) against the golden set and prints precision/recall per check type and per carrier. This is the scoreboard for the 90% → 95% → 98% trajectory (PRD §10) — without it, "precision" is a vibe.
* **Gate before Phase 3 merges:** on the golden set, the pipeline must hit ≥90% precision / ≥80% recall on checks 1–3. Below that, fix prompts/parsers — do not proceed to real customer data.
* The same harness reruns on every parser/prompt change in CI (regression guard) and on every new carrier format before that format is enabled for customers.

##### Phase 2.0.4 — Reason-code taxonomy v1 (seeded before the first review)
* Seed `reason_codes` with the full taxonomy: `wrong-matrix-row` | `misread-pdf-field` | `contract-exception-misapplied` | `not-an-error` | `duplicate-false-positive` | `fsc-table-wrong-month` | `rate-effective-date-mismatch` | `other`.
* Wire the review queue's rejection dropdown to this table from day one — retroactively tagging rejections is fiction; nobody does it.

**Why this phase is non-negotiable:** The review queue (Phase 4) catches bad flags, but it cannot catch a systematically wrong rate matrix or a parser that misreads totals — every flag would be confidently wrong, the reviewer would approve them (they look right), and the CFO would receive a wrong number. Validation is what makes the review queue meaningful instead of ceremonial.

* **Acceptance:** every invoice carries `parse_confidence`; every contract carries `contract_validation_json`; `calibrate.py` runs in CI and reports per-check precision; the ≥90%/≥80% gate is green on the golden set before Phase 3 begins.

#### Phase 2.1 — Invoice parser (LLM + Instructor → InvoiceJSON)
* Worker: Docling extraction → prompt (`packages/prompts/invoice_v1.md`) → Instructor `response_model=InvoiceJSON` → DB.
* `InvoiceJSON` schema: carrier, pro_number, invoice_number, invoice_date, ship_from/to (parsed to 3-digit and 5-digit lane keys), line_items[{description, charge_code, amount}], accessorials[{type, amount}], billed_weight, billed_class, fsc_amount, fsc_pct, total, raw_text_hash.
* Per-carrier format hints for ABF/XPO/Roadrunner (top-3) as system-prompt context; generic prompt for others.
* Golden-fixture harness: 30+ real invoices across carriers committed as fixtures; parser must hit field-level accuracy targets before merge (pro# 100%, totals ≥99%, line items ≥97%).
* **Acceptance:** run 500 invoices < 15 min total pipeline time (FR-2.3); failures → `status=parse_failed` queue, never silent drops.

#### Phase 2.2 — Contract parser → RateMatrixJSON (THE hard one)
* Input: PDF per Quality Ladder rung (PRD §5.3): Rung A clean agreement; Rung B email-chain digests; Rung C published tariff + claimed discount note.
* Output `RateMatrixJSON`: carrier, effective dates, lanes[{origin_geo, origin_zip_prefix, dest_geo, dest_zip_prefix, transit_days}], weight_breaks[], rates, min_charge, FSC terms (base, table source, diesel peg scale), accessorial schedule, discount %, FAK mappings, exceptions[], confidence per section.
* Human spot-check step on first parse of each contract (reviewer confirms matrix before it can be used in audits) — this is the contract-side analogue of the review queue.
* **Acceptance:** top-3 carrier formats parse to a usable matrix with ≤2 reviewer corrections per contract.

#### Phase 2.3 — FSC table ingestion
* Seed weekly EIA diesel prices and monthly/weekly carrier FSC % brackets per carrier; effective-dated lookups only.
* **Acceptance:** `get_fsc(carrier, shipment_date)` returns exactly one verified value for any invoice date in scope.

---

### PHASE 3 — AUDIT ENGINE v1 (Week 2, second half) (FR-2.1, FR-2.3)

#### Phase 3.1 — Audit engine core (packages/audit-engine)
* Implement `check_duplicates`, `check_rates` (including deficit weight bumping & 3-digit zip matching), `check_fsc` (including EIA diesel pegging), `check_arithmetic` per §5 contracts.
* Audit run orchestration: batch job over a customer's invoice range; `audit_runs` row tracks scope/stats.
* Flags written with full `evidence_json` (invoice ref, contract clause + page, billed vs correct value).
* Unit tests: 100% line coverage on the four checks with synthetic fixtures incl. known-error invoices (wrong FSC month/week, dup with ±2-day skew, rate on wrong weight break, non-bumped deficit weight, arithmetic drift).
* **Acceptance:** `pytest packages/audit-engine` green; engine flags every seeded error and zero false flags on clean invoices at the code level (precision measured again after human review in Phase 4).

#### Phase 3.2 — Pipeline wiring (worker end-to-end)
* `parse-invoice` job → `run-audit-for-invoice` job (per invoice, on arrival) + `run-audit-batch` (for 6-month backfills).
* Failure handling: dead-letter queue + Slack/email alert to internal channel; audit idempotency keys (re-run safe).
* **Acceptance:** 6-month backfill (≈2,500 invoices) processes unattended; every invoice ends in a terminal status.

#### Phase 3.3 — LLM cost guard (enforces the PRD §9 budget ceiling)
* **Parse cache:** LLM results keyed by `sha256(file content + prompt version)` — a re-forwarded or re-uploaded document never re-bills an LLM call.
* **Per-job token caps and model ladder:** cheap model first (`gpt-4o-mini` / `claude-haiku`); escalate to the flagship only on validation failure or low field confidence.
* **Monthly circuit breaker:** a counter of LLM spend (estimated from usage metadata) halts parsing and alerts when projected month spend crosses a configurable threshold (default $150 of the $200 ceiling, leaving headroom for Postmark/Stripe/etc.).
* **Acceptance:** cache hit returns identical JSON; breaker test fires in staging at $0.01 threshold.

---

### PHASE 4 — HUMAN REVIEW QUEUE (Week 3, first half) (PRD §5.5 — where the 90% guarantee lives)

#### Phase 4.1 — Internal review UI
* Route `/internal/review` (role-gated to `internal_reviewer`).
* Flag card: invoice ref, carrier, check type, $ overcharge, evidence links ([invoice PDF] [contract p.N]), side-by-side billed vs. correct.
* Three actions: Approve (→ report), Reject (▾ mandatory reason code — the SAME taxonomy seeded in Phase 2.0.4: `wrong-matrix-row` | `misread-pdf-field` | `contract-exception-misapplied` | `not-an-error` | `duplicate-false-positive` | `fsc-table-wrong-month` | `rate-effective-date-mismatch` | `other`), Needs research (→ manual contract dig list; research resolution must return the flag to the queue with a note — nothing may die in 'research').
* Target: ≤30 seconds per flag; a 500-invoice pilot (~50 flags) = ~25 min of review.
* **Acceptance:** review throughput measured; every rejection writes `reason_codes` + `review_events`.

#### Phase 4.2 — Reason-code feedback loop
* Monthly job: top reason codes → parser/prompt fix tickets; precision dashboard query (`approved / (approved+rejected)` per check type, per month).
* Target trajectory: ≥90% → 95% → 98% (PRD §10).
* **Acceptance:** precision report queryable per carrier, per check type; first reason-code retro held after pilot 1.

---

### PHASE 5 — RECOVERY REPORT & DISPUTE LETTERS (Week 3, second half) (FR-3.1, FR-3.2)

#### Phase 5.1 — Recovery Report PDF generator
* React-PDF template, branded per customer: bottom-line $recoverable on page 1 (FR-3.1), breakdown by error type and by carrier, per-claim evidence appendix (invoice excerpt + contract clause).
* Route: internal "generate report" from approved flags → stored in `generated-pdfs` → download link.
* **Acceptance:** a CFO can read it in <5 min (test with a real finance person on pilot 1).

#### Phase 5.2 — Dispute letter generator ("we draft, they send" — PRD §5.6)
* Per-flag letter: PDF + email body, addressed from the shipper, citing the shipper's contract clause, stating billed vs correct amount, requesting credit memo referencing original invoice #.
* One-click generate-all per carrier batch (one letter per carrier dispute packet is fine).
* Tracking state machine: `drafted` → `sent` → `responded` → `credit_issued` | `denied`.
* **One-Click mailto: & Copy-Paste Dispute Card:** Provides a button opening the user's default email client with the carrier's dispute address (from `carrier_contacts`, captured at onboarding — if missing, prompt the customer to fill it), CC to `disputes+{customer_slug}@in.rateguard.app`, subject line, and formatted body, plus a 1-click clipboard copy button.
* Explicit guardrail: system never sends to carriers directly (no carrier email credentials configured in system; letters only export/open via shipper).
* **Acceptance:** letter needs <1 click of edits to send (FR-3.2).

#### Phase 5.5 — CUSTOMER PORTAL (minimum lovable surface)
The PRD's Flow A/B has the customer doing real work: uploading contracts, tracking disputes, forwarding credit memos, downloading reports. A supply-chain manager will not run this over email and a shared drive — they need one URL. This is the minimum portal that makes the service usable and trustworthy, and it doubles as the concierge's working surface.

##### Phase 5.5.1 — Customer auth & dashboard skeleton
* Supabase Auth (email magic link — no passwords for MVP); role-gated routes (`customer` vs `internal_reviewer`).
* Dashboard: onboarding checklist (forwarding rule status → contracts uploaded → first invoices in → report ready), total $ recoverable to date, open disputes count, latest credit memos.

##### Phase 5.5.2 — Documents & contracts
* Invoice list per customer: carrier, date, amount, audit status, flag count; PDF viewer.
* Contract upload UI with Quality Ladder rung detection (ask the PRD's mandatory pre-pilot question in-product: "Do you have a signed rate agreement?" → route A/B/C intake accordingly); show `contract_validation_json` status.

##### Phase 5.5.3 — Disputes & credit memos
* Dispute tracker: per-dispute status (`drafted` → `sent` → `responded` → `credit_issued` | `denied`), the generated letter PDF, one-click `mailto:` launch card, and a "forward the carrier's reply here" flow — customer pastes/forwards the credit memo email to their inbound address; the memo-detection pipeline (Phase 6.1) picks it up.
* Recovery Report download link (the artifact from Phase 5.1).
* **Acceptance:** pilot customer can complete the entire PRD Flow A without a phone call: upload contract → confirm forwarding → watch invoices appear → receive report → download letters → forward a credit memo → see it verified. The concierge team uses the same portal internally (dogfooding rule).

#### Phase 5.4 — Recovery agreement (1-page, signed before any dispute is sent)
PRD Flow A gates letters on a signed 1-page recovery agreement — without it we have no contractual right to the 35%. This was missing from the plan and is a launch blocker for Pilot 1.
* Generate the agreement from a template: parties, contingency fee (35%, or 40% concierge-handled), memo-basis billing trigger + net-15, "we draft, you send" dispute mechanism, data-handling clause (ties to §7A).
* E-signature via typed full name + checkbox + timestamp (MVP — no DocuSign cost); PDF stored in `generated-pdfs`, status on the customer record.
* Hard gate enforced in code: dispute letters for a customer cannot be generated/exported until `recovery_agreement_signed_at` is set.
* **Acceptance:** pilot 1 signs in the portal; attempting to export letters before signing returns a clear blocking message.

#### Phase 5.3 — Pilot 1 run — THE WEEK-3 GATE (PRD §7)
* Real pilot end-to-end: onboarding → forwarding rule live <10 min → 6-month backfill → audit → human review → Found-Money call with report → recovery agreement signed → letters handed over.
* **Acceptance:** the report call happens. This is the whole point of the 3-week clock.

---

### PHASE 6 — RECOVERY TRACKING & COMMISSION BILLING (Week 4–5)

#### Phase 6.1 — Credit-memo detection & verification
* Stream scan: newly ingested invoices with negative totals or "CREDIT MEMO" patterns → `credit_memos` candidates; plus customer-forwarded memo inbox flow.
* Verification: match memo (number, original invoice ref, amount, carrier) against disputes; `verification_status=verified` is the ONLY thing that can trigger billing.
* **Acceptance:** zero commission invoices without a verified memo (revenue integrity KPI = 100%).

#### Phase 6.2 — Stripe commission invoicing
* 35% of verified memo value, billed as a monthly aggregate per customer (PRD Flow A: "we invoice 35%, net-15 → monthly commission") — one Stripe invoice per customer per month covering all memos verified that month, net-15 terms; concierge-handled disputes bill at 40% of their memo value.
* Denied disputes: one automated evidence-stronger resend task; if still denied → `unrecoverable`, priced into the 35% (no extra action).
* **Acceptance:** first commission invoice sent and trackable in Stripe.

---

### PHASE 7 — SELF-SERVE & SCALE (Week 6–8)

#### Phase 7.1 — Self-serve onboarding wizard
* Company → users → remit-to → carriers → contract upload (with Rung detection hint) → forwarding-rule instructions → first invoices flowing. Replaces concierge hand-holding; same pipeline underneath.

#### Phase 7.2 — Top-10 carrier formats
* Extend parser hints + fixtures to top-10 LTL formats; invoice2data-style regex fallback layer for ultra-stable fields (pro#, totals) as cost/robustness guard.

#### Phase 7.3 — Remaining checks 5–8
* Accessorials, reweigh/dimension, guaranteed-service (needs POD date parsing), tax — each behind the same flag/review machinery, rolled out per reason-code data.

#### Phase 7.4 — Dispute status tracking automation
* Reminder nudges for sent > 14 days; denial-rate-per-carrier report (watch for carrier-specific hostility, PRD §11).

---

## 7A. SECURITY, COMPLIANCE & AUDIT TRAIL (cross-cutting — applies from Phase 1 onward)

We store customers' financial documents, contracts, and bank-adjacent data (remit-to). One breach or one lost dispute letter is company-ending for a trust business. This is not a Phase-7 concern; it's built in from the first migration.

| Area | Requirement |
| :--- | :--- |
| **Tenant isolation** | Postgres RLS on every table: `customer_id` claim from the JWT; internal reviewer role is a separate claim with explicit grants. Verified by an automated test that attempts cross-tenant reads on every table. |
| **Encryption** | TLS in transit everywhere; Supabase storage-level encryption at rest; no customer documents in any log line (CI check greps logs for pro-number patterns). |
| **Access control** | Internal review queue and `/internal/*` routes gated by role claim; all actions logged to `review_events` (who/what/when) — this is also the training-data audit trail. |
| **Data retention** | Per-customer retention config (default: raw files kept for the engagement + 90 days); hard-delete on request; deletion job tested. |
| **PII minimization** | We store shipper/consignee names only as needed for audit evidence; no employee PII beyond user accounts. |
| **Backups** | Supabase PITR (or daily dumps) — tested restore once before Pilot 1. |
| **Vendor posture** | Signed DPAs with OpenAI/Anthropic (zero-retention API tier — no customer documents used for model training); Postmark and Supabase on paid tiers with DPAs before first real customer. |
| **Credit-memo integrity** | Commission invoices only from `verification_status=verified` memos (Phase 6.1) — this is both a revenue rule and a fraud control. |

---

## 7. OPERATING DISCIPLINE (non-negotiable)

1. **Precision before speed:** flags never reach a customer un-reviewed in concierge mode. The 90% guarantee is a product feature, not a hope.
2. **Reason codes are the roadmap:** every rejection must have one; the monthly reason-code retro decides what gets fixed next.
3. **Evidence or it didn't happen:** every flag, letter, and commission carries document references. This is a trust business.
4. **The $200/mo ceiling:** any change that adds infra cost needs a cost note. LLM calls stay in the understanding layer only.
5. **Weekly demo against the 3-week clock:** W1 ingestion, W2 audit engine, W3 first pilot delivered. Slipping a week is a conversation, not a silent slide.
6. **No number without validation:** an invoice that fails arithmetic reconciliation, or a contract that fails the sanity suite + spot-verification, can never produce customer-visible flags. The calibration gate (≥90% precision / ≥80% recall on golden) must be green before any real-customer audit output ships.
7. **Non-goals stay non-goals:** if a customer asks for ERP integrations, dashboards, or EDI — it goes on the Phase 2+ list, never into the current sprint (PRD §5.9, §11 scope-creep risk).
