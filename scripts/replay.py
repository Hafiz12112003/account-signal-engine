import json
import os
import sys
import time
from pathlib import Path

import httpx
import psycopg
from dotenv import load_dotenv

load_dotenv()

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
HEADERS = {"X-Webhook-Secret": os.environ["WEBHOOK_SECRET"]}

seed = json.loads(Path("data/seed.json").read_text(encoding="utf-8"))
calls = json.loads(Path("data/call_transcripts.json").read_text(encoding="utf-8"))

PLAN = [
    ("tenant", seed["tenants"]),
    ("account", seed["accounts"]),
    ("usage", seed["usage_events"]),
    ("crm", seed["crm_snapshots"]),
    ("call", calls),
]


def post(client, kind, items):
    r = client.post("%s/webhooks/%s" % (BASE, kind), json=items, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.json()["accepted"]


with httpx.Client() as client:
    for kind, items in PLAN:
        sent = 0
        for i in range(0, len(items), 50):
            sent += post(client, kind, items[i:i + 50])
        print("sent %-8s %d" % (kind, sent))
        time.sleep(1)

EXPECTED = {
    "tenants": len(seed["tenants"]),
    "accounts": len(seed["accounts"]),
    "usage_events": len(seed["usage_events"]),
    "crm_snapshots": len(seed["crm_snapshots"]),
    "call_transcripts": len(calls),
}

print("\nWaiting for the worker to store everything...")
with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
    for _ in range(60):
        counts = {t: conn.execute("SELECT count(*) FROM " + t).fetchone()[0] for t in EXPECTED}
        chunks = conn.execute("SELECT count(*) FROM transcript_chunks").fetchone()[0]
        if counts == EXPECTED and chunks > 0:
            break
        time.sleep(3)

    print("\n%-18s %8s %8s" % ("table", "expected", "stored"))
    for t, exp in EXPECTED.items():
        print("%-18s %8d %8d" % (t, exp, counts[t]))
    print("%-18s %8s %8d" % ("transcript_chunks", "-", chunks))
    print("\nOK" if counts == EXPECTED and chunks > 0 else "\nMISMATCH: check the worker terminal for errors")
