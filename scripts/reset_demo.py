import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg

from backend import settings
from backend.correlator import save_finding
from backend.plays import generate_plays

results = json.loads(Path("data/llm_results.json").read_text(encoding="utf-8"))
accepted = [r for r in results if r["status"] == "accepted"]

with psycopg.connect(settings.DATABASE_URL, autocommit=True) as conn:
    with conn.transaction():
        conn.execute("DELETE FROM plays")
        conn.execute("DELETE FROM audit_log")
        conn.execute("DELETE FROM findings")
        for r in accepted:
            save_finding(conn, r)
    made = generate_plays(conn)
    waiting = conn.execute("SELECT count(*) FROM findings WHERE status = 'pending'").fetchone()[0]
    sample = conn.execute(
        "SELECT a.name, p.action, p.draft FROM plays p "
        "JOIN findings f ON f.id = p.finding_id "
        "JOIN accounts a ON a.id = f.account_id AND a.tenant_id = f.tenant_id "
        "WHERE f.kind = 'at_risk' ORDER BY p.id LIMIT 1"
    ).fetchone()

print("findings waiting: %d | plays created: %d" % (waiting, made))
if sample:
    print("\nSample play for %s: %s\n%s" % sample)
