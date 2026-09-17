# PRODUCT REQUIREMENTS DOCUMENT (PRD)
## RateGuard AI — Freight Broker Carrier Payables Audit & Recovery
**Version 2.1 | Status: Approved for Build | Target: Freight Broker GTM Launch & Pilot Onboarding on March 21st (concierge mode)**

---

## 0. WHAT CHANGED IN v2.1 (Freight Broker ICP Pivot & March 21 Target)

| # | Update / Decision | Details & Strategic Context |
| :--- | :--- | :--- |
| **0** | **March 21 Freight Broker Target** | Primary ICP officially pivoted from Shippers to **Freight Brokers & 3PLs**. Target launch date set to **March 21st** for pilot outreach and concierge onboarding. |
| **1** | Core Problem Retained | The core audit engine and problem solved (carrier overbilling via duplicates, tariff rate misapplications, FSC miscalculations, invalid accessorials, NMFC reweighs) remain 100% identical. |
| **2** | Broker Financial Impact | Carrier overcharges eat directly into thin brokerage gross margins (12–16%). Every $1 of carrier overbilling is $1 lost from brokerage EBITDA or forced into risky customer re-billing. |
| **3** | Ingestion Channels | Primary ingestion: Broker AP email forwarding (`payables@broker.com` → RateGuard) and Broker TMS invoice exports (McLeod, Tai, Ascend, Turvo CSV/PDF ZIPs). |
| **4** | Contract Quality Ladder | Rung A–D mapping updated for Broker-Carrier rates (FSTD contracts, spot confirmations, tariff matrices, carrier pricing addendums). |
| **5** | Dispute Legal Mechanism | "We draft, the broker sends" to carriers. Prevents carrier relationship friction while recovering carrier payables overcharges before or after voucher settlement. |
| **6** | Monetization & Trigger | Pure 35% contingency on verified carrier credit memos / adjusted carrier payables vouchers. Net-15 invoicing. |

---

## 1. EXECUTIVE SUMMARY

RateGuard AI is an AI-powered carrier payables audit and overcharge recovery platform engineered specifically for **Freight Brokers and 3PLs** (with secondary support for mid-market shippers). We ingest LTL carrier invoices and broker-carrier rate agreements, detect every carrier billing error (duplicate bills, contracted rate misapplications, invalid accessorial charges, reweigh & re-class errors, fuel surcharge miscalculations, deficit weight bumping misses, and late guaranteed deliveries), and recover overpaid funds for the freight broker. Pricing is pure contingency: **35% of recovered carrier overcharges. Nothing recovered = nothing owed.**

The one-line pitch for Freight Brokers:  
> *"Carrier billing errors leak 3–7% of your total carrier payables. Because brokerage gross margins are 12–16%, overcharges erase up to 30–50% of your net EBITDA. We catch carrier overbilling and get your margin back. You only pay us from verified recoveries."*

**v2.1 Strategic GTM Launch Target: March 21st.**  
The initial product execution relies on a high-touch concierge service backed by automated LLM parsing and deterministic math engines. The software ingests broker payables and contract terms; internal human-in-the-loop review ensures 90%+ precision; the freight broker dispatches carrier dispute notices. The initial March 21st cohort of freight broker pilots receives immediate bottom-line margin recovery without requiring complex API/EDI integrations.

**Why Freight Brokers now:** Legacy audit firms (Cass, nVision, Trax) target direct enterprise shippers with armies of manual auditors. Mid-market freight brokerages ($5M–$250M in carrier payables) handle thousands of LTL carrier bills every month under tight 12–16% gross margin constraints. Carrier payables clerks cannot manually check every LTL bill against complex carrier rate matrices. AI-driven contract parsing and automated audit logic allow freight brokers to plug carrier overcharge leaks instantly.

---

## 2. PROBLEM STATEMENT

