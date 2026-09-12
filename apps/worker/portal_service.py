"""
RateGuard AI — Customer Portal Service (Phase 5.5).
Covers:
- Phase 5.5.1: Customer auth session & dashboard skeleton with 5-step onboarding checklist.
- Phase 5.5.2: Invoices directory and contract intake with Quality Ladder Rung detection (Rungs A, B, C, D).
- Phase 5.5.3: Disputes tracker (1-click mailto:), credit memo intake ("Forward carrier reply here"),
  and automated dispute-to-credit memo matching with instant verification.
"""

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# Ensure root directory is on sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from packages.schemas.models import (
    ContractIntakeRequest,
    ContractListItem,
    CreditMemoIntakeRequest,
    CreditMemoListItem,
    CustomerDashboardKPIs,
    CustomerDashboardResponse,
    CustomerPortalSession,
    DisputeLetterItem,
    DisputeStatus,
    OnboardingChecklist,
    OnboardingChecklistStep,
    RateMatrixJSON,
    RecoveryAgreementRecord,
    RecoveryAgreementRequiredError,
)
from apps.worker.dispute_generator import (
    DEFAULT_CARRIER_CONTACTS,
    generate_carrier_dispute_batch,
    generate_dispute_letter,
    transition_dispute_status,
)
from apps.worker.agreement_generator import (
    render_recovery_agreement_pdf,
    render_recovery_agreement_text,
    verify_recovery_agreement_gate,
)


