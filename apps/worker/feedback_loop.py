"""
RateGuard AI — Reason-Code Feedback Loop & Precision Engine (Phase 4.2).
Transforms human review rejections and reason codes into continuous precision improvement.

Core Responsibilities:
1. Computes post-review precision: Approved / (Approved + Rejected) overall, per carrier, and per check type.
2. Benchmarks against the PRD §10 trajectory: >=90% (Pilot Gate) -> >=95% (Scale Target) -> >=98% (Enterprise Target).
3. Evaluates top reason codes from the 8-code taxonomy and generates prioritized Parser/Prompt fix tickets.
4. Produces structured Monthly Retrospective Reports (MonthlyRetroReport).
"""
from datetime import datetime, timezone
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple
import uuid

root_dir = Path(__file__).resolve().parent.parent.parent
audit_engine_dir = root_dir / "packages" / "audit-engine"
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))
if str(audit_engine_dir) not in sys.path:
    sys.path.insert(0, str(audit_engine_dir))

from packages.schemas.models import (
    FeedbackTicket,
    MonthlyRetroReport,
    PrecisionReportItem,
)
from validation import STANDARD_REASON_CODES

logger = logging.getLogger("rateguard.feedback_loop")

# Rule mapping from reason codes to pipeline components and recommended remediation
TAXONOMY_REMEDIATION_MAP: Dict[str, Dict[str, str]] = {
    "wrong-matrix-row": {
        "category": "contract_parser",
        "action": "Audit ContractParser RateMatrixJSON generation. Verify 3-digit vs 5-digit zip prefix lane priority, FAK class mapping, and weight break tier order.",
    },
    "misread-pdf-field": {
        "category": "invoice_parser",
        "action": "Calibrate InvoiceParser LLM prompt extraction and OCR bounding boxes for PRO#, linehaul total, and fuel surcharge currency fields.",
    },
    "contract-exception-misapplied": {
        "category": "contract_parser",
        "action": "Refine contractual rider and exception extraction in ContractParser Quality Ladder Rungs A & B.",
    },
    "not-an-error": {
        "category": "audit_engine",
        "action": "Review deterministic audit rules; verify carrier tariff baseline rules and customer-specific negotiated exclusions.",
    },
    "duplicate-false-positive": {
        "category": "audit_engine",
        "action": "Tighten check_duplicates time window; verify BOL matching requirements and carrier PRO re-use rules.",
    },
    "fsc-table-wrong-month": {
        "category": "fsc_engine",
        "action": "Audit FSCTable and EIA benchmark alignment. Verify Monday DOE benchmark price windowing and carrier monthly lag rules.",
    },
    "rate-effective-date-mismatch": {
        "category": "contract_parser",
        "action": "Verify rate_matrices effective date windows. Ensure annual GRI amendments do not audit out-of-scope historical invoices.",
    },
    "other": {
        "category": "audit_engine",
        "action": "Manual engineering investigation of ad-hoc rejection notes in review_events.",
    },
}


def compute_precision_score(approved: int, rejected: int) -> float:
    """
    Computes human review precision percentage: Approved / (Approved + Rejected).
    Returns 0.0 if no reviews have been finalized.
    """
    total = approved + rejected
    if total <= 0:
        return 0.0
    return round((approved / total) * 100.0, 1)


def evaluate_trajectory_status(precision: float, total_reviewed: int) -> str:
    """
    Evaluates precision against the PRD §10 quality ladder:
    - >= 98%: ENTERPRISE_MET
    - >= 95%: SCALE_TARGET_MET
    - >= 90%: PILOT_GATE_PASSED
    - < 90%: BELOW_TARGET
    """
    if total_reviewed <= 0:
        return "NO_REVIEWS_RECORDED"
    if precision >= 98.0:
        return "ENTERPRISE_MET"
    elif precision >= 95.0:
        return "SCALE_TARGET_MET"
    elif precision >= 90.0:
        return "PILOT_GATE_PASSED"
    else:
        return "BELOW_TARGET"


