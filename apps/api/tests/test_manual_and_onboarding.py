"""
Tests for Manual Entry Fallback (Phase 1.3) and Onboarding Slug Provisioning (Phase 1.4).
"""
import pytest

from apps.worker.manual_entry import build_canonical_manual_invoice
from apps.worker.onboarding import generate_slug


def test_generate_slug_clean():
    assert generate_slug("Acme Industrial Supply") == "acme-industrial-supply"
    assert generate_slug("X-Treme & Heavy Freight, LLC") == "x-treme-heavy-freight-llc"
    assert generate_slug("   Pacesetter Logistics 2026   ") == "pacesetter-logistics-2026"
    assert generate_slug("---leading-and-trailing---") == "leading-and-trailing"


def test_build_canonical_manual_invoice():
    manual_data = {
        "carrier": "Roadrunner",
        "pro_number": "RR-99110022",
        "invoice_number": "INV-778899",
        "invoice_date": "2026-08-14",
        "origin_zip": "43215",
        "dest_zip": "60601",
        "billed_weight": 850.0,
        "billed_class": 70.0,
        "invoice_total": 412.50,
        "line_items": [
            {"description": "Base Linehaul", "amount": 340.00},
            {"description": "Fuel Surcharge", "amount": 72.50}
        ],
        "notes": "Concierge manual fax transcription"
    }

    canonical = build_canonical_manual_invoice(manual_data)
    assert canonical["carrier"] == "Roadrunner"
    assert canonical["pro_number"] == "RR-99110022"
    assert canonical["invoice_number"] == "INV-778899"
    assert canonical["invoice_total"] == 412.50
    assert canonical["manual_entry"] is True
    assert len(canonical["raw_text_hash"]) == 64
    assert len(canonical["line_items"]) == 2


def test_build_canonical_manual_invoice_validation_failures():
    # Missing required field
    with pytest.raises(ValueError, match="Missing required manual invoice field: carrier"):
        build_canonical_manual_invoice({
            "pro_number": "123",
            "invoice_number": "456",
            "invoice_date": "2026-08-14",
            "invoice_total": 100.00
        })

    # Zero or negative total
    with pytest.raises(ValueError, match="Invoice total must be greater than zero"):
        build_canonical_manual_invoice({
            "carrier": "ABF",
            "pro_number": "123",
            "invoice_number": "456",
            "invoice_date": "2026-08-14",
            "invoice_total": -50.00
        })
