import json
import re
import time

from psycopg.types.json import Jsonb

from backend import settings
from backend.detectors import USAGE_SQL, detect_all

CAUSES = ["budget_pressure", "competitor_risk", "champion_departure", "renewal_delay",
          "disengagement", "usage_decline", "other", "none"]
VERDICTS = ["at_risk", "healthy", "needs_review"]
CONFIDENCE_FLOOR = 0.6

QUERIES = [
    "budget freeze, cutting spend, reducing seats, pricing pressure",
    "evaluating a competitor or switching to another vendor",
    "champion leaving, reorganization, new stakeholder or new owner",
    "renewal delayed, procurement or legal review, uncertain timing",
    "disengaged, cancelled meetings, vague and noncommittal about next quarter",
    "temporary pause, planned shutdown, migration, expects usage to recover, plans to renew",
]

INSTRUCTIONS = """You are an analyst on a customer success team. Decide whether this customer account is at risk of not renewing or shrinking, using only the evidence below.

Think carefully about benign explanations. A temporary usage dip that the calls clearly explain (a planned shutdown, a data migration, a procurement or security review) is NOT risk if the customer confirms they intend to renew and usage has recovered. Real risk can also be quiet: a champion leaving, budget moving elsewhere, a competitor being evaluated, a new owner reviewing vendors, or a champion going vague and avoiding renewal talk, even with no complaint about the product and no usage decline yet.

Verdicts:
- "at_risk": the evidence supports a real renewal or contraction risk.
- "healthy": no meaningful risk.
- "needs_review": the evidence is thin, mixed, or contradictory and a human should look. Use this instead of guessing when your confidence is below 0.6.

Rules:
- Cite evidence only by the exact IDs given below. Never invent an ID.
- For at_risk or needs_review, cite at least one ID, and every cited item must actually support your claim.
- Write the summary for a CSM in 2 to 3 plain sentences. Quote at most a short phrase from any call.
- cause must be one of: budget_pressure, competitor_risk, champion_departure, renewal_delay, disengagement, usage_decline, other. Use "none" when the verdict is healthy.

Return only a JSON object with exactly these keys:
{"verdict": "at_risk|healthy|needs_review", "confidence": 0.0 to 1.0, "cause": "...", "summary": "...", "citations": ["id", "id"]}
"""

USAGE_ID = re.compile(r"^usage:([^:\s]+):(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$")


def gather_context(conn, embedder, tenant_id, account_id):
    acct = conn.execute(
        "SELECT name, segment, arr, renewal_date, owner FROM accounts WHERE id = %s AND tenant_id = %s",
        (account_id, tenant_id),
    ).fetchone()
    if not acct:
        raise ValueError("unknown account for this tenant")
    name, segment, arr, renewal, owner = acct
    as_of = conn.execute(
        "SELECT max(occurred_on) FROM usage_events WHERE tenant_id = %s AND account_id = %s",
        (tenant_id, account_id),
    ).fetchone()[0]

    hits = detect_all(conn, tenant_id, account_id)
    usage_rows = conn.execute(USAGE_SQL, {"t": tenant_id, "a": account_id}).fetchall()
    crm_rows = conn.execute(
        "SELECT id, snapshot_date, stage, close_date, champion FROM crm_snapshots "
        "WHERE tenant_id = %s AND account_id = %s ORDER BY snapshot_date",
        (tenant_id, account_id),
    ).fetchall()

    chunks = {}
    for q in QUERIES:
        vec = list(embedder.embed([q]))[0]
        rows = conn.execute(
            "SELECT c.id, t.occurred_on, t.title, c.chunk_index, c.content "
            "FROM transcript_chunks c JOIN call_transcripts t ON t.id = c.transcript_id "
            "WHERE c.tenant_id = %s AND c.account_id = %s "
            "ORDER BY c.embedding <=> %s LIMIT 2",
            (tenant_id, account_id, vec),
        ).fetchall()
        for r in rows:
            chunks[r[0]] = r
    ordered = sorted(chunks.values(), key=lambda r: (r[1], r[3]))

    lines = []
    lines.append("ACCOUNT: %s (%s), ARR %s, renewal date %s, owner %s. Data as of %s."
                 % (name, segment, "{:,.0f}".format(float(arr or 0)), renewal, owner, as_of))
    lines.append("")
    lines.append("AUTOMATED DETECTOR HITS (simple rules, may be wrong):")
    if hits:
        for h in hits:
            lines.append("- %s: %s [cite: %s]" % (h["detector"], h["summary"], ", ".join(h["citations"])))
    else:
        lines.append("- none")
    lines.append("")
    lines.append("WEEKLY WEEKDAY ACTIVE USERS (oldest to newest):")
    for wk, avg, first, last in sorted(usage_rows, key=lambda r: -r[0]):
        lines.append("- %s to %s: %.0f users/day [id: usage:%s:%s..%s]" % (first, last, avg, account_id, first, last))
    lines.append("")
    lines.append("CRM HISTORY (weekly snapshots):")
    for cid, snap, stage, close, champ in crm_rows:
        lines.append("- [id: crm:%d] snapshot %s | stage %s | close date %s | champion %s" % (cid, snap, stage, close, champ))
    lines.append("")
    lines.append("CALL EXCERPTS (retrieved):")
    for cid, day, title, idx, content in ordered:
        lines.append("[chunk:%d] %s, call: %s" % (cid, day, title))
        lines.append(content)
        lines.append("")

    return INSTRUCTIONS + "\n" + "\n".join(lines), hits