class FeedbackLoopService:
    """
    Service for calculating precision analytics, generating parser/prompt tickets,
    and conducting monthly review retrospectives.
    """

    def __init__(self, db_client: Any = None):
        self.db_client = db_client
        # In-memory store for unit tests without database dependency
        self._mock_flags: List[Dict[str, Any]] = []

    def seed_mock_flags(self, flags: List[Dict[str, Any]]):
        """Seeds mock flags for in-memory testing."""
        self._mock_flags = flags

    def get_precision_analytics(
        self,
        month: Optional[str] = None,
        customer_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Calculates precision metrics:
        - Overall precision
        - Precision by check type (RATE, FSC, DUP, ARITH)
        - Precision by carrier (ABF Freight, XPO Logistics, Roadrunner)
        """
        flags = self._load_flags(month=month, customer_id=customer_id)

        # Overall counters
        overall_approved = 0
        overall_rejected = 0
        overall_pending = 0
        overall_research = 0

        # Grouped counters: check_type -> {approved, rejected, pending, research}
        by_check: Dict[str, Dict[str, int]] = {}
        # Grouped counters: carrier -> {approved, rejected, pending, research}
        by_carrier: Dict[str, Dict[str, int]] = {}

        for f in flags:
            st = f.get("review_status", "pending")
            ctype = f.get("check_type", "UNKNOWN")
            carrier = f.get("carrier") or (f.get("invoices") or {}).get("carrier", "Unknown")

            # Initialize dicts if needed
            if ctype not in by_check:
                by_check[ctype] = {"approved": 0, "rejected": 0, "pending": 0, "research": 0}
            if carrier not in by_carrier:
                by_carrier[carrier] = {"approved": 0, "rejected": 0, "pending": 0, "research": 0}

            if st == "approved":
                overall_approved += 1
                by_check[ctype]["approved"] += 1
                by_carrier[carrier]["approved"] += 1
            elif st == "rejected":
                overall_rejected += 1
                by_check[ctype]["rejected"] += 1
                by_carrier[carrier]["rejected"] += 1
            elif st == "research":
                overall_research += 1
                by_check[ctype]["research"] += 1
                by_carrier[carrier]["research"] += 1
            else:
                overall_pending += 1
                by_check[ctype]["pending"] += 1
                by_carrier[carrier]["pending"] += 1

        # Format overall
        total_reviewed = overall_approved + overall_rejected
        overall_prec = compute_precision_score(overall_approved, overall_rejected)
        overall_item = PrecisionReportItem(
            category="overall",
            name="OVERALL",
            approved_count=overall_approved,
            rejected_count=overall_rejected,
            pending_count=overall_pending,
            research_count=overall_research,
            total_reviewed=total_reviewed,
            precision_pct=overall_prec,
            meets_pilot_target=overall_prec >= 90.0 and total_reviewed > 0,
            meets_scale_target=overall_prec >= 95.0 and total_reviewed > 0,
            meets_enterprise_target=overall_prec >= 98.0 and total_reviewed > 0,
        )

        # Format by check type
        check_items: Dict[str, PrecisionReportItem] = {}
        for ctype, counts in by_check.items():
            rev = counts["approved"] + counts["rejected"]
            prec = compute_precision_score(counts["approved"], counts["rejected"])
            check_items[ctype] = PrecisionReportItem(
                category="check_type",
                name=ctype,
                approved_count=counts["approved"],
                rejected_count=counts["rejected"],
                pending_count=counts["pending"],
                research_count=counts["research"],
                total_reviewed=rev,
                precision_pct=prec,
                meets_pilot_target=prec >= 90.0 and rev > 0,
                meets_scale_target=prec >= 95.0 and rev > 0,
                meets_enterprise_target=prec >= 98.0 and rev > 0,
            )

        # Format by carrier
        carrier_items: Dict[str, PrecisionReportItem] = {}
        for carr, counts in by_carrier.items():
            rev = counts["approved"] + counts["rejected"]
            prec = compute_precision_score(counts["approved"], counts["rejected"])
            carrier_items[carr] = PrecisionReportItem(
                category="carrier",
                name=carr,
                approved_count=counts["approved"],
                rejected_count=counts["rejected"],
                pending_count=counts["pending"],
                research_count=counts["research"],
                total_reviewed=rev,
                precision_pct=prec,
                meets_pilot_target=prec >= 90.0 and rev > 0,
                meets_scale_target=prec >= 95.0 and rev > 0,
                meets_enterprise_target=prec >= 98.0 and rev > 0,
            )

        return {
            "overall": overall_item,
            "by_check_type": check_items,
            "by_carrier": carrier_items,
            "trajectory_status": evaluate_trajectory_status(overall_prec, total_reviewed),
        }

    def generate_fix_tickets(
        self,
        month: Optional[str] = None,
        min_rejections: int = 1,
    ) -> List[FeedbackTicket]:
        """
        Groups rejections by reason code and converts them into structured engineering
        fix tickets prioritized by volume and pipeline component.
        """
        flags = self._load_flags(month=month)
        rejection_groups: Dict[str, Dict[str, Any]] = {}
        total_rejections = 0

        for f in flags:
            if f.get("review_status") != "rejected":
                continue

            reason_code = f.get("reject_reason_code") or "other"
            reason_code = reason_code.strip().lower()
            carrier = f.get("carrier") or (f.get("invoices") or {}).get("carrier", "Unknown")
            ctype = f.get("check_type", "UNKNOWN")
            flag_id = f.get("id", str(uuid.uuid4()))

            total_rejections += 1
            if reason_code not in rejection_groups:
                rejection_groups[reason_code] = {
                    "count": 0,
                    "carriers": {},
                    "check_types": {},
                    "flag_ids": [],
                }

            group = rejection_groups[reason_code]
            group["count"] += 1
            group["flag_ids"].append(flag_id)
            group["carriers"][carrier] = group["carriers"].get(carrier, 0) + 1
            group["check_types"][ctype] = group["check_types"].get(ctype, 0) + 1

        # Build prioritized tickets
        tickets: List[FeedbackTicket] = []
        # Sort reason codes by frequency descending
        sorted_codes = sorted(rejection_groups.items(), key=lambda x: x[1]["count"], reverse=True)

        for code, data in sorted_codes:
            cnt = data["count"]
            if cnt < min_rejections:
                continue

            pct = round((cnt / total_rejections) * 100.0, 1) if total_rejections > 0 else 0.0

            # Priority calculation
            if cnt >= 5 or pct >= 30.0:
                priority = "HIGH"
            elif cnt >= 2 or pct >= 15.0:
                priority = "MEDIUM"
            else:
                priority = "LOW"

            remedy = TAXONOMY_REMEDIATION_MAP.get(code, TAXONOMY_REMEDIATION_MAP["other"])
            category = remedy["category"]
            action = remedy["action"]

            # Predominant carrier and check type
            top_carrier = max(data["carriers"], key=data["carriers"].get) if data["carriers"] else None
            top_ctype = max(data["check_types"], key=data["check_types"].get) if data["check_types"] else None

            ticket = FeedbackTicket(
                ticket_id=f"TICKET-{category.upper()}-{code.replace('-', '_').upper()}",
                reason_code=code,
                rejection_count=cnt,
                percentage_of_rejections=pct,
                category=category,
                priority=priority,
                affected_carrier=top_carrier,
                affected_check_type=top_ctype,
                recommended_action=action,
                sample_flag_ids=data["flag_ids"][:5],  # Sample up to 5 IDs
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            tickets.append(ticket)

        return tickets

    def run_monthly_retro(
        self,
        month: Optional[str] = None,
    ) -> MonthlyRetroReport:
        """
        Executes the monthly retrospective job:
        1. Queries precision analytics.
        2. Compiles reason-code frequency ranking.
        3. Generates engineering tickets for top failure modes.
        4. Outputs structured MonthlyRetroReport.
        """
        report_month = month or datetime.now(timezone.utc).strftime("%Y-%m")
        analytics = self.get_precision_analytics(month=report_month)
        overall: PrecisionReportItem = analytics["overall"]
        tickets = self.generate_fix_tickets(month=report_month)

        # Ranked reason codes
        flags = self._load_flags(month=report_month)
        reason_counts: Dict[str, int] = {}
        total_rej = 0
        for f in flags:
            if f.get("review_status") == "rejected":
                code = f.get("reject_reason_code") or "other"
                reason_counts[code] = reason_counts.get(code, 0) + 1
                total_rej += 1

        top_reason_codes = []
        for code, count in sorted(reason_counts.items(), key=lambda x: x[1], reverse=True):
            top_reason_codes.append({
                "code": code,
                "count": count,
                "percentage": round((count / total_rej) * 100.0, 1) if total_rej > 0 else 0.0,
            })

        return MonthlyRetroReport(
            month=report_month,
            total_flags_reviewed=overall.total_reviewed,
            total_approved=overall.approved_count,
            total_rejected=overall.rejected_count,
            overall_precision_pct=overall.precision_pct,
            trajectory_status=analytics["trajectory_status"],
            precision_by_check_type=analytics["by_check_type"],
            precision_by_carrier=analytics["by_carrier"],
            top_reason_codes=top_reason_codes,
            generated_tickets=tickets,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def _load_flags(
        self,
        month: Optional[str] = None,
        customer_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Loads flags from DB or in-memory list with optional month/customer filters."""
        if self.db_client:
            try:
                query = self.db_client.table("flags").select(
                    "id, check_type, overcharge_cents, review_status, reject_reason_code, reviewed_at, created_at, invoices(carrier, customer_id, invoice_date)"
                )
                res = query.execute()
                if res.data:
                    filtered = []
                    for row in res.data:
                        inv = row.get("invoices") or {}
                        if customer_id and inv.get("customer_id") != customer_id:
                            continue
                        if month:
                            # Match reviewed_at or invoice_date prefix YYYY-MM
                            rev_at = row.get("reviewed_at") or row.get("created_at") or inv.get("invoice_date") or ""
                            if not rev_at.startswith(month):
                                continue
                        row["carrier"] = inv.get("carrier", "Unknown")
                        filtered.append(row)
                    return filtered
            except Exception as e:
                logger.warning(f"Error querying flags from DB: {e}")

        # Fallback to in-memory flags
        filtered = []
        for f in self._mock_flags:
            if customer_id and f.get("customer_id") != customer_id:
                continue
            if month:
                dt = f.get("reviewed_at") or f.get("created_at") or f.get("invoice_date") or ""
                if not dt.startswith(month):
                    continue
            filtered.append(f)
        return filtered


def format_retro_markdown(report: MonthlyRetroReport) -> str:
    """Formats a MonthlyRetroReport into human-readable Markdown for team retrospectives."""
    md = [
        f"# RateGuard AI — Monthly Precision Retrospective ({report.month})",
        f"**Generated:** {report.generated_at} | **Status:** `{report.trajectory_status}`",
        "",
        "## 1. Executive Quality Scoreboard",
        f"- **Total Reviewed Flags:** {report.total_flags_reviewed}",
        f"- **Approved (Staged for Recovery):** {report.total_approved}",
        f"- **Rejected (False Flags Caught):** {report.total_rejected}",
        f"- **Post-Review Precision:** **{report.overall_precision_pct}%** (PRD §10 Target: ≥90.0% Pilot / ≥95.0% Scale / ≥98.0% Enterprise)",
        "",
        "## 2. Precision by Check Type",
        "| Check Type | Approved | Rejected | Total | Precision | Pilot Gate (≥90%) |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for ctype, item in report.precision_by_check_type.items():
        gate_str = "PASSED" if item.meets_pilot_target else "BELOW"
        md.append(f"| **{ctype}** | {item.approved_count} | {item.rejected_count} | {item.total_reviewed} | {item.precision_pct}% | `{gate_str}` |")

    md.extend([
        "",
        "## 3. Precision by Carrier",
        "| Carrier | Approved | Rejected | Total | Precision | Pilot Gate (≥90%) |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    for carr, item in report.precision_by_carrier.items():
        gate_str = "PASSED" if item.meets_pilot_target else "BELOW"
        md.append(f"| **{carr}** | {item.approved_count} | {item.rejected_count} | {item.total_reviewed} | {item.precision_pct}% | `{gate_str}` |")

    md.extend([
        "",
        "## 4. Top Rejection Reason Codes (Failure Modes)",
        "| Reason Code | Count | % of Rejections | Primary Component |",
        "| :--- | :--- | :--- | :--- |",
    ])

    for r in report.top_reason_codes:
        remedy = TAXONOMY_REMEDIATION_MAP.get(r["code"], TAXONOMY_REMEDIATION_MAP["other"])
        md.append(f"| `{r['code']}` | {r['count']} | {r['percentage']}% | `{remedy['category']}` |")

    md.extend([
        "",
        "## 5. Prioritized Engineering Action Tickets",
    ])

    if not report.generated_tickets:
        md.append("*(No rejections recorded; zero tickets generated.)*")
    else:
        for t in report.generated_tickets:
            md.extend([
                f"### [{t.priority}] {t.ticket_id}",
                f"- **Reason Code:** `{t.reason_code}` ({t.rejection_count} rejections, {t.percentage_of_rejections}%)",
                f"- **Component:** `{t.category}` | **Carrier:** {t.affected_carrier or 'Multiple'} | **Check:** {t.affected_check_type or 'Multiple'}",
                f"- **Action:** {t.recommended_action}",
                f"- **Sample Flags:** {', '.join(t.sample_flag_ids)}",
                "",
            ])

    return "\n".join(md)
