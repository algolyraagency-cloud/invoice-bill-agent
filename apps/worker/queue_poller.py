"""
pg-boss Job Poller for Python Worker.
Uses Postgres SELECT ... FOR UPDATE SKIP LOCKED to consume jobs directly from Supabase.
"""
import json
import os
from typing import Any, Dict, Optional, Tuple

import psycopg2


def get_db_connection():
    return psycopg2.connect(
        dbname=os.environ.get("SUPABASE_DB_NAME", "postgres"),
        user=os.environ.get("SUPABASE_DB_USER", "postgres.ojolpdbveutbaxqmaffv"),
        password=os.environ.get("SUPABASE_DB_PASSWORD", "99NRU%$4.YY6-eg"),
        host=os.environ.get("SUPABASE_DB_HOST", "aws-0-ap-southeast-2.pooler.supabase.com"),
        port=int(os.environ.get("SUPABASE_DB_PORT", 6543)),
        sslmode="require",
        connect_timeout=10
    )


def fetch_next_job(cur, queue_name: str = "parse-invoice") -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Atomically claims the next job from pgboss.job using FOR UPDATE SKIP LOCKED.
    Returns (job_id, job_data) or None if queue is empty.
    """
    try:
        cur.execute("""
            UPDATE pgboss.job
            SET state = 'active', startedon = now()
            WHERE id = (
                SELECT id FROM pgboss.job
                WHERE name = %s AND state = 'created'
                ORDER BY priority DESC, createdon ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id, data;
        """, (queue_name,))
        row = cur.fetchone()
        if row:
            job_id, data = row
            return str(job_id), data if isinstance(data, dict) else json.loads(data)
        return None
    except Exception:
        # Table might not exist yet if pg-boss node initializer hasn't booted
        return None


def complete_job(cur, job_id: str, output: Dict[str, Any]):
    cur.execute("""
        UPDATE pgboss.job
        SET state = 'completed', completedon = now(), output = %s
        WHERE id = %s
    """, (json.dumps(output), job_id))


def fail_job(cur, job_id: str, error_message: str):
    cur.execute("""
        UPDATE pgboss.job
        SET state = 'failed', completedon = now(), output = %s
        WHERE id = %s
    """, (json.dumps({"error": error_message}), job_id))
