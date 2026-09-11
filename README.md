# RateGuard AI — Freight Audit & Recovery MVP

> **Mid-market freight audit and recovery concierge engine.**  
> Shippers lose 3–7% of freight spend to carrier overbilling. We detect it, verify it mathematically, and generate dispute recovery packets. Pure contingency: **35% of recovered dollars** (verified on carrier credit memos, Net-15 terms).

---

## 1. Core Operating Principles

1. **Rule #1: LLMs understand, code calculates. Never the reverse.**
   - LLMs extract messy PDFs and emails into structured JSON schemas.
   - Deterministic, unit-tested code performs all mathematical checks, tariff rate lookups, deficit weight ratings, and fuel surcharge lookups. Zero LLM variance on math.
2. **Rule #2: The $200/mo Operating Ceiling.**
   - Total runtime costs are capped at $\le \$200/\text{mo}$ until first revenue ($150 LLM cap, $50 platform headroom).
   - Enforced by SHA-256 parse caching ($0 on re-scans), model ladders (cheap models first), and automated monthly circuit breakers.
3. **Rule #3: Precision Before Speed ($\ge 90\%$ Precision Gate).**
   - No unverified flags reach customers. Every release is gated against human-labeled golden datasets (`scripts/calibrate.py`).
4. **Rule #4: "We draft, shipper sends."**
   - RateGuard never acts as a third party or holds power-of-attorney in concierge MVP. The customer sends the dispute packet.

---

## 2. Architecture & Monorepo Layout

One monorepo containing three logical deployables:

```text
invoice-bill-agent/
├── apps/
│   ├── api/             # Next.js / Node API routes & Postmark email webhooks
│   ├── web/             # Next.js 15 App Router — customer portal & review queue
│   └── worker/          # Python async worker — layout extraction, parsers, pipeline & cost guard
│       ├── extractor.py        # Multi-engine PDF layout extractor (Docling -> pdfplumber -> PyMuPDF)
│       ├── invoice_parser.py   # Instructor structured output extraction + self-validation
│       ├── contract_parser.py  # Quality Ladder Rungs A/B/C rate agreement parser
│       ├── fsc_ingestion.py    # Carrier scale synchronizer & baseline scale seeder
│       ├── cost_guard.py       # LLM spend tracker, model ladder & circuit breaker
│       └── pipeline.py         # End-to-end async job runner & dead-letter queue
├── packages/
│   ├── audit-engine/    # THE deterministic core (pure functions, zero LLM, 100% testable)
│   │   ├── engine.py           # Duplicate, rate, FSC, and arithmetic checks
│   │   ├── fsc.py              # Monday EIA diesel benchmark resolver & bracket scales
│   │   ├── validation.py       # Extraction self-validation & contract sanity suite
│   │   └── orchestrator.py     # Single-invoice and multi-invoice batch runner
│   ├── schemas/         # Shared schemas (Pydantic v2 in Python, Zod in TypeScript)
│   │   ├── models.py           # Canonical Python domain models
│   │   └── index.ts            # Mirrored TypeScript Zod schemas
│   └── prompts/         # Versioned LLM extraction prompts
├── fixtures/golden/     # Benchmark labeled invoices for ABF, XPO, and Roadrunner
├── infra/               # Supabase migrations (001_initial_schema.sql) & env templates
└── scripts/
    └── calibrate.py     # Automated CI precision/recall calibration harness
```

---

## 3. Implemented Capabilities (Phases 1–3)

### Phase 1: Ingestion & Storage
- Per-customer dedicated inbound forwarding email stream (`*@in.rateguard.app`).
- Multi-file drag-and-drop, CSV manifests, and ZIP unpacking.
- Multi-tenant PostgreSQL database on Supabase with Row Level Security (RLS) across 18 core tables.

### Phase 2: Document Understanding & Validation Layer
- **Phase 2.0 (Validation Layer & Calibration Harness):**
  - Deterministic arithmetic re-derivation with $\pm \$0.02$ tolerance.
  - Contract sanity suite (monotonicity, overlapping weight breaks, duplicate lanes).
  - Stratified $N=5$ spot-verification protocol for rate agreements.
  - Calibration harness maintaining **100% Precision / 100% Recall** on golden benchmarks.
  - Standardized 8-code reason taxonomy v1.
