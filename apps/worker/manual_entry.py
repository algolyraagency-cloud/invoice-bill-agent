"""
Manual invoice entry service for Python runtime.
Guarantees manual invoices enter the exact same pipeline state ('pending') as emailed/uploaded invoices.
"""
import hashlib
import json
import uuid
from typing import Any, Dict, Optional, Tuple


def build_canonical_manual_invoice(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Constructs a validated canonical InvoiceJSON structure from manual form input.
    """
    required = ["carrier", "pro_number", "invoice_number", "invoice_date", "invoice_total"]
    for field in required:
        if not data.get(field):
            raise ValueError(f"Missing required manual invoice field: {field}")

    if float(data["invoice_total"]) <= 0:
        raise ValueError("Invoice total must be greater than zero")

    raw_hash = hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()

    return {
        "carrier": data["carrier"].strip(),
        "pro_number": data["pro_number"].strip(),
        "invoice_number": data["invoice_number"].strip(),
        "invoice_date": data["invoice_date"].strip()[:10],
        "origin_zip": data.get("origin_zip", "").strip(),
        "dest_zip": data.get("dest_zip", "").strip(),
        "billed_weight": float(data.get("billed_weight", 0.0)),
        "billed_class": float(data["billed_class"]) if data.get("billed_class") is not None else None,
        "line_items": data.get("line_items", []),
        "accessorials": data.get("accessorials", []),
        "fsc_amount": float(data["fsc_amount"]) if data.get("fsc_amount") is not None else None,
        "fsc_pct": float(data["fsc_pct"]) if data.get("fsc_pct") is not None else None,
        "invoice_total": float(data["invoice_total"]),
        "notes": data.get("notes"),
        "raw_text_hash": raw_hash,
        "manual_entry": True
    }


def insert_manual_invoice(conn, customer_id: str, data: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Inserts manual invoice into Supabase Postgres database.
    Returns: (success, invoice_id, error_message)
    """
    try:
        canonical_json = build_canonical_manual_invoice(data)
    except Exception as val_err:
        return False, None, str(val_err)

    invoice_id = str(uuid.uuid4())
    cur = conn.cursor()

    # Check duplicate constraint
    cur.execute("""
        SELECT id FROM invoices
        WHERE customer_id = %s AND carrier = %s AND invoice_number = %s AND pro_number = %s;
    """, (customer_id, canonical_json["carrier"], canonical_json["invoice_number"], canonical_json["pro_number"]))

    if cur.fetchone():
        return False, None, f"Duplicate invoice: {canonical_json['invoice_number']} already exists"

    try:
        cur.execute("""
            INSERT INTO invoices (
                id, customer_id, source, carrier, pro_number, invoice_number,
                invoice_date, invoice_total, parsed_json, parse_confidence,
                file_path, status
            ) VALUES (
                %s, %s, 'manual', %s, %s, %s,
                %s, %s, %s, 1.000,
                NULL, 'pending'
            ) RETURNING id;
        """, (
            invoice_id,
            customer_id,
            canonical_json["carrier"],
            canonical_json["pro_number"],
            canonical_json["invoice_number"],
            canonical_json["invoice_date"],
            canonical_json["invoice_total"],
            json.dumps(canonical_json)
        ))
        conn.commit()
        return True, invoice_id, None
    except Exception as e:
        conn.rollback()
        return False, None, str(e)