### 2.1 The Problem for Freight Brokers
* **5–15% of carrier freight invoices contain errors**, and errors systematically favor the carrier over the broker.
* **Freight brokers lose 3–7% of total annual carrier payables** to undetected carrier overbilling.
* **Margin Impact:** Freight brokerages operate on 12–16% gross margins. A $500 carrier overbilling error on a $2,000 load destroys the margin on 3–4 other loads. 
* **The Re-billing Dilemma:** When carriers overbill (e.g. unexpected reweighs or accessorials), brokers face a painful choice: try to re-bill the shipper customer (risking customer churn) or absorb the charge (destroying brokerage EBITDA). Auditing carrier payables *before* or immediately after payment eliminates this dilemma.
* **Root Cause:** A mid-market freight broker receives 500–10,000 carrier invoices per month across dozens of LTL carriers (ABF, XPO, Saia, Estes, Roadrunner). Manually auditing each invoice against carrier contract matrices, FSC tables, and NMFC classifications takes 20–30 minutes per bill. Brokerage AP teams lack the time and tooling to perform comprehensive audits.

### 2.2 Evidence the Problem is Real and Paid For
* Mature audit programs recover 8–12% of audited carrier spend; ROI for freight brokers is amplified due to gross margin leverage.
* **Cass Information Systems (NASDAQ: CASS):** ~$207M revenue (2024), 51M invoices processed/year — proving multi-hundred-million-dollar demand for freight payment audit.
* Contingency pricing (30–50% of recovered dollars) is the standard, frictionless sales model accepted by freight brokerage executive teams.

---

## 3. MARKET OPPORTUNITY

| Layer | Figure | Basis |
| :--- | :--- | :--- |
| **US Freight Brokerage LTL Market (TAM)** | ~$52.8B (2024) → ~$114B (2033) | Industry brokerage market size & LTL payables volume |
| **Annual Carrier Overbilling Pool** | $1.6B–$3.7B/yr | 3–7% carrier error rate applied to broker LTL payables |
| **Serviceable Market (SAM)** | ~$600M–$1.1B recoverable/yr | Mid-market Freight Brokerages & 3PLs ($5M–$250M payables) |
| **RateGuard Revenue Potential @ 35%** | $210M–$385M/yr | SAM × 35% contingency share |
| **Target Launch Horizon** | **March 21 Launch** | Initial broker pilot wave target |

---

## 4. CUSTOMER PROFILE (ICP) — DETAILED

### 4.1 Ideal Company Profile (Freight Broker Firmographics)

| Attribute | Target | Rationale |
| :--- | :--- | :--- |
| **Geography** | United States | US LTL billing, NMFC tariffs, and carrier accessorial rules |
| **Industry** | Freight Brokerages, 3PLs, Freight Forwarders managing LTL carrier payables | High LTL load volume, 12–16% gross margins → carrier overbilling directly impacts EBITDA |
| **Brokerage Size** | 15–300 employees | Agile leadership, fast decision-making, high carrier invoice volume |
| **Annual Carrier Payables** | $5M–$250M (LTL spend focus) | Sweet spot: $150K–$8.75M/yr in leaking carrier overcharges |
| **Monthly Carrier Invoices** | 500–10,000 carrier bills/month | Volume makes manual carrier payables audit impossible |
| **LTL Carrier Mix** | 3–25 contracted LTL carriers (XPO, ABF, Saia, Estes, Roadrunner, R+L) | Complex contract matrices, discount tiers, and accessorial schedules |
| **Carrier Payables / AP Team** | 2–10 AP/Payables clerks, no dedicated automated freight auditor | Manual voucher processing bottleneck = our key entry point |
| **TMS Tooling** | McLeod, Tai Software, AscendTMS, Turvo, Freight360, or custom broker TMS | Export carrier invoices as CSV/PDF or forward AP emails |
| **Trigger Events** | Gross margin compression; carrier dispute backlog; annual carrier pricing updates; March 21 GTM push | Clear buying windows |

### 4.2 Buyer Personas

#### Persona 1 — THE ECONOMIC BUYER (Freight Brokerage Leader / CFO / VP of Operations)
* **Title:** VP of Brokerage Operations, Brokerage CFO, Chief Operating Officer, Managing Partner.
* **Goals:** Protect brokerage gross margins (12–16%), boost EBITDA, prevent carrier payment leakage, eliminate customer re-billing friction.
* **Pain Quote:** *"Carrier overcharges are eating our margin alive. Every time a carrier adds an unverified reweigh or accessorial, we either fight with our shipper customer or eat the loss."*
* **Buying Trigger:** Proof of unrecovered carrier overcharges on past carrier payables. Showing recoverable dollars closes them instantly.
* **Objection:** *"Our AP team already verifies carrier invoices before paying."* → **Counter:** *"Let us audit 6 months of paid carrier bills for free. If we find no errors, you pay nothing. If we find overcharges, we share the recovery."*

