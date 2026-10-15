import json
import time
from collections import Counter

import psycopg
import redis
from fastembed import TextEmbedding
from pgvector.psycopg import register_vector

from backend import settings

known_accounts = set()


def chunk_transcript(text, max_chars=700):
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    chunks, cur = [], ""
    for ln in lines:
        if cur and len(cur) + len(ln) + 1 > max_chars:
            chunks.append(cur)
            cur = ln
        else:
            cur = (cur + "\n" + ln) if cur else ln
    if cur:
        chunks.append(cur)
    return chunks


def connect_db():
    conn = psycopg.connect(settings.DATABASE_URL, autocommit=True)
    register_vector(conn)
    return conn


def check_tenant_match(conn, tenant_id, account_id):
    key = (tenant_id, account_id)
    if key in known_accounts:
        return
    row = conn.execute(
        "SELECT 1 FROM accounts WHERE id = %s AND tenant_id = %s", (account_id, tenant_id)
    ).fetchone()
    if not row:
        raise ValueError("account %s does not belong to tenant %s" % (account_id, tenant_id))
    known_accounts.add(key)


def handle(conn, embedder, kind, d):
    if kind == "tenant":
        conn.execute(
            "INSERT INTO tenants (id, name) VALUES (%s, %s) "
            "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
            (d["id"], d["name"]),
        )

    elif kind == "account":
        conn.execute(
            "INSERT INTO accounts (id, tenant_id, name, segment, arr, renewal_date, owner) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, segment = EXCLUDED.segment, "
            "arr = EXCLUDED.arr, renewal_date = EXCLUDED.renewal_date, owner = EXCLUDED.owner "
            "WHERE accounts.tenant_id = EXCLUDED.tenant_id",
            (d["id"], d["tenant_id"], d["name"], d.get("segment"), d.get("arr"),
             d.get("renewal_date"), d.get("owner")),
        )
        known_accounts.add((d["tenant_id"], d["id"]))

    elif kind == "usage":
        check_tenant_match(conn, d["tenant_id"], d["account_id"])
        conn.execute(
            "INSERT INTO usage_events (tenant_id, account_id, occurred_on, active_users, feature_events) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (tenant_id, account_id, occurred_on) DO UPDATE SET "
            "active_users = EXCLUDED.active_users, feature_events = EXCLUDED.feature_events",
            (d["tenant_id"], d["account_id"], d["occurred_on"], d["active_users"], d["feature_events"]),
        )

    elif kind == "crm":
        check_tenant_match(conn, d["tenant_id"], d["account_id"])
        conn.execute(
            "INSERT INTO crm_snapshots (tenant_id, account_id, snapshot_date, stage, amount, close_date, champion) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (tenant_id, account_id, snapshot_date) DO UPDATE SET "
            "stage = EXCLUDED.stage, amount = EXCLUDED.amount, close_date = EXCLUDED.close_date, "
            "champion = EXCLUDED.champion",
            (d["tenant_id"], d["account_id"], d["snapshot_date"], d["stage"], d.get("amount"),
             d.get("close_date"), d.get("champion")),
        )

    elif kind == "call":
        check_tenant_match(conn, d["tenant_id"], d["account_id"])
        chunks = chunk_transcript(d["transcript"])
        vectors = list(embedder.embed(chunks))
        with conn.transaction():
            conn.execute(
                "INSERT INTO call_transcripts (id, tenant_id, account_id, occurred_on, title, transcript) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET occurred_on = EXCLUDED.occurred_on, "
                "title = EXCLUDED.title, transcript = EXCLUDED.transcript "
                "WHERE call_transcripts.tenant_id = EXCLUDED.tenant_id",
                (d["id"], d["tenant_id"], d["account_id"], d["occurred_on"], d.get("title"), d["transcript"]),
            )
            conn.execute("DELETE FROM transcript_chunks WHERE transcript_id = %s", (d["id"],))
            for i, (content, vec) in enumerate(zip(chunks, vectors)):
                conn.execute(
                    "INSERT INTO transcript_chunks (tenant_id, account_id, transcript_id, chunk_index, content, embedding) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (d["tenant_id"], d["account_id"], d["id"], i, content, vec),
                )
    else:
        raise ValueError("unknown kind: " + kind)


def subscribe():
    bus = redis.from_url(settings.REDIS_URL, decode_responses=True)
    ps = bus.pubsub(ignore_subscribe_messages=True)
    ps.subscribe(settings.CHANNEL)
    return ps


def main():
    print("Loading embedding model (first run downloads it)...")
    embedder = TextEmbedding(model_name=settings.EMBED_MODEL)
    conn = connect_db()
    ps = subscribe()
    counts = Counter()
    errors = 0
    print("Worker ready. Listening on channel '%s'..." % settings.CHANNEL)

    while True:
        try:
            msg = ps.get_message(timeout=5)
            if msg is None:
                continue
            event = json.loads(msg["data"])
            handle(conn, embedder, event["kind"], event["data"])
            counts[event["kind"]] += 1
            total = sum(counts.values())
            if total % 100 == 0:
                print("processed %d events: %s (errors: %d)" % (total, dict(counts), errors))
        except (redis.ConnectionError, redis.TimeoutError) as e:
            print("redis connection problem, reconnecting:", type(e).__name__)
            time.sleep(2)
            ps = subscribe()
        except psycopg.OperationalError as e:
            errors += 1
            print("database connection problem, reconnecting:", type(e).__name__)
            time.sleep(2)
            conn = connect_db()
        except Exception as e:
            errors += 1
            print("event failed:", type(e).__name__, str(e)[:200])


if __name__ == "__main__":
    main()
