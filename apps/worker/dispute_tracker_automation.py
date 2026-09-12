"""
Dispute Status Tracking Automation & Carrier Hostility Analytics (Phase 7.4).
Automates follow-up nudges for unresolved disputes sent >14 days ago and
computes carrier hostility scores based on approval/denial ratios and latency.
"""
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from packages.schemas.models import (
    CarrierAnalyticsReport,
    CarrierHostilityMetrics,
    DisputeReminderNudge,
)


def parse_datetime(dt_str: str) -> datetime:
    """Safely parse ISO datetime string or YYYY-MM-DD string into datetime."""
    clean_str = dt_str.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(clean_str)
    except ValueError:
        return datetime.strptime(dt_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)


def scan_overdue_disputes(
    disputes_list: List[Dict[str, Any]],
    days_threshold: int = 14,
    reference_date: Optional[datetime] = None,
) -> List[DisputeReminderNudge]:
    """
    Scans sent disputes and identifies those pending without carrier response for >= days_threshold days.
    Generates structured DisputeReminderNudge objects with RFC 2368 1-click mailto links.
    """
    ref_dt = reference_date or datetime.now(timezone.utc)
    nudges: List[DisputeReminderNudge] = []

    for disp in disputes_list:
        status = str(disp.get("status", "")).lower()
        if status != "sent":
            continue

        sent_at_str = disp.get("sent_at") or disp.get("updated_at") or disp.get("created_at")
        if not sent_at_str:
            continue

        sent_dt = parse_datetime(str(sent_at_str))

        # Ensure tz-awareness for comparison
        if sent_dt.tzinfo is None:
            sent_dt = sent_dt.replace(tzinfo=timezone.utc)
        if ref_dt.tzinfo is None:
            ref_dt = ref_dt.replace(tzinfo=timezone.utc)

        days_since_sent = max(0, (ref_dt - sent_dt).days)

        if days_since_sent >= days_threshold:
            pro_number = disp.get("pro_number", "UNKNOWN")
            carrier = disp.get("carrier", "Carrier")
            carrier_email = disp.get("carrier_dispute_email") or disp.get("carrier_email") or "disputes@carrier.com"
            customer_name = disp.get("customer_name") or "Shipper"
            inv_number = disp.get("invoice_number", "N/A")
            overcharge_dollars = disp.get("overcharge_dollars", 0.0)

            subject = f"REMINDER: Unresolved Billing Dispute Notice: PRO #{pro_number}"
            body_text = (
                f"Attention Billing & Overcharge Claims Department ({carrier}),\n\n"
                f"This is a formal follow-up regarding our billing dispute for PRO #{pro_number} "
                f"(Invoice #{inv_number}) submitted on {sent_dt.strftime('%Y-%m-%d')}.\n\n"
                f"It has been {days_since_sent} days since our initial formal notice of overcharge in the amount of "
                f"${overcharge_dollars:.2f}.\n\n"
                f"Please issue the outstanding credit memo immediately to avoid escalation.\n\n"
                f"Sincerely,\n"
                f"Accounts Payable / Freight Audit Dept\n"
                f"{customer_name}\n"
            )

            mailto_link = f"mailto:{urllib.parse.quote(carrier_email)}?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body_text)}"

            nudge = DisputeReminderNudge(
                dispute_id=disp.get("dispute_id") or disp.get("id") or f"disp_{pro_number}",
                invoice_id=disp.get("invoice_id") or f"inv_{pro_number}",
                pro_number=pro_number,
                invoice_number=inv_number,
                carrier=carrier,
                customer_id=disp.get("customer_id", "cust_default"),
                customer_name=customer_name,
                sent_at=sent_dt.strftime("%Y-%m-%d"),
                days_since_sent=days_since_sent,
                days_overdue=days_since_sent,
                overdue_threshold_days=days_threshold,
                overcharge_dollars=overcharge_dollars,
                suggested_action="Send 1-Click Reminder Nudge",
                mailto_reminder_link=mailto_link,
                reminder_mailto_link=mailto_link,
                reminder_subject=subject,
                status="sent",
            )
            nudges.append(nudge)

    return nudges