#### Persona 2 — THE CHAMPION (Director of Carrier Payables / Operations Manager)
* **Title:** Director of Carrier Payables, AP Manager, Freight Operations Manager.
* **Role:** Oversees daily carrier voucher approvals and carrier dispute resolution.
* **Pain:** Overwhelmed by carrier balance dues, reweigh notices, and accessorial disputes; lacks time to audit line-item tariffs against carrier contracts.
* **Value:** Internal advocate who gathers sample carrier invoices and contracts for the pilot.

#### Persona 3 — THE END USER (Carrier Payables / AP Specialist)
* **Title:** Carrier Payables Specialist, AP Clerk, Settlement Specialist.
* **Role:** Processes carrier invoices daily in TMS/ERP, reviews flags, and dispatches dispute documentation to carrier reps.
* **Pain:** Spending 20–30 minutes checking a single complex LTL bill; constant friction with carrier credit departments.

#### Persona 4 — SECONDARY ICP (Mid-Market Shipper Logistics Director / CFO)
* **Title:** Shipper VP Supply Chain, Director of Logistics, Shipper CFO.
* **Role:** Direct shippers managing in-house freight spend. Supported as a secondary customer tier under the exact same audit engine.

### 4.3 Anti-ICP (Do Not Sell)
* Enterprise Fortune 500 Shippers with 9-month procurement cycles (already tied to Cass/nVision).
* Asset-only carriers (truckload fleets billing out, rather than brokering/auditing carrier payables).
* Companies with <$500K annual carrier payables (recovery volume too small for ROI).
* Prospects receiving ONLY EDI 210 with no access to PDF/email carrier bills (disqualified for MVP).
* Rung D prospects (no formal carrier rate agreements or pricing tariffs available).

---

## 5. PRODUCT OVERVIEW

### 5.1 Core Loop
Upload carrier invoices + broker-carrier rate agreements → AI Engine audits every bill → Recovery Report ($ found, evidence attached) → One-click carrier dispute letters → Broker sends to carrier → Carrier issues credit memo / voucher adjustment → We invoice 35% of verified credit memo value.

