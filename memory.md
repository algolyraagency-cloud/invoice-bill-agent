# RateGuard AI (Lexa) — Project Memory & Technical Context

> **Last Updated:** September 20, 2026  
> **System:** RateGuard AI (Lexa) Autonomous LTL Freight Billing Audit Platform  
> **Repository:** `c:\Users\krish\Downloads\LTL startup`  
> **Primary Goal:** 100% autonomous, zero-localhost, cloud-native freight bill auditing for freight brokers and shippers on a contingency fee model (65% client retained / 35% contingency fee).

---

## 1. Core Architecture & Cloud Infrastructure

The platform is designed to operate on **100% free-tier cloud infrastructure** with **zero localhost dependencies**:

```
[ Carrier Invoices ] 
        │
        ├── (Direct Inbound) ───────────────────────────────┐
        └── (Gmail / Outlook Auto-Forwarding) ──────────────┤
                                                            ▼
                                           [ Cloudflare Email Routing ]
                                           (Domain: lexaintake.com)
                                                            │
                                                            ▼
                                            [ Cloudflare Worker ]
                                            (lexa-email-intake)
                                            • 64KB Stream Reader (< 1ms CPU)
                                            • Google Verification Auto-Clicker
                                            • Carrier & Overcharge Parser
                                                            │
                                                            ▼
                                            [ Supabase PostgreSQL DB ]
                                            (ojolpdbveutbaxqmaffv.supabase.co)
                                            • Tables: customers, invoices, disputes
                                                            │
                                                            ▼
                                            [ Frontend Customer Portal ]
                                            (Vercel / Cloudflare Pages)
                                            • public/portal.html
                                            • Real-time KPI Recalculation
```

### Infrastructure Endpoints & Keys
* **Supabase Project URL:** `https://ojolpdbveutbaxqmaffv.supabase.co`
* **Supabase Service Role Key:** `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9qb2xwZGJ2ZXV0YmF4cW1hZmZ2Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4OTAzNzU5OSwiZXhwIjoyMTA0NjEzNTk5fQ.3mIQrpX4cxH7tuO6xZyynMuq8xCw-bm84pbxTpm790Y`
* **Production Portal URL:** `https://invoice-bill-agent-lq8w-seven.vercel.app/portal`
* **Email Inbound Domain:** `lexaintake.com` (Cloudflare MX: `route1.mx.cloudflare.net`, `route2.mx.cloudflare.net`, `route3.mx.cloudflare.net`)

---

## 2. Authentication & Multi-Tenant Isolation

### A. Google Auth & Supabase Auth
* Users authenticate via **Google OAuth** or email/password directly connected to Supabase Auth (`supabase.auth`).
* Session tokens and user profiles are stored in browser `localStorage` (`rateguard_token`, `rateguard_user`, `rateguard_org`).

### B. Multi-Tenant Organization Routing
* Every customer has a unique UUID and slug in the `customers` table.
* **Active Brokerage Organization:**
  * **Customer ID:** `57e87372-2586-4283-b647-890b8ce85c37`
  * **Name:** `KRISHNA FREIGHT BROKER`
  * **Slug:** `krishna-freight-broker`
  * **Inbound Email:** `krishna-freight-broker@lexaintake.com`
  * **Portal Session:** `?customer_id=57e87372-2586-4283-b647-890b8ce85c37`
* **Isolation Rule:**
  * The Cloudflare Worker reads the envelope recipient (`toAddress`).
  * Extracts the slug (e.g. `krishna-freight-broker@lexaintake.com` → `krishna-freight-broker`).
  * Queries Supabase for `customers.slug = orgSlug` to obtain `customer_id`.
  * Invoices are tagged with `customer_id`, ensuring clients can never view other clients' data.

---

## 3. Inbound Email Pipeline & Cloudflare Worker

### Worker Name: `lexa-email-intake`