def call_llm(client, prompt):
    kwargs = dict(
        model=settings.LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4000,
        temperature=0.2,
        response_format={"type": "json_object"},
        extra_body={"reasoning_effort": "medium"},
    )
    for _ in range(8):
        t0 = time.time()
        try:
            res = client.chat.completions.create(**kwargs)
            text = (res.choices[0].message.content or "").strip()
            if text:
                u = res.usage
                meta = {
                    "latency_s": round(time.time() - t0, 2),
                    "prompt_tokens": getattr(u, "prompt_tokens", None),
                    "completion_tokens": getattr(u, "completion_tokens", None),
                    "total_tokens": getattr(u, "total_tokens", None),
                }
                return text, meta
            kwargs["max_tokens"] = 6000
        except Exception as e:
            msg = str(e).lower()
            if "reasoning" in msg and "extra_body" in kwargs:
                kwargs.pop("extra_body")
            elif ("response_format" in msg or "json" in msg) and "response_format" in kwargs:
                kwargs.pop("response_format")
            elif "connection" in msg or "timeout" in msg:
                print("   connection problem, retrying in 5s...")
                time.sleep(5)
            elif "429" in msg or "rate" in msg:
                print("   rate limited, waiting 30s...")
                time.sleep(30)
            else:
                raise
    raise RuntimeError("LLM call failed after retries")


def parse_output(text):
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in reply")
    data = json.loads(t[start:end + 1])

    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in VERDICTS:
        raise ValueError("bad verdict: " + verdict)
    conf = max(0.0, min(1.0, float(data.get("confidence"))))
    cause = str(data.get("cause", "other")).strip().lower()
    if cause not in CAUSES:
        cause = "other"
    cites = data.get("citations") or []
    if not isinstance(cites, list):
        cites = []
    cites = [str(c).strip() for c in cites if str(c).strip()]

    downgraded = False
    if verdict == "at_risk" and conf < CONFIDENCE_FLOOR:
        verdict, downgraded = "needs_review", True

    return {"verdict": verdict, "confidence": conf, "cause": cause,
            "summary": str(data.get("summary", "")).strip(), "citations": cites,
            "downgraded": downgraded}


def verify_citations(conn, tenant_id, account_id, cites):
    valid, invalid = [], []
    for cid in dict.fromkeys(cites):
        ok = False
        try:
            if cid.startswith("chunk:") and cid[6:].isdigit():
                ok = conn.execute(
                    "SELECT 1 FROM transcript_chunks WHERE id = %s AND tenant_id = %s AND account_id = %s",
                    (int(cid[6:]), tenant_id, account_id)).fetchone() is not None
            elif cid.startswith("crm:") and cid[4:].isdigit():
                ok = conn.execute(
                    "SELECT 1 FROM crm_snapshots WHERE id = %s AND tenant_id = %s AND account_id = %s",
                    (int(cid[4:]), tenant_id, account_id)).fetchone() is not None
            else:
                m = USAGE_ID.match(cid)
                if m and m.group(1) == account_id:
                    ok = conn.execute(
                        "SELECT 1 FROM usage_events WHERE tenant_id = %s AND account_id = %s "
                        "AND occurred_on BETWEEN %s AND %s LIMIT 1",
                        (tenant_id, account_id, m.group(2), m.group(3))).fetchone() is not None
        except Exception:
            ok = False
        (valid if ok else invalid).append(cid)
    return valid, invalid


def analyze_account(conn, embedder, client, tenant_id, account_id):
    prompt, hits = gather_context(conn, embedder, tenant_id, account_id)
    out, meta, last_err = None, None, None
    for _ in range(2):
        text, meta = call_llm(client, prompt)
        try:
            out = parse_output(text)
            break
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            last_err = e
    if out is None:
        raise RuntimeError("unparseable model output: %s" % last_err)

    valid, invalid = verify_citations(conn, tenant_id, account_id, out["citations"])
    if out["verdict"] == "healthy":
        status = "no_finding"
    elif invalid:
        status = "rejected_invalid_citation"
    elif not valid:
        status = "rejected_no_evidence"
    else:
        status = "accepted"

    return {
        "account_id": account_id, "tenant_id": tenant_id,
        "verdict": out["verdict"], "confidence": out["confidence"], "cause": out["cause"],
        "summary": out["summary"], "downgraded": out["downgraded"],
        "citations": out["citations"], "valid_citations": valid, "invalid_citations": invalid,
        "status": status, "detector_hits": [h["detector"] for h in hits],
        "model": settings.LLM_MODEL, **meta,
    }


def save_finding(conn, r):
    conn.execute(
        "DELETE FROM plays WHERE finding_id IN "
        "(SELECT id FROM findings WHERE tenant_id = %s AND account_id = %s AND status = 'pending')",
        (r["tenant_id"], r["account_id"]))
    conn.execute(
        "DELETE FROM findings WHERE tenant_id = %s AND account_id = %s AND status = 'pending'",
        (r["tenant_id"], r["account_id"]))
    if r["status"] != "accepted":
        return None
    fid = conn.execute(
        "INSERT INTO findings (tenant_id, account_id, kind, summary, confidence, status, citations, cause) "
        "VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s) RETURNING id",
        (r["tenant_id"], r["account_id"], r["verdict"], r["summary"], r["confidence"],
         Jsonb(r["valid_citations"]), r["cause"])).fetchone()[0]
    conn.execute(
        "INSERT INTO audit_log (tenant_id, actor, action, entity, entity_id, detail) "
        "VALUES (%s, 'system:correlator', 'finding_created', 'finding', %s, %s)",
        (r["tenant_id"], str(fid), Jsonb({
            "verdict": r["verdict"], "confidence": r["confidence"], "model": r["model"],
            "total_tokens": r["total_tokens"], "latency_s": r["latency_s"]})))
    return fid

