"""
Unit tests for Deterministic Audit Engine Checks 5–8 (Phase 7.3).
Covers:
- Check 5: Accessorial Audit (ACCESSORIAL)
- Check 6: Reweigh & Dimension Audit (REWEIGH)
- Check 7: Guaranteed SLA Audit (GUARANTEE)
- Check 8: Freight Transportation Tax Audit (TAX)
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
engine_dir = BASE_DIR / "packages" / "audit-engine"
for p in [str(BASE_DIR), str(engine_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from engine import (
    check_accessorials,
    check_freight_tax,
    check_guaranteed_sla,
    check_reweigh_dimension,
)
from orchestrator import audit_invoice

from packages.schemas.models import Accessorial, InvoiceJSON, LineItem, RateMatrixJSON


def test_check_5_accessorials_unauthorized():
    inv = InvoiceJSON(
        carrier="Estes Express",
        pro_number="PRO-ACC-01",
        invoice_number="INV-ACC-01",
        invoice_date="2026-09-01",
        origin_zip="90210",
        dest_zip="60601",
        billed_weight=1200,
        invoice_total=450.0,
        accessorials=[
            Accessorial(type="Liftgate", amount=75.0, authorized=False),
        ],
    )
    flags = check_accessorials(inv)
    assert len(flags) == 1
    assert flags[0].check_type == "ACCESSORIAL"
    assert flags[0].overcharge_cents == 7500
    assert "Liftgate" in flags[0].evidence_json["note"]


def test_check_5_accessorials_rate_exceeded():
    inv = InvoiceJSON(
        carrier="Estes Express",
        pro_number="PRO-ACC-02",
        invoice_number="INV-ACC-02",
        invoice_date="2026-09-01",
        origin_zip="90210",
        dest_zip="60601",
        billed_weight=1200,
        invoice_total=450.0,
        accessorials=[
            Accessorial(type="Liftgate", amount=95.0, authorized=True),
        ],
    )
    matrix = RateMatrixJSON(
        carrier="Estes Express",
        effective_dates={"start": "2026-01-01", "end": "2026-12-31"},
        approved_accessorials={"liftgate": 50.0, "residential": 60.0},
    )
    flags = check_accessorials(inv, rate_matrix_versions=[matrix])
    assert len(flags) == 1
    assert flags[0].check_type == "ACCESSORIAL"
    assert flags[0].overcharge_cents == 4500  # $95 - $50 = $45


def test_check_6_reweigh_unauthorized_fee():
    inv = InvoiceJSON(
        carrier="FedEx Freight",
        pro_number="PRO-REW-01",
        invoice_number="INV-REW-01",
        invoice_date="2026-09-01",
        origin_zip="90210",
        dest_zip="60601",
        billed_weight=1500,
        invoice_total=520.0,
        line_items=[
            LineItem(description="Base Linehaul Freight", amount=450.0),
            LineItem(description="Reweigh & Weight Inspection Fee", amount=70.0),
        ],
    )
    flags = check_reweigh_dimension(inv, certified_reweigh=False)
    assert len(flags) == 1
    assert flags[0].check_type == "REWEIGH"
    assert flags[0].overcharge_cents == 7000


def test_check_6_reweigh_excess_weight_without_cert():
    inv = InvoiceJSON(
        carrier="FedEx Freight",
        pro_number="PRO-REW-02",
        invoice_number="INV-REW-02",
        invoice_date="2026-09-01",
        origin_zip="90210",
        dest_zip="60601",
        billed_weight=1800,  # 300 lbs higher than BOL
        invoice_total=600.0,
        line_items=[
            LineItem(description="Base Freight", amount=600.0),
        ],
    )
    flags = check_reweigh_dimension(inv, bol_weight=1500.0, certified_reweigh=False)
    assert len(flags) == 1
    assert flags[0].check_type == "REWEIGH"
    assert flags[0].evidence_json["weight_diff_lbs"] == 300.0


def test_check_7_guaranteed_sla_missed():
    inv = InvoiceJSON(
        carrier="SAIA Motor Freight",
        pro_number="PRO-GSD-01",
        invoice_number="INV-GSD-01",
        invoice_date="2026-09-01",
        origin_zip="90210",
        dest_zip="60601",
        billed_weight=1000,
        invoice_total=350.0,
        line_items=[
            LineItem(description="Standard Linehaul Freight", amount=280.0),
            LineItem(description="Guaranteed 12:00 PM Service", amount=70.0),
        ],
    )
    flags = check_guaranteed_sla(
        inv,
        guaranteed_service=True,
        promised_delivery_date="2026-09-03",
        actual_delivery_date="2026-09-05",  # 2 days late
    )
    assert len(flags) == 1
    assert flags[0].check_type == "GUARANTEE"
    assert flags[0].overcharge_cents == 7000  # $70 refund of guarantee fee


def test_check_8_freight_tax_interstate_exemption():
    inv = InvoiceJSON(
        carrier="Old Dominion",
        pro_number="PRO-TAX-01",
        invoice_number="INV-TAX-01",
        invoice_date="2026-09-01",
        origin_zip="90210",  # CA
        dest_zip="60601",  # IL (Interstate)
        billed_weight=1100,
        invoice_total=432.0,
        line_items=[
            LineItem(description="Linehaul Freight", amount=400.0),
            LineItem(description="State Sales Tax Charge", amount=32.0),
        ],
    )
    flags = check_freight_tax(inv, is_interstate=True)
    assert len(flags) == 1
    assert flags[0].check_type == "TAX"
    assert flags[0].overcharge_cents == 3200


def test_master_audit_invoice_executes_all_checks():
    inv = InvoiceJSON(
        carrier="Old Dominion",
        pro_number="PRO-ALL-01",
        invoice_number="INV-ALL-01",
        invoice_date="2026-09-01",
        origin_zip="90210",
        dest_zip="60601",
        billed_weight=1200,
        invoice_total=500.0,
        accessorials=[
            Accessorial(type="Liftgate", amount=80.0, authorized=False),
        ],
        line_items=[
            LineItem(description="Base Linehaul Freight", amount=380.0),
            LineItem(description="Reweigh Inspection Fee", amount=40.0),
            LineItem(description="Guaranteed AM Delivery", amount=50.0),
            LineItem(description="State Transportation Tax", amount=30.0),
        ],
    )
    flags = audit_invoice(
        invoice=inv,
        rate_matrices=[],
        certified_reweigh=False,
        guaranteed_service=True,
        promised_delivery_date="2026-09-03",
        actual_delivery_date="2026-09-04",
        is_interstate=True,
    )
    check_types = {f.check_type for f in flags}
    assert "ACCESSORIAL" in check_types
    assert "REWEIGH" in check_types
    assert "GUARANTEE" in check_types
    assert "TAX" in check_types
