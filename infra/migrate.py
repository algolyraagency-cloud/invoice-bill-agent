import os
from pathlib import Path

import psycopg2


def run_migration():
    migration_file = Path(__file__).parent / "migrations" / "001_initial_schema.sql"
    if not migration_file.exists():
        print(f"Migration file not found: {migration_file}")
        return False

    with open(migration_file, "r", encoding="utf-8") as f:
        sql = f.read()

    # Connection parameters for Supabase Pooler (IPv4 reliable)
    host = os.environ.get("SUPABASE_DB_HOST", "aws-0-ap-southeast-2.pooler.supabase.com")
    port = int(os.environ.get("SUPABASE_DB_PORT", 6543))
    dbname = os.environ.get("SUPABASE_DB_NAME", "postgres")
    user = os.environ.get("SUPABASE_DB_USER", "postgres.ojolpdbveutbaxqmaffv")
    password = os.environ.get("SUPABASE_DB_PASSWORD", "99NRU%$4.YY6-eg")

    print(f"Connecting to Postgres at {host}:{port} as {user}...")
    try:
        conn = psycopg2.connect(
            dbname=dbname,
            user=user,
            password=password,
            host=host,
            port=port,
            connect_timeout=15,
            sslmode="require"
        )
        conn.autocommit = True
        cur = conn.cursor()
        print("Executing migration 001_initial_schema.sql...")
        cur.execute(sql)
        print("SUCCESS: Migration 001 executed successfully!")

        # Verify tables
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';")
        tables = [r[0] for r in cur.fetchall()]
        print(f"\nPublic tables created ({len(tables)}):")
        for t in sorted(tables):
            print(f"  - {t}")

        cur.execute("SELECT count(*) FROM reason_codes;")
        print(f"\nReason codes seeded: {cur.fetchone()[0]}")
        cur.execute("SELECT count(*) FROM carrier_contacts;")
        print(f"Carrier contacts seeded: {cur.fetchone()[0]}")
        cur.execute("SELECT count(*) FROM fsc_tables;")
        print(f"FSC scale rows seeded: {cur.fetchone()[0]}")
        cur.execute("SELECT count(*) FROM eia_diesel_indices;")
        print(f"EIA diesel weeks seeded: {cur.fetchone()[0]}")

        conn.close()
        return True
    except Exception as e:
        print(f"Migration failed with error: {e}")
        return False

if __name__ == "__main__":
    run_migration()
