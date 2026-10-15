import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg; from pgvector.psycopg import register_vector
from fastembed import TextEmbedding
from groq import Groq

from backend import settings
from backend.correlator import analyze_account, save_finding

truth = json.loads(Path("data/ground_truth.json").read_text(encoding="utf-8"))
baseline = {r["account_id"]: r for r in json.loads(Path("data/detector_baseline.json").read_text(encoding="utf-8"))}

ACCEPTABLE_CAUSES = {
    "budget_freeze_with_usage_decline": {"budget_pressure", "usage_decline"},
    "renewal_slip_competitor_eval": {"competitor_risk", "renewal_delay"},
    "champion_left": {"champion_departure"},
    "silent_disengagement": {"disengagement"},
    "competitor_adoption_with_usage_decline": {"competitor_risk", "usage_decline"},
    "champion_reorg_budget_moved": {"champion_departure", "budget_pressure"},
    "sponsor_leaving_vendor_review": {"champion_departure", "competitor_risk"},
}


def outcome(flagged, at_risk):
    if flagged and at_risk:
        return "TP"
    if flagged and not at_risk:
        return "FP"
    if not flagged and at_risk:
        return "FN"
    return "TN"


def prf(rows, key):
    tp = sum(1 for r in rows if r[key] == "TP")
    fp = sum(1 for r in rows if r[key] == "FP")
    fn = sum(1 for r in rows if r[key] == "FN")
    p = tp / (tp + fp) if tp + fp else 0.0
    rc = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * rc / (p + rc) if p + rc else 0.0
    return tp, fp, fn, p, rc, f1


print("Loading embedding model...")
embedder = TextEmbedding(model_name=settings.EMBED_MODEL)
client = Groq(api_key=settings.GROQ_API_KEY)

results = []
with psycopg.connect(settings.DATABASE_URL, autocommit=True) as conn:
    register_vector(conn); accounts = conn.execute("SELECT id, tenant_id FROM accounts ORDER BY id").fetchall()
    for i, (acct_id, tenant_id) in enumerate(accounts, start=1):
        try:
            r = analyze_account(conn, embedder, client, tenant_id, acct_id)
            save_finding(conn, r)
        except Exception as e:
            print("[%d/%d] %s FAILED: %s %s" % (i, len(accounts), acct_id, type(e).__name__, str(e)[:200]))
            continue
        results.append(r)
        print("[%d/%d] %s -> %s (%.2f) %s | %.1fs, %s tokens"
              % (i, len(accounts), acct_id, r["verdict"], r["confidence"], r["status"], r["latency_s"], r["total_tokens"]))
        time.sleep(2)

scored = []
for r in results:
    t = truth[r["account_id"]]
    strict = r["verdict"] == "at_risk" and r["status"] == "accepted"
    lenient = strict or r["verdict"] == "needs_review"
    cause_ok = None
    if t["at_risk"] and strict:
        cause_ok = r["cause"] in ACCEPTABLE_CAUSES.get(t["cause"], set())
    scored.append({
        **r,
        "truth_at_risk": t["at_risk"], "truth_cause": t["cause"],
        "difficulty": t["difficulty"], "decoy": t["decoy"],
        "strict": outcome(strict, t["at_risk"]),
        "lenient": outcome(lenient, t["at_risk"]),
        "baseline_b": baseline[r["account_id"]]["baseline_b"],
        "cause_ok": cause_ok,
    })

print()
print("%-7s %-8s %-6s %-5s %-13s %-5s %-19s %-6s %-6s" % ("acct", "truth", "diff", "decoy", "verdict", "conf", "status", "strict", "lenient"))
for s in scored:
    print("%-7s %-8s %-6s %-5s %-13s %-5.2f %-19s %-6s %-6s" % (
        s["account_id"], "AT RISK" if s["truth_at_risk"] else "ok", s["difficulty"],
        "yes" if s["decoy"] else "", s["verdict"], s["confidence"], s["status"], s["strict"], s["lenient"]))

print()
for key, label in (("baseline_b", "Rules only (baseline B)"), ("strict", "LLM strict (at_risk only)"), ("lenient", "LLM lenient (+needs_review)")):
    tp, fp, fn, p, rc, f1 = prf(scored, key)
    print("%-30s TP=%d FP=%d FN=%d  precision=%.2f recall=%.2f F1=%.2f" % (label, tp, fp, fn, p, rc, f1))

total_cites = sum(len(s["citations"]) for s in scored)
valid_cites = sum(len(s["valid_citations"]) for s in scored)
rejected = sum(1 for s in scored if s["status"].startswith("rejected"))
downgraded = sum(1 for s in scored if s["downgraded"])
cause_checked = [s for s in scored if s["cause_ok"] is not None]
print()
print("accounts analyzed: %d of %d" % (len(scored), len(truth)))
print("citations valid: %d of %d (%.0f%%)" % (valid_cites, total_cites, 100.0 * valid_cites / total_cites if total_cites else 0))
print("findings rejected by provenance check: %d" % rejected)
print("low-confidence at_risk downgraded to needs_review: %d" % downgraded)
if cause_checked:
    print("cause matched on correct catches: %d of %d" % (sum(1 for s in cause_checked if s["cause_ok"]), len(cause_checked)))
n = len(scored) or 1
print("avg tokens per account: %.0f | avg latency: %.1fs"
      % (sum((s["total_tokens"] or 0) for s in scored) / n, sum(s["latency_s"] for s in scored) / n))

Path("data/llm_results.json").write_text(json.dumps(scored, indent=1, default=str), encoding="utf-8")
print("\nSaved data/llm_results.json")