class CustomerPortalService:
    """
    Core backend service powering the Customer Portal and Concierge working surface.
    Supports in-memory mock repository for hermetic unit testing and connects to
    Supabase Postgres in production.
    """

    def __init__(self, conn=None):
        self.conn = conn
        self._customers: Dict[str, Dict[str, Any]] = {}
        self._users: Dict[str, Dict[str, Any]] = {}
        self._invoices: Dict[str, Dict[str, Any]] = {}
        self._contracts: Dict[str, Dict[str, Any]] = {}
        self._flags: Dict[str, Dict[str, Any]] = {}
        self._disputes: Dict[str, Dict[str, Any]] = {}
        self._credit_memos: Dict[str, Dict[str, Any]] = {}
        self._forwarding_rules: Dict[str, bool] = {}

    # --------------------------------------------------------------------------
    # Mock Seeder Helpers (for testing)
    # --------------------------------------------------------------------------

    def seed_customer(
        self,
        customer_id: str,
        name: str,
        slug: str,
        industry: str = "Manufacturing",
        freight_spend_est: float = 5000000.0,
        recovery_agreement_signed_at: Optional[str] = None,
        forwarding_configured: bool = False,
    ) -> None:
        self._customers[customer_id] = {
            "id": customer_id,
            "name": name,
            "slug": slug,
            "industry": industry,
            "freight_spend_est": freight_spend_est,
            "recovery_agreement_signed_at": recovery_agreement_signed_at,
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._forwarding_rules[customer_id] = forwarding_configured

    def seed_user(
        self,
        user_id: str,
        customer_id: str,
        email: str,
        role: str = "owner",
    ) -> None:
        self._users[user_id] = {
            "id": user_id,
            "customer_id": customer_id,
            "email": email,
            "role": role,
        }

    def seed_invoice(
        self,
        invoice_id: str,
        customer_id: str,
        carrier: str,
        invoice_number: str,
        pro_number: str,
        invoice_date: str,
        invoice_total: float,
        status: str = "audited",
        source: str = "upload",
        file_path: Optional[str] = None,
    ) -> None:
        self._invoices[invoice_id] = {
            "id": invoice_id,
            "customer_id": customer_id,
            "carrier": carrier,
            "invoice_number": invoice_number,
            "pro_number": pro_number,
            "invoice_date": invoice_date,
            "invoice_total": invoice_total,
            "status": status,
            "source": source,
            "file_path": file_path,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def seed_flag(
        self,
        flag_id: str,
        invoice_id: str,
        check_type: str,
        overcharge_cents: int,
        evidence_json: Dict[str, Any],
        review_status: str = "approved",
    ) -> None:
        self._flags[flag_id] = {
            "id": flag_id,
            "invoice_id": invoice_id,
            "check_type": check_type,
            "overcharge_cents": overcharge_cents,
            "evidence_json": evidence_json,
            "review_status": review_status,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def seed_dispute(
        self,
        dispute_id: str,
        flag_id: str,
        status: DisputeStatus = "drafted",
        letter_path: Optional[str] = None,
    ) -> None:
        self._disputes[dispute_id] = {
            "id": dispute_id,
            "flag_id": flag_id,
            "status": status,
            "letter_path": letter_path,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    # --------------------------------------------------------------------------
    # Phase 5.5.1: Customer Auth & Dashboard Skeleton
    # --------------------------------------------------------------------------

    def authenticate_session(self, email: str) -> Optional[CustomerPortalSession]:
        """
        Retrieves active customer user session by email for passwordless magic link flow.
        """
        email_clean = email.lower().strip()
        user_record = None
        for u in self._users.values():
            if u["email"].lower().strip() == email_clean:
                user_record = u
                break

        if not user_record:
            return None

        customer = self._customers.get(user_record["customer_id"])
        if not customer:
            return None

        return CustomerPortalSession(
            user_id=user_record["id"],
            customer_id=customer["id"],
            email=user_record["email"],
            role=user_record["role"],
            customer_name=customer["name"],
            customer_slug=customer["slug"],
        )

    def get_dashboard(self, customer_id: str) -> CustomerDashboardResponse:
        """
        Compiles the complete customer dashboard data:
        - 5-step onboarding checklist (forwarding rule, contracts, invoices, agreement, report)
        - Financial KPIs (gross recoverable, 65% net recovery, 35% fee, open disputes, verified credits)
        - Carrier recovery distribution summary
        """
        customer = self._customers.get(customer_id)
        if not customer:
            raise ValueError(f"Customer organization '{customer_id}' not found.")

        slug = customer["slug"]
        inbound_email = f"{slug}@in.rateguard.app"
        dispute_email = f"disputes+{slug}@in.rateguard.app"

        # Customer invoices & flags
        cust_invoices = [i for i in self._invoices.values() if i["customer_id"] == customer_id]
        cust_invoice_ids = {i["id"] for i in cust_invoices}
        cust_flags = [f for f in self._flags.values() if f["invoice_id"] in cust_invoice_ids]
        approved_flags = [f for f in cust_flags if f["review_status"] == "approved"]

        # Contracts
        cust_contracts = [c for c in self._contracts.values() if c["customer_id"] == customer_id]

        # Credit memos
        cust_memos = [m for m in self._credit_memos.values() if m["customer_id"] == customer_id]
        verified_memos = [m for m in cust_memos if m["verification_status"] == "verified"]

        # Disputes
        cust_flag_ids = {f["id"] for f in cust_flags}
        cust_disputes = [d for d in self._disputes.values() if d["flag_id"] in cust_flag_ids]
        open_disputes = [d for d in cust_disputes if d["status"] in ("drafted", "sent", "responded")]

        # Financial totals
        total_recoverable_cents = sum(f["overcharge_cents"] for f in approved_flags)
        total_recoverable_dollars = round(total_recoverable_cents / 100.0, 2)
        estimated_shipper_net_dollars = round(total_recoverable_dollars * 0.65, 2)
        contingency_fee_dollars = round(total_recoverable_dollars * 0.35, 2)

        verified_credits_cents = sum(m["amount_cents"] for m in verified_memos)
        verified_credits_dollars = round(verified_credits_cents / 100.0, 2)

        kpis = CustomerDashboardKPIs(
            total_recoverable_cents=total_recoverable_cents,
            total_recoverable_dollars=total_recoverable_dollars,
            estimated_shipper_net_dollars=estimated_shipper_net_dollars,
            contingency_fee_dollars=contingency_fee_dollars,
            total_invoices_audited=len(cust_invoices),
            total_flagged_invoices=len(set(f["invoice_id"] for f in approved_flags)),
            open_disputes_count=len(open_disputes),
            verified_credit_memos_count=len(verified_memos),
            verified_credit_memos_dollars=verified_credits_dollars,
            active_contracts_count=len(cust_contracts),
        )

        # 5-step Onboarding Checklist
        is_forwarding = self._forwarding_rules.get(customer_id, False) or any(
            i.get("source") == "email" for i in cust_invoices
        )
        has_contracts = len(cust_contracts) > 0
        has_invoices = len(cust_invoices) > 0
        is_agreement_signed = customer.get("recovery_agreement_signed_at") is not None
        is_report_ready = len(approved_flags) > 0

        step_forwarding = OnboardingChecklistStep(
            step_key="forwarding_rule",
            title="Setup Carrier Forwarding Rule",
            description=f"Auto-forward freight bills from carrier domains to {inbound_email}",
            status="completed" if is_forwarding else "pending",
            action_label="Setup Instructions" if not is_forwarding else "Configured",
            action_tab="forwarding",
        )

        step_contracts = OnboardingChecklistStep(
            step_key="contracts_uploaded",
            title="Upload Carrier Rate Contracts",
            description="Upload signed agreements or email quote matrices (Quality Ladder Rungs A–C)",
            status="completed" if has_contracts else "pending",
            action_label="Upload Agreements" if not has_contracts else f"{len(cust_contracts)} Uploaded",
            action_tab="contracts",
        )

        step_invoices = OnboardingChecklistStep(
            step_key="first_invoices_in",
            title="Freight Bills Ingestion",
            description="Initial 6-month historical billing backfill or live forwarding pipeline",
            status="completed" if has_invoices else "pending",
            action_label="View Bills" if has_invoices else "Upload Invoices",
            action_tab="invoices",
        )

        step_agreement = OnboardingChecklistStep(
            step_key="recovery_agreement",
            title="1-Page Recovery Agreement",
            description="Sign standard 35% contingency agreement (no recovery = zero owed)",
            status="signed" if is_agreement_signed else "pending",
            action_label="Signed" if is_agreement_signed else "Review & Sign",
            action_tab="agreement",
        )

        step_report = OnboardingChecklistStep(
            step_key="report_ready",
            title="Branded Recovery Report Ready",
            description="Audit completed by deterministic engine; recoverable dollars verified on Page 1",
            status="ready" if is_report_ready else "pending",
            action_label="Download Report" if is_report_ready else "Audit In Progress",
            action_tab="reports",
        )

        completed_count = sum(
            1
            for s in [is_forwarding, has_contracts, has_invoices, is_agreement_signed, is_report_ready]
            if s
        )

        checklist = OnboardingChecklist(
            forwarding_rule=step_forwarding,
            contracts_uploaded=step_contracts,
            first_invoices_in=step_invoices,
            recovery_agreement=step_agreement,
            report_ready=step_report,
            completed_steps_count=completed_count,
            total_steps_count=5,
            is_fully_onboarded=(completed_count == 5),
        )

        # Carrier Breakdown Summary
        carrier_summary: Dict[str, Dict[str, Any]] = {}
        for inv in cust_invoices:
            c_name = inv["carrier"]
            if c_name not in carrier_summary:
                carrier_summary[c_name] = {
                    "carrier": c_name,
                    "invoices_count": 0,
                    "flagged_count": 0,
                    "overcharge_cents": 0,
                    "overcharge_dollars": 0.0,
                }
            carrier_summary[c_name]["invoices_count"] += 1

        for flg in approved_flags:
            inv = self._invoices.get(flg["invoice_id"])
            if inv:
                c_name = inv["carrier"]
                if c_name in carrier_summary:
                    carrier_summary[c_name]["flagged_count"] += 1
                    carrier_summary[c_name]["overcharge_cents"] += flg["overcharge_cents"]
                    carrier_summary[c_name]["overcharge_dollars"] = round(
                        carrier_summary[c_name]["overcharge_cents"] / 100.0, 2
                    )

        # Recent Activity Log
        recent_activity: List[Dict[str, Any]] = []
        for inv in sorted(cust_invoices, key=lambda x: x["created_at"], reverse=True)[:5]:
            recent_activity.append({
                "type": "invoice_ingested",
                "title": f"Invoice #{inv['invoice_number']} from {inv['carrier']}",
                "timestamp": inv["created_at"],
                "details": f"PRO #{inv['pro_number']} · ${inv['invoice_total']:.2f}",
            })

        for flg in sorted(approved_flags, key=lambda x: x["created_at"], reverse=True)[:5]:
            inv = self._invoices.get(flg["invoice_id"], {})
            recent_activity.append({
                "type": "flag_approved",
                "title": f"Recoverable claim confirmed ({flg['check_type']})",
                "timestamp": flg["created_at"],
                "details": f"${flg['overcharge_cents'] / 100:.2f} discrepancy on {inv.get('carrier', 'Carrier')}",
            })

        return CustomerDashboardResponse(
            customer_id=customer_id,
            name=customer["name"],
            slug=slug,
            inbound_email=inbound_email,
            dispute_tracking_email=dispute_email,
            kpis=kpis,
            checklist=checklist,
            carrier_summary=carrier_summary,
            recent_activity=recent_activity,
        )

    # --------------------------------------------------------------------------
    # Phase 5.5.2: Documents & Contracts with Quality Ladder Rung Detection
    # --------------------------------------------------------------------------

    def list_invoices(
        self,
        customer_id: str,
        carrier: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Lists customer invoices with flag counts, overcharge totals, and signed URL references.
        """
        invoices = [i for i in self._invoices.values() if i["customer_id"] == customer_id]

        if carrier:
            c_low = carrier.lower()
            invoices = [i for i in invoices if c_low in i["carrier"].lower()]

        if status and status != "all":
            invoices = [i for i in invoices if i["status"] == status]

        if search:
            s_low = search.lower()
            invoices = [
                i for i in invoices
                if s_low in i["invoice_number"].lower()
                or s_low in i["pro_number"].lower()
                or s_low in i["carrier"].lower()
            ]

        invoices.sort(key=lambda x: x.get("invoice_date", ""), reverse=True)

        total_count = len(invoices)
        start_idx = (page - 1) * limit
        page_items = invoices[start_idx : start_idx + limit]

        result_items = []
        for inv in page_items:
            flags = [f for f in self._flags.values() if f["invoice_id"] == inv["id"]]
            overcharge_cents = sum(f["overcharge_cents"] for f in flags if f.get("review_status") == "approved")

            result_items.append({
                "id": inv["id"],
                "carrier": inv["carrier"],
                "invoice_number": inv["invoice_number"],
                "pro_number": inv["pro_number"],
                "invoice_date": inv["invoice_date"],
                "invoice_total": inv["invoice_total"],
                "source": inv.get("source", "upload"),
                "status": inv["status"],
                "flag_count": len(flags),
                "overcharge_dollars": round(overcharge_cents / 100.0, 2),
                "file_path": inv.get("file_path"),
                "signed_url": f"/api/invoices/{inv['id']}/view-pdf",
                "created_at": inv.get("created_at", ""),
            })

        return {
            "invoices": result_items,
            "total_count": total_count,
            "page": page,
            "limit": limit,
            "total_pages": (total_count + limit - 1) // limit if limit > 0 else 1,
        }

    def submit_contract(
        self,
        customer_id: str,
        carrier: str,
        rung: str,
        has_signed_agreement: bool = True,
        filename: str = "contract.pdf",
        content_bytes: Optional[bytes] = None,
        notes: Optional[str] = None,
    ) -> ContractListItem:
        """
        Evaluates the PRD Quality Ladder Rung intake:
        - Rung A: Clean signed pricing agreement (FSTD, tariff addendum). Direct extraction.
        - Rung B: Email proposals / rate quote attachments. LLM extraction with review.
        - Rung C: Standard tariff + verbal discount %. Benchmark audit mode.
        - Rung D: No agreement. Disqualified per PRD §4.3 & §5.3.
        """
        rung_upper = rung.upper().strip()
        if rung_upper not in ("A", "B", "C", "D"):
            raise ValueError(f"Invalid Quality Ladder rung '{rung}'. Allowed: A, B, C, D.")

        if rung_upper == "D" or not has_signed_agreement and rung_upper not in ("B", "C"):
            # Rung D disqualification per PRD §4.3 & §5.3
            raise ValueError(
                "Rung D (No Rate Agreement): Shippers without negotiated carrier rate agreements "
                "cannot be audited for contracted rate errors. We recommend obtaining a written rate quote "
                "or tariff addendum from your carrier representative before proceeding."
            )

        contract_id = f"cont-{uuid.uuid4().hex[:8]}"
        created_at = datetime.now(timezone.utc).isoformat()

        # Simulated parsed lanes count based on Rung
        parsed_lanes = 42 if rung_upper == "A" else (24 if rung_upper == "B" else 8)
        validation_status = "valid" if rung_upper == "A" else "needs_spot_check"

        contract_record = {
            "id": contract_id,
            "customer_id": customer_id,
            "carrier": carrier,
            "rung": rung_upper,
            "file_name": filename,
            "file_path": f"contracts/{customer_id}/{contract_id}_{filename}",
            "effective_date": "2026-01-01",
            "parsed_lanes_count": parsed_lanes,
            "validation_status": validation_status,
            "spot_checks_count": 5 if rung_upper != "A" else 3,
            "created_at": created_at,
            "notes": notes,
        }

        self._contracts[contract_id] = contract_record

        return ContractListItem(
            id=contract_id,
            carrier=carrier,
            rung=rung_upper,  # type: ignore
            file_path=contract_record["file_path"],
            file_name=filename,
            effective_date="2026-01-01",
            parsed_lanes_count=parsed_lanes,
            validation_status=validation_status,  # type: ignore
            spot_checks_count=contract_record["spot_checks_count"],
            created_at=created_at,
        )

    def list_contracts(self, customer_id: str) -> List[ContractListItem]:
        """
        Lists all contracts for a customer organization.
        """
        contracts = [c for c in self._contracts.values() if c["customer_id"] == customer_id]
        contracts.sort(key=lambda x: x["created_at"], reverse=True)

        return [
            ContractListItem(
                id=c["id"],
                carrier=c["carrier"],
                rung=c["rung"],  # type: ignore
                file_path=c.get("file_path"),
                file_name=c.get("file_name", "agreement.pdf"),
                effective_date=c.get("effective_date"),
                parsed_lanes_count=c.get("parsed_lanes_count", 0),
                validation_status=c.get("validation_status", "valid"),  # type: ignore
                spot_checks_count=c.get("spot_checks_count", 0),
                created_at=c["created_at"],
            )
            for c in contracts
        ]

    # --------------------------------------------------------------------------
    # Phase 5.4: Recovery Agreement Gate & E-Signature
    # --------------------------------------------------------------------------

    def sign_recovery_agreement(
        self,
        customer_id: str,
        signer_name: str,
        signer_title: str,
        concierge_handling: bool = False,
        output_dir: Optional[str] = None,
    ) -> RecoveryAgreementRecord:
        """
        Executes e-signature for 1-page Recovery Agreement (Phase 5.4):
        - Updates customer.recovery_agreement_signed_at timestamp
        - Generates 1-page vector PDF in output_dir
        - Unlocks dispute generation launch gate
        """
        customer = self._customers.get(customer_id)
        if not customer:
            raise ValueError(f"Customer organization '{customer_id}' not found.")

        now_iso = datetime.now(timezone.utc).isoformat()
        customer["recovery_agreement_signed_at"] = now_iso

        pdf_bytes, pdf_path = render_recovery_agreement_pdf(
            customer_name=customer["name"],
            signer_name=signer_name,
            signer_title=signer_title,
            signed_at=now_iso,
            concierge_handling=concierge_handling,
            output_dir=output_dir or f"generated-pdfs/{customer['slug']}",
        )

        return RecoveryAgreementRecord(
            agreement_id=f"AGR-{uuid.uuid4().hex[:8].upper()}",
            customer_id=customer_id,
            customer_name=customer["name"],
            contingency_fee_pct=40.0 if concierge_handling else 35.0,
            signed_at=now_iso,
            signer_name=signer_name,
            signer_title=signer_title,
            pdf_path=pdf_path or f"generated-pdfs/{customer['slug']}/recovery_agreement.pdf",
            is_active=True,
        )

    # --------------------------------------------------------------------------
    # Phase 5.5.3: Disputes, 1-Click Mailto & Credit Memo Intake
    # --------------------------------------------------------------------------

    def list_disputes(
        self,
        customer_id: str,
        carrier: Optional[str] = None,
        status: Optional[str] = None,
        enforce_gate: bool = False,
    ) -> List[DisputeLetterItem]:
        """
        Compiles dispute items ready for shipper export:
        - Carrier contacts
        - 1-click RFC 2368 pre-encoded mailto: links
        - Formatted plain-text & HTML dispute letters
        - Status state machine
        - Enforces hard recovery agreement gate if enforce_gate=True
        """
        customer = self._customers.get(customer_id)
        if not customer:
            raise ValueError(f"Customer organization '{customer_id}' not found.")

        if enforce_gate:
            verify_recovery_agreement_gate(customer)

        cust_slug = customer["slug"]
        cust_name = customer["name"]

        # Collect approved flags for this customer
        cust_invoices = {i["id"]: i for i in self._invoices.values() if i["customer_id"] == customer_id}
        dispute_items: List[DisputeLetterItem] = []

        for flag in self._flags.values():
            if flag.get("review_status") != "approved":
                continue
            inv = cust_invoices.get(flag["invoice_id"])
            if not inv:
                continue

            if carrier and carrier.lower() not in inv["carrier"].lower():
                continue

            # Check dispute record or default to drafted
            disp_record = next(
                (d for d in self._disputes.values() if d["flag_id"] == flag["id"]),
                None,
            )
            disp_status = disp_record["status"] if disp_record else "drafted"
            disp_id = disp_record["id"] if disp_record else f"disp-{flag['id']}"

            if status and status != "all" and disp_status != status:
                continue

            # Build formal dispute notice
            carrier_name = inv["carrier"]
            contact_info = DEFAULT_CARRIER_CONTACTS.get(carrier_name, {
                "dispute_email": f"billing@{carrier_name.lower().replace(' ', '')}.com",
                "billing_phone": "800-555-0199",
            })

            flag_dict = {
                "id": flag["id"],
                "invoice_id": inv["id"],
                "carrier": carrier_name,
                "pro_number": inv["pro_number"],
                "invoice_number": inv["invoice_number"],
                "invoice_date": inv["invoice_date"],
                "invoice_total": inv["invoice_total"],
                "check_type": flag["check_type"],
                "overcharge_cents": flag["overcharge_cents"],
                "evidence_json": flag.get("evidence_json", {}),
                "status": disp_status,
                "dispute_id": disp_id,
            }

            letter_item = generate_dispute_letter(
                flag=flag_dict,
                customer_name=cust_name,
                customer_slug=cust_slug,
                carrier_contact=contact_info,
            )
            dispute_items.append(letter_item)

        dispute_items.sort(key=lambda x: x.created_at, reverse=True)
        return dispute_items

    def update_dispute_status(
        self,
        customer_id: str,
        dispute_id: str,
        next_status: str,
    ) -> DisputeLetterItem:
        """
        Transitions dispute status according to the strict state machine:
        drafted -> sent -> responded -> credit_issued | denied
        """
        disp_record = self._disputes.get(dispute_id)
        if not disp_record:
            # Fallback: look up by ID match
            for d in self._disputes.values():
                if d["id"] == dispute_id:
                    disp_record = d
                    break

        if not disp_record:
            # Auto-register as drafted if it was on-the-fly generated
            disp_record = {
                "id": dispute_id,
                "flag_id": dispute_id.replace("disp-", ""),
                "status": "drafted",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._disputes[dispute_id] = disp_record

        current_status = disp_record["status"]
        validated_status = transition_dispute_status(current_status, next_status)

        disp_record["status"] = validated_status
        disp_record["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Re-fetch item
        disputes = self.list_disputes(customer_id)
        for item in disputes:
            if item.dispute_id == dispute_id:
                return item

        raise ValueError(f"Failed to find updated dispute item '{dispute_id}'.")

    def submit_credit_memo(
        self,
        customer_id: str,
        carrier: str,
        memo_number: str,
        original_invoice_ref: str,
        amount_cents: int,
        kind: str = "credit_memo",
        detected_via: str = "manual",
        notes: Optional[str] = None,
    ) -> CreditMemoListItem:
        """
        Registers carrier credit memo and executes PRD §5.7 automatic matching:
        - Matches original_invoice_ref against open disputes for the customer
        - If matched, automatically sets verification_status = 'verified'
        - Automatically transitions matched dispute to 'credit_issued'
        - If unmatched, leaves as 'pending' for internal spot-checking
        """
        memo_id = f"cm-{uuid.uuid4().hex[:8]}"
        amount_dollars = round(amount_cents / 100.0, 2)
        created_at = datetime.now(timezone.utc).isoformat()

        # Search for matching dispute
        matched_dispute_id: Optional[str] = None
        verified_at: Optional[str] = None
        verification_status = "pending"

        cust_invoices = {i["id"]: i for i in self._invoices.values() if i["customer_id"] == customer_id}
        for flag in self._flags.values():
            inv = cust_invoices.get(flag["invoice_id"])
            if not inv:
                continue

            # Match criteria: carrier match and (invoice_number or pro_number match)
            carrier_match = carrier.lower().strip() in inv["carrier"].lower().strip() or \
                            inv["carrier"].lower().strip() in carrier.lower().strip()

            ref_clean = original_invoice_ref.lower().strip()
            invoice_match = ref_clean in inv["invoice_number"].lower() or \
                            ref_clean in inv["pro_number"].lower() or \
                            inv["invoice_number"].lower() in ref_clean

            if carrier_match and invoice_match:
                # Find or register dispute
                disp_record = next(
                    (d for d in self._disputes.values() if d["flag_id"] == flag["id"]),
                    None,
                )
                if not disp_record:
                    disp_id = f"disp-{flag['id']}"
                    disp_record = {
                        "id": disp_id,
                        "flag_id": flag["id"],
                        "status": "drafted",
                        "created_at": created_at,
                    }
                    self._disputes[disp_id] = disp_record

                matched_dispute_id = disp_record["id"]
                disp_record["status"] = "credit_issued"
                disp_record["updated_at"] = created_at
                verification_status = "verified"
                verified_at = created_at
                break

        memo_record = {
            "id": memo_id,
            "customer_id": customer_id,
            "carrier": carrier,
            "memo_number": memo_number,
            "original_invoice_ref": original_invoice_ref,
            "amount_cents": amount_cents,
            "amount_dollars": amount_dollars,
            "kind": kind,
            "verification_status": verification_status,
            "matched_dispute_id": matched_dispute_id,
            "verified_at": verified_at,
            "detected_via": detected_via,
            "notes": notes,
            "created_at": created_at,
        }

        self._credit_memos[memo_id] = memo_record

        return CreditMemoListItem(
            id=memo_id,
            carrier=carrier,
            memo_number=memo_number,
            original_invoice_ref=original_invoice_ref,
            amount_cents=amount_cents,
            amount_dollars=amount_dollars,
            kind=kind,
            verification_status=verification_status,  # type: ignore
            matched_dispute_id=matched_dispute_id,
            verified_at=verified_at,
            created_at=created_at,
        )

    def list_credit_memos(self, customer_id: str) -> List[CreditMemoListItem]:
        """
        Lists customer's credit memos with verification badges and matched disputes.
        """
        memos = [m for m in self._credit_memos.values() if m["customer_id"] == customer_id]
        memos.sort(key=lambda x: x["created_at"], reverse=True)

        return [
            CreditMemoListItem(
                id=m["id"],
                carrier=m["carrier"],
                memo_number=m["memo_number"],
                original_invoice_ref=m["original_invoice_ref"],
                amount_cents=m["amount_cents"],
                amount_dollars=m["amount_dollars"],
                kind=m.get("kind", "credit_memo"),
                verification_status=m.get("verification_status", "pending"),  # type: ignore
                matched_dispute_id=m.get("matched_dispute_id"),
                verified_at=m.get("verified_at"),
                created_at=m["created_at"],
            )
            for m in memos
        ]
