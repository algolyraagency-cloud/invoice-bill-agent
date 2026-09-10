# PRODUCT REQUIREMENTS DOCUMENT (PRD)
## RateGuard AI — Freight Audit & Recovery
**Version 2.0 | Status: Approved for Build | Target: First paying pilot customer in 3 weeks (concierge mode)**

---

## 0. WHAT CHANGED IN v2.0 (incorporates the 7 operational Q&A decisions)

| # | Question | Decision now baked into the PRD |
| :--- | :--- | :--- |
| **1** | Where do invoices come from? | Ingestion is now channel-prioritized: email forwarding (60–70%, MVP #1) → AP system export CSV/ZIP (20–30%, #2) → drag-and-drop (fallback). EDI 210 is explicitly out of MVP and a disqualifier signal. |
| **2** | Messy/missing contracts? | Added the Contract Quality Ladder (Rungs A–D) and a mandatory pre-pilot qualification question. Rung D = disqualify. |
| **3** | How do we get paid? | Billing trigger is now credit-memo-issued + verified, NOT cash received. Net-15. Denials priced into the 35%. |
| **4** | Disputes "on their behalf"? | Legal mechanism: we draft, the customer sends. Always. Phase 2: one-page authorization letter only if carriers demand it (~customer #5–10). |
| **5** | Stack & LLM vs deterministic? | Architecture split codified: LLM for understanding, deterministic code for math. Budget ceiling $200/mo until first revenue. |
| **6** | Who reviews? | Human-in-the-loop review queue added as a first-class feature (internal). 90% precision guarantee lives here. Reason-code feedback loop documented. |
| **7** | 3-week clock? | Concierge-first is the official GTM mode. Weekly build timeline (W1–W8) added. Self-serve is W6–8, not W2. |

---

## 1. EXECUTIVE SUMMARY

RateGuard AI is an AI-powered freight audit and recovery service for mid-market US shippers. We ingest carrier invoices and rate contracts, detect every billing error (duplicates, wrong rates, invalid accessorials, reweighs, fuel surcharge miscalculations), and recover the overpaid money for the shipper. Pricing is pure contingency: **35% of recovered dollars. Nothing recovered = nothing owed.**

The one-line pitch:  
> *"You are losing 3–7% of your freight spend to carrier billing errors. We find it and get it back. You only pay us from what we recover."*

**v2.0 strategic framing — the MVP is a concierge service with software underneath.**  
The software does the reading and the math; we do the judgment calls; the customer does the sending. The first 5 customers are not buying software — they are buying a "$100K found-money" phone call. Everything else (EDI, PoAs, self-serve, integrations) is a response to real demand, not a prediction of it.

**Why now:** Legacy freight audit firms (Cass, nVision, Trax) run on armies of human auditors, take months, and chase only enterprise clients. LLMs can now read messy LTL invoices and 40-page rate contracts at near-zero marginal cost. The mid-market ($2M–$50M freight spend) is completely unserved.

---

## 2. PROBLEM STATEMENT

### 2.1 The problem
* **5–15% of freight invoices contain errors**, and errors systematically favor the carrier.
* **Shippers lose 3–7% of total annual freight spend** to undetected overbilling.
* **Root cause:** a mid-market shipper receives 500–10,000 carrier invoices/month. Manually auditing one invoice against a rate contract takes 20–30 minutes. No AP team can check them all, so bills are paid on trust.
* **LTL is the worst offender:** NMFC freight-class reweighs, cubic-capacity rules, complex accessorial schedules, and monthly fuel-surcharge tables create endless error surface area.

### 2.2 Evidence the problem is real and paid for
* Mature audit programs recover 8–12% of audited spend; year-1 ROI exceeds benchmarks (industry).
* **Cass Information Systems (NASDAQ: CASS):** ~$207M revenue (2024), 51M invoices processed/year, $94B annual disbursements — a multi-decade, multi-hundred-million-dollar business built on this exact problem.
* Contingency recovery (30–50% of recovered dollars) is the established, accepted pricing model.

---

## 3. MARKET OPPORTUNITY

| Layer | Figure | Basis |
| :--- | :--- | :--- |
| **US LTL market (TAM)** | ~$52.8B (2024) → ~$114B (2033) | Industry market-size reports |
| **Annual overbilling pool** | $1.6B–$3.7B/yr | 3–7% error rate applied to TAM |
| **Serviceable (SAM)** | ~$600M–$1.1B recoverable/yr | Mid-market shippers (~35% of spend) |
| **RateGuard share @ 35% contingency** | $210M–$385M/yr revenue potential | SAM × 35% |
| **Expansion TAM** | +$400B+ global LTL; TL & parcel audit; freight payment float | Roadmap phases 2–4 |

**Bottom line:** the audit niche alone supports a $1B+ outcome; freight payment (the Cass endgame) makes it inevitable if we win the audit wedge.

---

## 4. CUSTOMER PROFILE (ICP) — DETAILED

### 4.1 Ideal Company Profile (firmographics)

| Attribute | Target | Why |
| :--- | :--- | :--- |
| **Geography** | United States | LTL billing complexity is US-centric (NMFC, tariffs) |
| **Industry** | Manufacturing (furniture, building materials, machinery), wholesale distribution, food & beverage distribution, e-commerce brands shipping palletized freight | High LTL volume, thin margins → overbilling hurts |
| **Employees** | 50–500 | Big enough for real freight spend; too small for Cass/nVision |
| **Annual revenue** | $10M–$150M | Correlates with freight spend sweet spot |
| **Annual freight spend** | $2M–$50M (avg ~$10M) | = $60K–$3.5M/yr leaking to errors |
| **Invoices/month** | 500–10,000 carrier invoices | Volume makes manual audit impossible |
| **Carrier count** | 3–15 contracted LTL carriers | Enough contracts to audit against |
| **AP team** | 2–10 people, no dedicated freight auditor | Bottleneck = our wedge |
| **Current tooling** | ERP (NetSuite/SAP B1/QuickBooks), maybe a TMS; invoices arrive as PDF/email; rarely EDI | No existing audit = greenfield |
| **Trigger events** | New CFO/controller; freight spend growth; bad audit experience; carrier GRI season | Buying windows |

### 4.2 Buyer Personas

#### Persona 1 — THE ECONOMIC BUYER (primary target)
* **Title:** CFO, VP Finance, or Controller. Age 38–55. Reports to CEO/PE owner. Measured on cash and margin.
* **Goals:** free cash, margin improvement, clean books, no surprises.
* **Pain quotes:** *"I know we're being overcharged, but I can't prove it."* / *"We found a $50K duplicate once by accident. How many did we miss?"*
* **Buying trigger:** any proof of recoverable dollars. A single number ("$187,340 recoverable") closes them.
* **Objection:** *"Our AP team already checks these."* → **Counter:** *"Give us 6 months of invoices. If we find nothing, you pay nothing."*
* **Where to find:** LinkedIn (title + company size filters), CFO peer groups, industry finance communities.

#### Persona 2 — THE CHAMPION
* **Title:** VP/Director Supply Chain, Director of Logistics.
* **Role:** Owns carrier relationships and shipping budget. Feels the billing chaos daily; often brings us to the CFO.
* **Pain:** drowning in invoice disputes, no leverage with carriers, blamed for freight cost overruns.
* **Value:** internal advocate; writes the business case; usually runs the evaluation.

#### Persona 3 — THE END USER
* **Title:** Transportation Manager, Logistics Manager, AP Manager.
* **Role:** Runs invoices daily. Operates the product in self-serve mode (upload, review, send disputes).
* **Pain:** 20–30 min per manual invoice check; carrier disputes go nowhere; month-end crunch.
* **Value:** product feedback, renewal loyalty.

### 4.3 Anti-ICP (explicitly NOT our customer — do not sell)
* **Fortune 1000** (already served by Cass/nVision; 9-month sales cycles)
* **Companies spending <$500K/yr on freight** (recovery too small)
* **Carriers/trucking companies** (different business)
* **Pure parcel shippers** (UPS/FedEx refund space is commoditized)
* **3PLs/brokers** (future channel partners, not first customers)
* **NEW: prospects who "only get EDI 210"** — EDI requires a translator stack that's Fortune 1000 territory. Out of MVP scope; disqualify and revisit in Phase 3.
* **NEW: Rung D contract prospects (no rate agreement at all)** — a pilot with no contract produces a weak report and burns a referral. Politely pass, check back in 3 months.

---

## 5. PRODUCT OVERVIEW

### 5.1 Core loop
Upload invoices + rate contracts → AI audits every invoice → Recovery Report ($ found, with evidence) → One-click dispute letters → customer sends → carrier issues credit memo → we invoice 35% of verified credit memos.

### 5.2 INGESTION — Channel-Prioritized (Q1 decision)

* **Channel A — Email forwarding (60–70% of volume, MVP priority #1).**  
  Carriers email invoices as PDF attachments to the shipper's AP inbox. The shipper sets a forwarding rule: anything from `@abf.com`, `@xpo.com`, `@roadrunner.com` etc. → forward to their unique RateGuard address. Path of least resistance — AP clerks already live in email; a forwarding rule takes 2 minutes. We parse the email body + attachment via inbound email API (Postmark/Mailgun inbound).
* **Channel B — AP system exports (20–30%, MVP priority #2).**  
  Mid-market shippers run NetSuite, SAP Business One, or QuickBooks. Their AP team exports "paid freight invoices" as CSV or a ZIP of PDFs in under 10 minutes. Simple upload UI for both. We do NOT build API integrations in MVP — the export takes the customer 10 minutes and takes us zero engineering time.
* **Channel C — EDI 210 (enterprise-only, explicitly OUT of MVP).**  
  EDI 210 is the X12 transaction carriers use to bill electronically. Requires an EDI translator (TrueCommerce, SPS Commerce, Cleo) and carrier mappings — Fortune 1000 territory. Phase 3. If a pilot prospect says "we only get EDI," they are not an MVP customer.
* **Drag-and-drop:** acceptable UI, but it is the fallback for stragglers — not the main artery. The main artery is the forwarding rule.

**Functional Requirements:**
* **FR-1.1:** Customer can onboard (company, users, remit-to) in <10 min.
* **FR-1.2:** Batch upload of 500+ invoices without error.
* **FR-1.3:** Contract parser outputs validated JSON rate matrix with confidence scores.
* **FR-1.4:** Unique inbound email address per customer; forwarding-rule setup instructions in onboarding.

### 5.3 CONTRACT INTAKE — The Quality Ladder (Q2 decision)
The single biggest operational risk. Every pilot customer is sorted into one rung:

| Rung | What they have | Our move |
| :--- | :--- | :--- |
| **A** | Clean signed pricing agreement (FSTD, pricing addendum, rate tariff) | Ideal — parse directly |
| **B** | Rates buried in email chains with carrier reps ("attached is your 2024 pricing...") | Parse emails + attachments; LLM extracts the rate matrix from messy text |
| **C** | Only published tariff + verbal "we get 65% off" | Fallback audit mode: audit against published tariff minus claimed discount. Weaker, but still catches duplicates, fake accessorials, and arithmetic errors — ~50% of recoverable dollars |
| **D** | Nothing | Disqualify for MVP. Not every prospect is a customer |

**Mandatory pre-pilot qualification question (ask before any free work):**  
> *"Can you send me your current rate agreement with your top carrier?"*

* **Yes** → proceed.
* **"Let me find it"** → proceed with caution.
* **"We don't have one"** → politely pass, check back in 3 months.
* *Note:* carriers are legally required to maintain tariffs; negotiated rates are amendments. Many mid-market shippers DO have the PDF — it lives in the AP clerk's inbox or a shared drive. Part of concierge onboarding is literally helping them find it.

### 5.4 THE AUDIT ENGINE (~80% of engineering effort)
**Architecture split (Q5 decision): LLM for understanding, deterministic code for math.**

**Deterministic code (no LLM, no variance):**
* Duplicate detection (hash on carrier + pro# + amount + date window)
* Arithmetic validation (line items = invoice total)
* FSC calculation (lookup table: month → FSC % → apply to base)
* Rate matrix lookups (lane + weight break → contracted rate)
* Date logic (guaranteed service: promised date vs. POD delivery date)

**LLM (understanding messy documents):**
* Parsing invoice PDFs → structured JSON (charges, accessorials, pro numbers from 20 carrier formats)
* Parsing rate contracts → rate matrix JSON (the hard one — 20–40 pages of tables, exceptions, FAK mappings)
* Parsing PODs for delivery dates
* Matching remittance/payment emails to invoices (fuzzy text understanding)

**Why this split matters for cost:**  
A $10M-spend shipper generates ~5,000 invoices/year. LLM-parsing 5,000 invoices + 10 contracts ≈ $50–150 in API calls. Deterministic math on 5,000 invoices costs $0. LLM-ing everything would 10x cost for zero accuracy gain on math.

**The 8 audit checks (per invoice):**
1. **Duplicate billing** (same pro/load #, same charges, same date window)
2. **Rate misapplication** (billed rate ≠ contracted lane rate)
3. **Fuel surcharge miscalculations** (wrong FSC %, wrong table month)
4. **Unauthorized/fictitious accessorials** (liftgate, residential, limited access, inside delivery, appointment — billed but not applicable)
5. **Reweigh & dimension disputes** (billed weight/class vs. contract rules; NMFC class errors)
6. **Guaranteed-service failures** (billed premium, delivered late → refund owed)
7. **Arithmetic errors** (line items ≠ total)
8. **Tax errors** where applicable

**Functional Requirements:**
* **FR-2.1:** Every flagged error carries: invoice ref, contract clause cited, $ overcharge, confidence score.
* **FR-2.2:** Precision target: ≥90% of flagged errors are real (human review in concierge mode).
* **FR-2.3:** Audit of 500 invoices completes in <15 minutes.

### 5.5 HUMAN-IN-THE-LOOP REVIEW QUEUE (Q6 decision — internal feature, where the 90% guarantee lives)
Invisible to customers; simple internal queue — one screen, three buttons:

```text
┌─────────────────────────────────────────────────────────┐
│ REVIEW QUEUE — 14 flagged errors (Acme Imports)         │
├─────────────────────────────────────────────────────────┤
│ ▶ INV-2847 · ABF · $412.50                              │
│ Flag: Fuel surcharge miscalculated                      │
│ Billed FSC: 42% · Contract FSC (June): 38%              │
│ Evidence: [invoice PDF] [contract p.7]                  │
│ [✓ Approve] [✗ Reject] [? Needs research]               │
├─────────────────────────────────────────────────────────┤
│ ▶ INV-2851 · XPO · $1,204.00                            │
│ Flag: Possible duplicate of INV-2844                    │
│ [✓ Approve] [✗ Reject] [? Needs research]               │
└─────────────────────────────────────────────────────────┘
```

* **Approve** → goes into the customer-facing Recovery Report.
* **Reject** → "rejected" log = training data; every rejection tagged with a reason code (*wrong rate matrix row, misread PDF, contract exception misapplied*).
* **Needs research** → manual contract dig.
* **Time budget:** ~30 seconds per flag. A 500-invoice pilot with ~50 flags = 25 minutes of review.
* **Feedback loop:** monthly review of top reason codes → fix the parser or contract reader. This is how 90% → 95% → 98% precision.

### 5.6 RECOVERY REPORT + DISPUTE LETTERS (with legal mechanism — Q4 decision)
* **Branded PDF report:** total $ recoverable, breakdown by error type and carrier, evidence per claim.
* **Dispute letter generation:** we draft, the customer sends. Always (MVP).
* Letter generated as PDF + email body, addressed from the shipper, citing the shipper's contract.
* Customer (or AP clerk) copies it into their own email and hits send. Two minutes of their time.
* **Why:** zero legal complexity, zero PoA paperwork, zero carrier-relationship risk. The carrier sees a dispute from their customer — normal business.
* Customer CCs/forwards us the thread for status tracking.
* **Phase 2 option:** a one-page authorization letter ("RateGuard AI is authorized to submit billing disputes on our behalf") — built only when a carrier demands it (expect around customer #5–10).
* **We never do in MVP:** act as a party to the dispute, file anything legal, or communicate with carriers without the customer in the loop.
* **Status tracking:** disputed → carrier response → credit memo issued → applied/paid. Lightweight, spreadsheet-grade.
* **FR-3.1:** Report readable by a CFO in <5 min; "bottom line" number on page 1.
* **FR-3.2:** Dispute letter ready to send with <1 click of edits.

### 5.7 RECOVERY REALIZATION & OUR BILLING TRIGGER (Q3 decision — critical)
**Industry reality:** carriers issue credit memos, not checks. The standard mechanism is a credit memo applied against future invoices; the shipper's next carrier bills are reduced by the credited amount.

**Our billing trigger:** we invoice 35% on credit memo issued by the carrier, verified by documentation — **NOT on cash received.**

**Mechanism:**
1. Dispute sent → carrier responds with credit memo (or denial).
2. Shipper forwards the credit memo, or we detect it in the forwarded invoice stream (credit memos often arrive as invoices with negative amounts).
3. Verification: credit memo number, original invoice reference, dollar amount, carrier name — matched against our dispute record.
4. We invoice 35% of credit memo value, net-15.

**Why not cash received:** credit memos can take 60–90 days to flow through AP; cash-basis billing means financing our customers' working capital. Cash-basis billing kills audit firms. Memo-basis is the industry standard for contingency auditors.

**Edge cases:**
* **Actual refund checks** (some carriers cut checks for large amounts): same trigger — documented refund = billing event.
* **Carrier denies:** track, escalate once with stronger evidence; if still denied, mark "unrecoverable," eat the cost. The 35% already prices in ~20–30% denial rates.

### 5.8 Concierge Mode (how the first 5 customers are served)
Same 3 features, operated by us. Customer uploads (or forwards); we run the audit, human-review every flagged error, deliver the report on a call, and optionally send disputes on their behalf (+10% fee). Purpose: revenue in week 3, training data, product learning.

### 5.9 Explicit NON-GOALS for MVP (do not build)
* ERP/TMS API integrations — Phase 2 (CSV/ZIP export is the bridge)
* Dashboards, analytics, charts — Phase 3
* Payment processing / freight pay — Phase 4 (Cass endgame)
* Carrier-side features, claims filing, detention — out of scope
* Multi-user roles & permissions — Phase 3
* Self-serve dispute automation — after concierge proves letter formats
* EDI 210 ingestion — Phase 3, and a current disqualifier
* Acting as a dispute party / PoA / direct carrier communication — not MVP
* Self-serve onboarding before week 6 — the first 5 customers need found money, not a signup flow

---

## 6. USER FLOWS

* **Flow A — Pilot (concierge):** Pre-qualification (contract rung question) → shipper sets forwarding rule / sends 6 months of invoices + contracts → we audit → human review → 30-min "Found Money" call with report → sign 1-page recovery agreement → customer sends dispute letters (we track) → credit memos verified → we invoice 35%, net-15 → monthly commission cycle.
* **Flow B — Self-serve (post-MVP, week 6–8):** Signup → onboarding wizard (company, remit-to, carriers, contract upload, forwarding-rule instructions) → invoices flow via forwarding rule → audit runs → human spot-check queue → report → click "Generate disputes" → customer sends → credit-memo detection → commission invoicing.

---

## 7. THE 3-WEEK CLOCK — Concierge-First (Q7 decision, confirmed)

| Week | Deliverable | Customer-facing? |
| :--- | :--- | :--- |
| **1** | Ingestion pipeline (email forwarding + upload), document storage, manual invoice entry fallback | No — internal |
| **2** | Audit engine v1: duplicates + rate check + FSC check (these three = ~70% of recoverable dollars). Contract parser for top 3 carriers | No — internal |
| **3** | Review queue UI, Recovery Report PDF, dispute letter generator. Run first real pilot manually — we upload, we review, we hand over the report on a Zoom call | **Yes — first pilot delivered** |
| **4–5** | Second and third pilots. Refine audit rules from findings. Stripe billing for first commission invoice | **Yes — revenue** |
| **6–8** | Self-serve onboarding flow, top 10 carrier formats, automated dispute tracking | **Yes — product** |

**The trap to avoid:** building self-serve onboarding in week 2. It's 2 weeks of engineering that adds zero value when hand-holding the first 5 customers anyway. The first 5 customers don't need a signup flow — they need us to find them $100K.

---

## 8. PRICING & BUSINESS MODEL

| Element | Detail |
| :--- | :--- |
| **Model** | Contingency only in MVP: 35% of recovered (credit-memo-verified) dollars |
| **Billing trigger** | Credit memo issued + verified. Net-15. Never cash-received basis |
| **Pilot** | Free audit of last 6 months; simple 1-page recovery agreement |
| **Concierge dispute handling** | +10% fee (40% total) if we manage the dispute process end-to-end |
| **Future (Phase 2+)** | Continuous pre-audit subscription $1,500–$5,000/mo ("stop overpaying before it happens"); payment processing take-rate; analytics tier |
| **Unit economics target** | First customer ≤3 weeks from first outreach; ≥$100K revenue per $10M-spend customer/yr; CAC ≈ $0 (founder-led, free pilot) |
| **Denial economics** | ~20–30% dispute denial rate priced into the 35% |

---

## 9. TECH STACK & BUDGET (Q5 decision)

| Item | Choice | Cost |
| :--- | :--- | :--- |
| **DB + auth + storage** | Supabase free tier (500MB DB, 2GB storage — enough for thousands of invoice PDFs) | $0 |
| **Hosting** | Vercel hobby tier | $0 |
| **LLM API** | OpenAI/Anthropic pay-as-you-go | ~$50–100/mo at pilot volume |
| **Inbound email** | Postmark (5,000 emails) | $15/mo |
| **Domain + misc** | — | ~$20/mo |
| **Total** | | **~$100–150/mo (ceiling: $200/mo until first revenue)** |

*Stripe fees only when we bill. Billing: Stripe invoicing for commission invoices.*

---

## 10. SUCCESS METRICS & KPIs

| Metric | Target | Why it matters |
| :--- | :--- | :--- |
| **First paying pilot customer** | ≤3 weeks from first outreach | Validates concierge GTM |
| **Flag precision (post-review)** | ≥90% → 95% → 98% monthly | The trust covenant; reason-code loop drives it |
| **Review time per flag** | ≤30 seconds | Concierge unit economics |
| **Audit throughput** | 500 invoices <15 min | Scales to 10K/mo customers |
| **Recoverable $ found per $10M-spend customer** | ≥$100K/yr revenue to us | Core unit economics |
| **Dispute denial rate** | ≤20–30% | Watch for carrier-specific hostility |
| **Credit memo verification rate** | 100% of billed commissions | Revenue integrity |
| **Memo-to-verification lag** | Track; flag if >60 days | Early-warning on billing disputes |
| **Onboarding time** | Customer forwarding rule live <10 min | Ingestion friction is the #1 drop-off risk |

---

## 11. RISKS & MITIGATIONS (new in v2.0)

| Risk | Severity | Mitigation |
| :--- | :--- | :--- |
| **Contract quality (messy/missing)** | High | Quality Ladder Rungs A–D; mandatory pre-pilot question; concierge helps locate the PDF |
| **Billing on cash instead of memos kills cash flow** | High | Memo-basis billing trigger, net-15, verified |
| **Customer expects us to "handle carriers"** | Medium | "We draft, you send" — set expectation in the recovery agreement |
| **Carrier denies disputes in bad faith** | Medium | Escalate once with evidence; price 20–30% denial into 35%; track denial by carrier |
| **False positives erode CFO trust** | High | Human review queue until precision ≥98%; never auto-send flags to customers in concierge mode |
| **EDI-only prospects waste sales time** | Low | Disqualifier question added to ICP/anti-ICP |
| **Scope creep (self-serve, integrations, dashboards)** | High | Non-goals list; 3-week clock; concierge-first |
| **Credit memo detection misses (revenue leakage)** | Medium | Invoice stream monitoring for negative-amount invoices + customer forwards |

---

## 12. PHASE ROADMAP (context, not commitment)

* **Phase 1 (now):** Concierge audit + recovery, 3 checks (dupes, rate, FSC), top 3–10 carrier formats, memo-basis billing.
* **Phase 2:** Continuous pre-audit subscription; one-page authorization letters; NetSuite/QuickBooks sync; top 20 formats.
* **Phase 3:** Self-serve at scale; EDI 210; dashboards; multi-user roles; analytics tier.
* **Phase 4:** Freight payment / disbursements (the Cass endgame).

*Everything in Phase 2+ is a response to real demand, not a prediction of it.*