def compute_carrier_hostility_analytics(
    disputes_list: List[Dict[str, Any]],
    customer_id: str = "cust_default",
    period: str = "all_time",
) -> CarrierAnalyticsReport:
    """
    Computes per-carrier hostility metrics, approval/denial ratios, resolution latency,
    and overall hostility scores for all carriers interacting with the customer.
    """
    carrier_buckets: Dict[str, List[Dict[str, Any]]] = {}
    for disp in disputes_list:
        cname = str(disp.get("carrier", "Unknown Carrier")).strip()
        if cname not in carrier_buckets:
            carrier_buckets[cname] = []
        carrier_buckets[cname].append(disp)

    carrier_metrics_list: List[CarrierHostilityMetrics] = []
    total_recovered_dollars = 0.0
    total_denied_dollars = 0.0

    for carrier_name, carrier_disputes in carrier_buckets.items():
        total_sent = len(carrier_disputes)
        approved_count = 0
        denied_count = 0
        pending_count = 0
        resolution_days_list: List[float] = []

        for disp in carrier_disputes:
            st = str(disp.get("status", "")).lower()
            overcharge_dollars = float(disp.get("overcharge_dollars", 0.0))

            if st in ["credit_issued", "approved", "verified"]:
                approved_count += 1
                total_recovered_dollars += overcharge_dollars
            elif st in ["denied", "rejected", "unrecoverable"]:
                denied_count += 1
                total_denied_dollars += overcharge_dollars
            else:
                pending_count += 1

            # Latency calculation
            sent_at_str = disp.get("sent_at") or disp.get("created_at")
            updated_at_str = disp.get("updated_at") or disp.get("resolved_at")
            if sent_at_str and updated_at_str and st in ["credit_issued", "approved", "denied", "rejected"]:
                s_dt = parse_datetime(str(sent_at_str))
                u_dt = parse_datetime(str(updated_at_str))
                diff_days = max(1.0, float((u_dt - s_dt).days))
                resolution_days_list.append(diff_days)

        approval_rate_pct = round((approved_count / total_sent * 100.0), 2) if total_sent > 0 else 0.0
        denial_rate_pct = round((denied_count / total_sent * 100.0), 2) if total_sent > 0 else 0.0
        avg_res_days = round(sum(resolution_days_list) / len(resolution_days_list), 1) if resolution_days_list else 7.0

        # Hostility Score calculation formula:
        # High denial rate + long resolution latency = higher hostility
        # Hostility Score range 0.0 to 10.0
        hostility_score = round(min(10.0, (denial_rate_pct * 0.08) + (avg_res_days * 0.2)), 2)

        if hostility_score <= 2.0:
            hostility_status = "friendly"
        elif hostility_score <= 5.0:
            hostility_status = "moderate"
        else:
            hostility_status = "hostile"

        metrics = CarrierHostilityMetrics(
            carrier=carrier_name,
            total_disputes=total_sent,
            total_disputes_sent=total_sent,
            approved_count=approved_count,
            disputes_approved=approved_count,
            denied_count=denied_count,
            disputes_denied=denied_count,
            pending_count=pending_count,
            disputes_pending=pending_count,
            approval_rate_pct=approval_rate_pct,
            denial_rate_pct=denial_rate_pct,
            avg_resolution_days=avg_res_days,
            total_recovered_dollars=round(sum(float(d.get("overcharge_dollars", 0.0)) for d in carrier_disputes if str(d.get("status", "")).lower() in ["credit_issued", "approved"]), 2),
            hostility_score=hostility_score,
            hostility_status=hostility_status,
        )
        carrier_metrics_list.append(metrics)

    # Sort carriers by hostility score descending
    carrier_metrics_list.sort(key=lambda m: m.hostility_score, reverse=True)

    highest_hostility = carrier_metrics_list[0].carrier if carrier_metrics_list else None
    lowest_hostility = carrier_metrics_list[-1].carrier if carrier_metrics_list else None

    report_id = f"report_analytics_{customer_id}_{datetime.now(timezone.utc).strftime('%Y%m%d')}"

    return CarrierAnalyticsReport(
        report_id=report_id,
        customer_id=customer_id,
        period=period,
        total_carriers_tracked=len(carrier_metrics_list),
        total_disputes=len(disputes_list),
        total_disputes_analyzed=len(disputes_list),
        overall_denial_rate_pct=round((sum(m.denied_count for m in carrier_metrics_list) / max(1, len(disputes_list))) * 100.0, 2),
        total_recovered_dollars=round(total_recovered_dollars, 2),
        total_denied_dollars=round(total_denied_dollars, 2),
        highest_hostility_carrier=highest_hostility,
        lowest_hostility_carrier=lowest_hostility,
        most_hostile_carrier=highest_hostility,
        carriers=carrier_metrics_list,
        overdue_nudges_count=0,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

