"""
Customer onboarding & multi-tenant view helper for Python runtime.
"""
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple


def generate_slug(name: str) -> str:
    """Sanitizes customer name into a clean, alphanumeric email-friendly slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")
    return slug[:48] if slug else f"org-{uuid.uuid4().hex[:8]}"


def onboard_pilot_customer(
    conn,
    name: str,
    contact_email: str,
    industry: str = "Manufacturing",
    freight_spend_est: float = 5000000.00
) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
    """
    Onboards a pilot customer organization into Supabase Postgres.
    Returns: (success, customer_id, slug, error)
    """
    cur = conn.cursor()
    slug = generate_slug(name)

    # Check slug collision
    cur.execute("SELECT id FROM customers WHERE slug = %s;", (slug,))
    if cur.fetchone():
        slug = f"{slug}-{uuid.uuid4().hex[:4]}"

    customer_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    try:
        # Create customer
        cur.execute("""
            INSERT INTO customers (id, name, slug, industry, freight_spend_est, status)
            VALUES (%s, %s, %s, %s, %s, 'active')
            RETURNING id, slug;
        """, (customer_id, name, slug, industry, freight_spend_est))

        # Create primary owner user
        cur.execute("""
            INSERT INTO users (id, customer_id, email, role)
            VALUES (%s, %s, %s, 'owner');
        """, (user_id, customer_id, contact_email.lower().strip()))

        conn.commit()
        return True, customer_id, slug, None
    except Exception as e:
        conn.rollback()
        return False, None, None, str(e)


def list_customer_invoices(conn, customer_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Lists invoices for a customer with flag counts and overcharge summaries.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT
            i.id,
            i.carrier,
            i.pro_number,
            i.invoice_number,
            i.invoice_date,
            i.invoice_total,
            i.source,
            i.status,
            i.parse_confidence,
            i.file_path,
            i.created_at,
            COUNT(f.id) AS flag_count,
            COALESCE(SUM(f.overcharge_cents), 0) AS total_overcharge_cents
        FROM invoices i
        LEFT JOIN flags f ON f.invoice_id = i.id
        WHERE i.customer_id = %s
        GROUP BY i.id
        ORDER BY i.created_at DESC
        LIMIT %s;
    """, (customer_id, limit))

    columns = [desc[0] for desc in cur.description]
    rows = cur.fetchall()
    results = []
    for r in rows:
        item = dict(zip(columns, r))
        # Format types cleanly
        item["id"] = str(item["id"])
        item["invoice_date"] = str(item["invoice_date"])
        item["invoice_total"] = float(item["invoice_total"])
        item["parse_confidence"] = float(item["parse_confidence"] or 1.0)
        item["created_at"] = str(item["created_at"])
        results.append(item)
    return results
