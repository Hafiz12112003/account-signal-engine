import os
from pathlib import Path
from dotenv import load_dotenv
import psycopg

load_dotenv()

schema = Path("backend/schema.sql").read_text(encoding="utf-8")

with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
    conn.execute(schema)
    tables = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' ORDER BY table_name"
    ).fetchall()

print("Schema applied. Tables:")
for (name,) in tables:
    print(" -", name)