### 5.2 INGESTION — Channel-Prioritized
* **Channel A — AP Email Forwarding (60–70% of volume, MVP Priority #1):**  
  Carriers email billing PDFs to the broker's payables inbox (`payables@brokerage.com`). The broker sets an automated forwarding rule to RateGuard (`broker-invoices@rateguard.ai`). Fast, 2-minute setup.
* **Channel B — Broker TMS Exports (20–30%, MVP Priority #2):**  
  Brokers export paid/pending carrier invoices from McLeod, Tai, AscendTMS, or Turvo as CSV or PDF ZIP packages. Simple drag-and-drop ingestion.
* **Channel C — EDI 210 Ingestion:**  
  Explicitly OUT of MVP scope. Disqualify EDI-only prospects during initial qualification.

**Functional Requirements:**
* **FR-1.1:** Broker onboarding completed in <10 minutes.
* **FR-1.2:** Batch ingestion supporting 500+ carrier invoices per upload without timeout.
* **FR-1.3:** Automated contract parser extracting baseline rates, discount percentages, FSC schedules, and accessorial rules into structured JSON.
* **FR-1.4:** Dedicated inbound email routing address per broker account with forwarding setup guide.

### 5.3 CONTRACT INTAKE — The Quality Ladder
Every broker-carrier pricing contract is classified into one of four rungs:

| Rung | Document Availability | Action Plan |
| :--- | :--- | :--- |
| **A** | Signed Carrier Rate Agreement / FSTD / Tariff Addendum | Ideal: Parse directly into structured rate matrix |
| **B** | Rate terms in email threads with carrier reps | Parse email bodies and attachments via LLM into rate tables |
| **C** | Published tariff + documented discount (e.g. "Czarlite 2024 minus 68%") | Audit against baseline tariff minus discount; catches duplicates, wrong FSC, and unauthorized accessorials (~50–60% of recoverable pool) |
| **D** | No rate documentation available | Disqualify for MVP |

**Pre-Pilot Qualification Question:**  
> *"Can you provide your current pricing agreement or tariff schedule for your top 3 LTL carriers?"*

### 5.4 THE AUDIT ENGINE (LLM Parsing + Deterministic Math)
* **Deterministic Code:** Hashes for duplicate detection (carrier + PRO# + amount + load ID), exact arithmetic checks, FSC table calculations, contracted lane matrix lookups, and delivery date/guaranteed service logic.
* **LLM Intelligence:** PDF document parsing for un-structured carrier bills, contract clause extraction, POD delivery date matching, and line-item charge categorizations.

**The 8 Core Audit Checks (Identical Core Audit Logic):**
1. **Duplicate Carrier Billing:** Identical PRO#, load reference, or charge combination submitted multiple times.
2. **Rate Misapplication:** Billed rate exceeds contracted tariff or discount agreement.
3. **Fuel Surcharge (FSC) Errors:** Incorrect FSC percentage applied for the ship date/week.
4. **Unauthorized Accessorials:** Unverified liftgate, residential delivery, inside delivery, or limited access charges billed without broker dispatch authorization.
5. **Reweigh & Re-class Disputes:** Incorrect NMFC class assignment or reweigh charges violating contract tolerance rules (e.g., lack of deficit bumping).
6. **Guaranteed Service Failures:** Carrier billed guaranteed rate but delivered after promised window.
7. **Arithmetic Errors:** Line items do not sum to total invoice charge.
8. **Tax Calculation Errors:** Invalid tax assessments on non-taxable freight legs.

**Functional Requirements:**
* **FR-2.1:** Flagged overcharges contain invoice ref, contract clause reference, calculated overcharge amount, and confidence score.
* **FR-2.2:** Target flag precision ≥90% prior to client delivery (enforced via Human-in-the-Loop review).
* **FR-2.3:** 500 invoices processed and audited in under 15 minutes.

### 5.5 HUMAN-IN-THE-LOOP (HITL) REVIEW QUEUE
Internal review screen for RateGuard audit team to verify flagged overcharges before presenting to the freight broker. Ensures absolute data integrity and maintains 90%+ precision guarantee.

### 5.6 RECOVERY REPORT & CARRIER DISPUTE LETTERS
* **Recovery Report:** PDF/Dashboard detailing total recoverable overcharges grouped by carrier, error category, and load reference.
* **Dispute Letters ("We Draft, Broker Sends"):** Pre-formatted dispute letters citing specific contract clauses and PRO numbers. The broker's carrier payables clerk reviews and forwards the dispute directly to the carrier rep.
* **Benefits:** Preserves broker-carrier relationship, avoids Power-of-Attorney paperwork, and integrates seamlessly with standard AP workflows.

### 5.7 BILLING TRIGGER & MONETIZATION
* **Contingency Model:** 35% of verified carrier overcharge recoveries (credit memos or payables voucher reductions issued by carriers).
* **Trigger Event:** Issued carrier credit memo or verified payables adjustment. Invoiced on Net-15 terms.
* **Denial Factor:** ~20–30% carrier denial rate is pre-calculated into the 35% contingency pricing.

---

## 6. USER FLOWS

* **Flow A — Broker Pilot (Concierge Mode):** Qualification → Broker uploads 6 months of paid carrier bills + carrier rate sheets → System audits → HITL verification → 30-min "Broker Margin Recovery" presentation → Broker executes 1-page agreement → Broker dispatches dispute letters → Carrier issues credit memos → RateGuard invoices 35% commission (Net-15).
* **Flow B — Broker Self-Serve (Post-MVP, Weeks 6–8):** Broker onboarding → Select TMS / configure email forwarding → Automated continuous carrier audit → Monthly recovery statement & automated dispute dispatch.

---

## 7. GTM & BUILD TIMELINE (Targeting March 21 Broker Launch)

| Week / Milestone | Execution Deliverables | Broker Impact |
| :--- | :--- | :--- |
| **Week 1** | Ingestion pipeline (email forwarding + TMS export support), database schema setup | Internal readiness |
| **Week 2** | Audit engine v1 (Duplicates, Rate misapplications, FSC check), contract parser | Internal testing |
| **Week 3 (March 21 Target)** | **GTM Launch & First Freight Broker Pilot Delivery.** Review queue UI live, Recovery Report generation, dispute letter builder. Onboard first freight brokerages in concierge mode. | **First Freight Broker Pilots Live (March 21)** |
| **Weeks 4–5** | Expansion to 3–5 brokerage pilots; Stripe commission billing; refinement of broker TMS parsers | **Revenue & Case Studies** |
| **Weeks 6–8** | Automated self-serve broker onboarding, top 10 LTL carrier invoice templates, dispute status tracking | **Scalable Product Platform** |

---

## 8. PRICING & BUSINESS MODEL

| Element | Specification |
| :--- | :--- |
| **Pricing Structure** | Pure contingency: 35% of verified carrier overcharge recoveries |
| **Billing Trigger** | Carrier credit memo issued or payables voucher adjustment verified. Net-15 terms. |
| **Broker Pilot Offer** | Free historical audit of past 3–6 months of carrier payables |
| **Managed Dispute Add-on** | +10% fee (40% total) if RateGuard manages end-to-end carrier correspondence |
| **Expected Broker Value** | $100K–$350K+ annual margin recovery per $10M–$25M in carrier payables |

---

## 9. TECH STACK & BUDGET

* **Database & Auth:** Supabase (PostgreSQL, Auth, Storage) — Free Tier
* **Hosting:** Vercel Hobby / Pro
* **AI Engine:** OpenAI / Anthropic Pay-As-You-Go API (~$50–$100/mo at pilot volume)
* **Inbound Email:** Postmark Inbound API ($15/mo)
* **Operational Budget Ceiling:** <$200/mo until initial pilot revenue

---

## 10. SUCCESS METRICS & KPIs

| Metric | Target | Strategic Objective |
| :--- | :--- | :--- |
| **March 21 Launch Target** | Onboard first Freight Brokerage pilot by **March 21st** | GTM validation |
| **Broker Flag Precision** | ≥90% (Concierge) → ≥95% (Automated) | Broker trust retention |
| **Audit Processing Speed** | 500 carrier invoices in <15 minutes | Scalability |
| **Average Margin Recovery** | ≥$100K/yr recovered per broker ($10M carrier payables) | Core economic engine |
| **Dispute Acceptance Rate** | ≥75–80% carrier approval | Recovery efficiency |
| **Broker Onboarding Time** | <10 minutes for email forwarding setup | Zero-friction adoption |

---

## 11. RISKS & MITIGATIONS

| Risk Factor | Severity | Mitigation Strategy |
| :--- | :--- | :--- |
| **Messy / Missing Carrier Rate Agreements** | High | Quality Ladder framework; concierge team assists broker in pulling carrier rate PDFs |
| **Carrier Opposition / Dispute Denials** | Medium | "We draft, broker sends" model; detailed contract clause citations; 20–30% denial buffer in 35% rate |
| **AP Team Resistance** | Medium | Position RateGuard as an assistant to AP clerks that frees them from manual 20-min invoice checks |
| **Delayed Carrier Credit Memos** | Medium | Invoicing based on confirmed credit memo issuance / voucher adjustment rather than cash payout |

---

## 12. PHASED PRODUCT ROADMAP

* **Phase 1 (March 21 Focus):** Concierge Freight Broker Carrier Payables Audit & Recovery (Duplicate, Rate, FSC, Accessorial checks; top LTL carriers).
* **Phase 2:** Continuous Pre-Pay Carrier Voucher Audit (Catch errors *before* broker pays carrier); TMS integrations (McLeod, Tai, Turvo).
* **Phase 3:** Self-serve broker portal, multi-user carrier payables approval workflows, automated EDI 210 parser.
* **Phase 4:** Integrated Freight Payment & Disbursement Float Management for Brokerages.