#### Critical Features Implemented:
1. **64KB Stream Optimization (CPU Limit Protection)**:
   * Cloudflare Workers Free Tier enforces a strict **10ms CPU limit**.
   * Large PDF attachments (1MB+) caused worker timeouts when decoded in full.
   * **Fix:** The worker limits reading to the first **64 KB** (`MAX_BYTES = 65536`). This extracts all headers, subject, and the complete text body in `< 1ms`, completely skipping heavy binary PDF attachment chunks.
2. **Google Forwarding Auto-Verification**:
   * Intercepts verification emails from `forwarding-noreply@google.com`.
   * Automatically extracts Google's confirmation link (`https://mail-settings.google.com/mail/vf-...`) and executes `fetch(confLink)` in the background.
   * Extracts the numeric confirmation code (e.g., `1789874294`) and records it in Supabase under `Google Mail Verification` for instant manual retrieval if needed.
3. **MIME Boundary Sanitization**:
   * Strips raw multipart MIME headers and boundary lines (`boundary="..."`, `Content-Type:`, etc.).
   * Prevents boundary tokens (e.g., `qP6eXnimyn8gA5Q`) from being mistaken for PRO numbers or `To:` headers as invoice numbers.
4. **Zero-Hardcoding Dynamic Carrier & Line-Item Audit**:
   * Detects known carriers (`Zenith Logistics Solutions`, `Vanguard Logistics`, `GSW Freight System`, `ABF Freight`, `XPO Logistics`, `Estes Express`, `Saia`, `Old Dominion`, `TForce`) or generic `... Logistics / Freight` names.
   * Detects line-item overcharges dynamically:
     * **NMFC Re-classification:** Class 85 → 110 uplift ($187.50).
     * **Weight & Research / Inspection Fee:** ($85.00).
     * **Detention Charges:** Accessorial errors ($225.00).
     * **Deficit Weight Bumping:** Tariff Item 100-D errors ($135.25).
   * If an invoice has no discrepancies, overcharge is recorded as `$0.00` and status is marked `audited` (clean). It **never** defaults to fake numbers.

---

## 4. Gmail Forwarding & Filter Setup (Option B)

Brokers can either give carriers `krishna-freight-broker@lexaintake.com` directly (Option A) or set up auto-forwarding in their existing Gmail/Outlook (Option B):

### Gmail Setup Steps:
1. **Add Forwarding Address:**
   * In Gmail Settings → **Forwarding and POP/IMAP** → Add `krishna-freight-broker@lexaintake.com`.
   * Worker auto-clicks the verification link and logs confirmation code `1789874294`.
2. **Create Invoice Forwarding Filter:**
   * **Matches:** `has:attachment filename:pdf ("invoice" OR "freight" OR "bill" OR "bol" OR "rate confirmation" OR "pro#") -in:chats`
   * **Action 1:** `Forward to: krishna-freight-broker@lexaintake.com`
   * **Action 2 (CRITICAL):** `Never send it to Spam`
     * *Why:* Personal test emails often trigger Google's anti-phishing AI when sending corporate billing text. Gmail strictly refuses to run forwarding filters on messages in Spam. Checking `Never send it to Spam` forces them to Inbox and guarantees forwarding fires.

---

## 5. Frontend Portal Engine (`public/portal.html`)

* **Repository Path:** `public/portal.html`
* **Live Deployment:** Auto-deployed via Git push to GitHub (`algolyraagency-cloud/invoice-bill-agent`) → Vercel.

### Dynamic Rendering Logic:
1. **Dynamic Invoices Fetch:**
   * Queries Supabase: `/rest/v1/invoices?customer_id=eq.${orgId}&order=created_at.desc`.
   * Filters out internal `Google Mail Verification` events.
   * Reads dynamic `overcharge_amount`, `clause`, `origin`, and `dest` directly from `parsed_json`.
2. **Dispute Tracker & Recovery Report:**
   * Dynamically constructs `state.disputes` from all flagged invoices.
   * Automatically sets dispute category (`RATE`, `ACCESSORIAL`, `CLASSIFICATION`).
   * Populates carrier dispute email (`billing@gswfreight.com`, `accounts@vanguard-logistics.com`, `billing@zenith-logistics.com`).