- **Phase 2.1 (Invoice Parser):**
  - Multi-engine layout extraction: IBM Docling $\to$ `pdfplumber` $\to$ `PyMuPDF` $\to$ `pypdf`.
  - Carrier-tailored context prompts for ABF Freight, XPO Logistics, and Roadrunner.
  - Self-validation loop with automatic error correction.
- **Phase 2.2 (Contract Parser):**
  - Support for Quality Ladder Rungs A (signed contract), B (email quotes), and C (tariff baseline).
  - Materializes rate matrix rows into Supabase `rate_matrices`.
- **Phase 2.3 (FSC Engine):**
  - Deterministic Monday DOE/EIA weekly diesel benchmark resolver.
  - Bracket scale matching for top-3 carriers.

### Phase 3: Deterministic Audit Engine & Pipeline
- **Phase 3.1 (Audit Engine Core & Batch Orchestrator):**
  - `check_duplicates`: PRO number match within 30 days, BOL number match, and $\pm 3$-day identical amount window. Chronological directionality prevents false positives on original bills.
  - `check_rates`: 5-digit vs 3-digit zip prefix resolution, deficit weight rating ("As" weight bumping), negotiated discounts, and Absolute Minimum Charge (AMC) floors.
  - `check_fsc`: Monday EIA diesel benchmark resolution; calculates FSC strictly on **Net Freight** (excluding accessorials and gross amounts).
  - `check_arithmetic`: Line item sum reconciliation.
  - `orchestrator.py`: Batch audit runner for historical backfills (e.g. 6-month, 2,500 invoices) with execution metrics and category distribution.
- **Phase 3.2 (Pipeline Wiring & Worker Handlers):**
  - Event-driven job processing: `parse-invoice` $\to$ `run-audit-for-invoice` $\to$ `run-audit-batch`.
  - Idempotent audit execution (`{invoice_id}:{check_type}`).
  - Dead-Letter Queue (DLQ) and internal alerting.
  - Terminal status guarantee: every invoice resolves to `audited`, `parse_failed`, or `error`.
- **Phase 3.3 (LLM Cost Guard & Circuit Breaker):**
  - SHA-256 parse cache: $0.00 spend on duplicate or re-scanned documents.
  - Model ladder: cheap models (`gpt-4o-mini`) by default; flagship models (`gpt-4o`) only on validation failure.
  - Spend tracker & monthly circuit breaker halting external calls when threshold is breached.

---

## 4. Verification & Testing

### Running Tests
```bash
# Run worker and audit engine unit tests (60/60 passing)
python -m pytest packages/audit-engine/tests apps/worker/tests -v

# Run with test coverage
python -m pytest packages/audit-engine/tests --cov=packages/audit-engine --cov-report=term-missing
```

### Running the Golden Calibration Scoreboard
```bash
python scripts/calibrate.py
```
Expected output:
```text
================================================================================
RATEGUARD AI — CALIBRATION HARNESS SCOREBOARD (PHASE 2.0.3)
================================================================================
CHECK TYPE      | TP   | FP   | FN   | TN   | PRECISION  | RECALL     | F1    
--------------------------------------------------------------------------------
DUP             | 2    | 0    | 0    | 12   |    100.0% |    100.0% | 100.0
RATE            | 2    | 0    | 0    | 12   |    100.0% |    100.0% | 100.0
FSC             | 3    | 0    | 0    | 11   |    100.0% |    100.0% | 100.0
ARITH           | 2    | 0    | 0    | 12   |    100.0% |    100.0% | 100.0
================================================================================
OVERALL ACCURACY: Precision: 100.0% (Gate >= 90%) | Recall: 100.0% (Gate >= 80%)
DECISION: GATE PASSED [GO FOR PHASE 3]
================================================================================
```

---

## 5. Next Milestones

- **Phase 4: Human Review Queue** (Internal UI, 3 buttons: Approve / Reject / Needs Research, reason code feedback loop).
- **Phase 5: Recovery Report & Dispute Letters** (Branded PDF report, 1-click dispute packet generator, signed recovery agreement gate).
- **Phase 6: Credit Memo Verification & Commission Invoicing** (Negative invoice stream scan, Stripe invoicing on verified memos).
