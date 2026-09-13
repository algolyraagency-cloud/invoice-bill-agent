import os
import time
from pathlib import Path
import psycopg2


def connect_with_retry(max_retries=3, initial_delay=1.0):
    host = os.environ.get("SUPABASE_DB_HOST", "aws-0-ap-southeast-2.pooler.supabase.com")
    port = int(os.environ.get("SUPABASE_DB_PORT", 6543))
    dbname = os.environ.get("SUPABASE_DB_NAME", "postgres")
    user = os.environ.get("SUPABASE_DB_USER", "postgres.ojolpdbveutbaxqmaffv")
    password = os.environ.get("SUPABASE_DB_PASSWORD")

    if not password:
        # Fall back to env or raise descriptive error
        password = os.environ.get("DB_PASSWORD")

    delay = initial_delay
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            print(f"Connecting to Postgres at {host}:{port} as {user} (Attempt {attempt}/{max_retries})...")
            conn = psycopg2.connect(
                dbname=dbname,
                user=user,
                password=password or "",
                host=host,
                port=port,
                connect_timeout=15,
                sslmode="require"
            )
            conn.autocommit = True
            return conn
        except Exception as e:
            last_error = e
            print(f"Connection attempt {attempt} failed: {e}")
            if attempt < max_retries:
                time.sleep(delay)
                delay *= 2

    raise ConnectionError(f"Failed to connect to database after {max_retries} attempts: {last_error}")


def run_migration():
    migrations_dir = Path(__file__).parent / "migrations"
    migration_files = sorted(migrations_dir.glob("*.sql"))

    if not migration_files:
        print(f"No migration files found in: {migrations_dir}")
        return False

    try:
        conn = connect_with_retry()
        cur = conn.cursor()

        for mig_file in migration_files:
            print(f"Executing migration {mig_file.name}...")
            with open(mig_file, "r", encoding="utf-8") as f:
                sql = f.read()
            cur.execute(sql)
            print(f"  [OK] Migration {mig_file.name} executed successfully.")

        # Verify public tables
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';")
        tables = [r[0] for r in cur.fetchall()]
        print(f"\nPublic tables verified ({len(tables)}):")
        for t in sorted(tables):
            print(f"  - {t}")

        conn.close()
        return True
    except Exception as e:
        print(f"Migration execution failed with error: {e}")
        return False


if __name__ == "__main__":
    run_migration()
