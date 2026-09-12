import {
  CarrierAnalyticsReport,
  CarrierHostilityMetrics,
  DisputeReminderNudge,
} from '../../../packages/schemas';

export interface DisputeRecord {
  id: string;
  dispute_id?: string;
  invoice_id: string;
  customer_id: string;
  customer_name?: string;
  carrier: string;
  carrier_dispute_email?: string;
  pro_number: string;
  invoice_number: string;
  overcharge_dollars: number;
  status: 'drafted' | 'sent' | 'responded' | 'credit_issued' | 'denied';
  sent_at?: string;
  updated_at?: string;
  created_at: string;
}

export class DisputeAutomationAPIService {
  private disputes: DisputeRecord[] = [];

  constructor(initialDisputes: DisputeRecord[] = []) {
    this.disputes = initialDisputes;
  }

  public setDisputes(disputes: DisputeRecord[]): void {
    this.disputes = disputes;
  }

  public getOverdueDisputeNudges(
    customerId: string,
    daysThreshold: number = 14,
    referenceDateStr?: string
  ): DisputeReminderNudge[] {
    const refDate = referenceDateStr ? new Date(referenceDateStr) : new Date();

    const customerDisputes = this.disputes.filter(
      (d) => d.customer_id === customerId && d.status === 'sent'
    );

    const nudges: DisputeReminderNudge[] = [];

    for (const disp of customerDisputes) {
      const sentDateStr = disp.sent_at || disp.updated_at || disp.created_at;
      const sentDate = new Date(sentDateStr);
      const diffMs = refDate.getTime() - sentDate.getTime();
      const daysSinceSent = Math.max(0, Math.floor(diffMs / (1000 * 60 * 60 * 24)));

      if (daysSinceSent >= daysThreshold) {
        const carrierEmail = disp.carrier_dispute_email || `disputes@${disp.carrier.toLowerCase().replace(/\s+/g, '')}.com`;
        const customerName = disp.customer_name || 'Shipper';
        const subject = `REMINDER: Unresolved Billing Dispute Notice: PRO #${disp.pro_number}`;
        const bodyText =
          `Attention Billing & Overcharge Claims Department (${disp.carrier}),\n\n` +
          `This is a formal follow-up regarding our billing dispute for PRO #${disp.pro_number} ` +
          `(Invoice #${disp.invoice_number}) submitted on ${sentDate.toISOString().slice(0, 10)}.\n\n` +
          `It has been ${daysSinceSent} days since our initial formal notice of overcharge in the amount of ` +
          `$${disp.overcharge_dollars.toFixed(2)}.\n\n` +
          `Please issue the outstanding credit memo immediately to avoid escalation.\n\n` +
          `Sincerely,\n` +
          `Accounts Payable / Freight Audit Dept\n` +
          `${customerName}\n`;

        const mailtoLink = `mailto:${encodeURIComponent(carrierEmail)}?subject=${encodeURIComponent(
          subject
        )}&body=${encodeURIComponent(bodyText)}`;

        nudges.push({
          dispute_id: disp.dispute_id || disp.id,
          invoice_id: disp.invoice_id,
          pro_number: disp.pro_number,
          carrier: disp.carrier,
          customer_id: disp.customer_id,
          customer_name: customerName,
          sent_at: sentDate.toISOString().slice(0, 10),
          days_since_sent: daysSinceSent,
          overdue_threshold_days: daysThreshold,
          suggested_action: 'Send 1-Click Reminder Nudge',
          mailto_reminder_link: mailtoLink,
          reminder_subject: subject,
          status: 'sent',
        });
      }
    }

    return nudges;
  }

  public getCarrierHostilityAnalytics(
    customerId: string,
    period: string = 'all_time'
  ): CarrierAnalyticsReport {
    const customerDisputes = this.disputes.filter((d) => d.customer_id === customerId);

    const carrierBuckets: Record<string, DisputeRecord[]> = {};
    for (const disp of customerDisputes) {
      const cname = disp.carrier.trim();
      if (!carrierBuckets[cname]) {
        carrierBuckets[cname] = [];
      }
      carrierBuckets[cname].push(disp);
    }

    const carrierMetrics: CarrierHostilityMetrics[] = [];
    let totalRecovered = 0.0;
    let totalDenied = 0.0;

    for (const [carrierName, dispList] of Object.entries(carrierBuckets)) {
      const totalSent = dispList.length;
      let approvedCount = 0;
      let deniedCount = 0;
      let pendingCount = 0;
      const resolutionDaysList: number[] = [];

      for (const disp of dispList) {
        if (disp.status === 'credit_issued') {
          approvedCount++;
          totalRecovered += disp.overcharge_dollars;
        } else if (disp.status === 'denied') {
          deniedCount++;
          totalDenied += disp.overcharge_dollars;
        } else {
          pendingCount++;
        }

        const sentDateStr = disp.sent_at || disp.created_at;
        const updatedDateStr = disp.updated_at;
        if (sentDateStr && updatedDateStr && (disp.status === 'credit_issued' || disp.status === 'denied')) {
          const sDate = new Date(sentDateStr);
          const uDate = new Date(updatedDateStr);
          const diffDays = Math.max(1, Math.floor((uDate.getTime() - sDate.getTime()) / (1000 * 60 * 60 * 24)));
          resolutionDaysList.push(diffDays);
        }
      }

      const approvalRatePct = totalSent > 0 ? Number(((approvedCount / totalSent) * 100).toFixed(2)) : 0.0;
      const denialRatePct = totalSent > 0 ? Number(((deniedCount / totalSent) * 100).toFixed(2)) : 0.0;
      const avgResDays =
        resolutionDaysList.length > 0
          ? Number((resolutionDaysList.reduce((a, b) => a + b, 0) / resolutionDaysList.length).toFixed(1))
          : 7.0;

      const hostilityScore = Number(Math.min(10.0, denialRatePct * 0.08 + avgResDays * 0.2).toFixed(2));
      let hostilityStatus: 'friendly' | 'moderate' | 'hostile' = 'friendly';
      if (hostilityScore > 5.0) {
        hostilityStatus = 'hostile';
      } else if (hostilityScore > 2.0) {
        hostilityStatus = 'moderate';
      }

      carrierMetrics.push({
        carrier: carrierName,
        total_disputes_sent: totalSent,
        disputes_approved: approvedCount,
        disputes_denied: deniedCount,
        disputes_pending: pendingCount,
        approval_rate_pct: approvalRatePct,
        denial_rate_pct: denialRatePct,
        avg_resolution_days: avgResDays,
        hostility_score: hostilityScore,
        hostility_status: hostilityStatus,
      });
    }

    carrierMetrics.sort((a, b) => b.hostility_score - a.hostility_score);

    const highestHostility = carrierMetrics.length > 0 ? carrierMetrics[0].carrier : null;
    const lowestHostility = carrierMetrics.length > 0 ? carrierMetrics[carrierMetrics.length - 1].carrier : null;

    return {
      report_id: `report_analytics_${customerId}_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}`,
      customer_id: customerId,
      period,
      total_carriers_tracked: carrierMetrics.length,
      total_disputes: customerDisputes.length,
      total_recovered_dollars: Number(totalRecovered.toFixed(2)),
      total_denied_dollars: Number(totalDenied.toFixed(2)),
      carriers: carrierMetrics,
      highest_hostility_carrier: highestHostility,
      lowest_hostility_carrier: lowestHostility,
      generated_at: new Date().toISOString(),
    };
  }
}