3. **KPI Engine:**
   * **Gross Recoverable:** Sum of all invoice overcharges.
   * **Broker Net Recovery:** Exactly 65% of gross recoverable (`totalRecoverable * 0.65`).
   * **Contingency Fee:** Exactly 35% of gross recoverable (`totalRecoverable * 0.35`).
   * **Open Disputes:** Count of flagged bills.
4. **Dynamic Carrier Breakdown & Activity:**
   * Builds `state.carrierSummary` and `state.recentActivity` dynamically from real bills.
5. **Client-Side Upload Fallback:**
   * Replaced static `$135.25` fallback with dynamic carrier/invoice parsing.

---

## 6. Current Database State & Audited Invoices

Organization: `KRISHNA FREIGHT BROKER` (`57e87372-2586-4283-b647-890b8ce85c37`)

| Carrier | Invoice # | PRO # | Billed Total | Overcharge | Tariff / Audit Clause | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **GSW Freight System, Inc.** | `99182301` | `042-991823` | $1,117.08 | **+$135.25** | Deficit weight bumping under Tariff Item 100-D | `flagged` |
| **Vanguard Logistics** | `INV-2026-0882` | `77412-DX` | $2,800.00 | **+$225.00** | Detention Charges Billing Error (3 hrs @ $75.00/hr) | `flagged` |
| **Zenith Logistics Solutions** | `ZLS-2026-0920-8942` | `ZLS-0920-8942` | $2,538.10 | **+$272.50** | Unauthorized NMFC Re-classification (CL 85 → 110: $187.50) + Weight & Research Fee ($85.00) | `flagged` |
| **Zenith Logistics (Revised)** | `ZLS-2026-0920-8942-REV` | `ZLS-0920-8942-REV` | $1,068.10 | **+$272.50** | Unauthorized NMFC Re-classification ($187.50) + Weight & Research Fee ($85.00) [With $1,250 duplicate bill credit] | `flagged` |

### Live KPI Totals:
* **Gross Recoverable:** **`$905.25`**
* **Broker Net Recovery (65%):** **`$588.41`**
* **Lexa Contingency Fee (35%):** **`$316.84`**
* **Open Disputes:** **`4 Claims`**

---

## 7. Key Bugs Resolved & Lessons Learned

1. **Hardcoded Fallbacks:**
   * *Bug:* Invoices were defaulting to GSW `$135.25` or Vanguard `$225.00`.
   * *Resolution:* Replaced with dynamic line-item extraction in both Cloudflare Worker and portal mapping.
2. **Cloudflare Worker 10ms CPU Timeout:**
   * *Bug:* 1MB PDF attachments caused worker crashes during stream decoding.
   * *Resolution:* Stream reading capped at 64 KB, reducing execution time to `< 1ms`.
3. **MIME Boundary Regex Bleed:**
   * *Bug:* Raw boundary strings like `boundary="qP6eXnimyn8gA5Q"` matched PRO regex.
   * *Resolution:* Cleaned MIME boundary headers before regex execution.
4. **Gmail Forwarding Verification Silent Drop:**
   * *Bug:* Forwarding verification emails from Google were ignored because they were not invoices.
   * *Resolution:* Built an auto-verification handler that intercepts Google emails, clicks the verification link, and logs the code.
5. **Gmail Spam Filter Block:**
   * *Bug:* Gmail silently ignores forwarding filters on messages landing in the Spam folder.
   * *Resolution:* Added `Never send it to Spam` to the recommended Gmail filter rule.

---

## 8. Data Asset Strategy & Future Capabilities

1. **Proprietary Fine-Tuning Dataset:**
   * Every audited bill builds a domain-specific dataset (line items, discrepancies, carrier-specific errors).
   * Can be used to fine-tune open-source LLMs (Llama 3 / Mistral) for ultra-low-cost, high-precision freight auditing.
2. **Market Intelligence & Benchmarking:**
   * Anonymized, aggregated lane rate intelligence and Carrier Hostility Index (error rates per carrier).
   * Standard enterprise SaaS data clause included in client onboarding agreement.
