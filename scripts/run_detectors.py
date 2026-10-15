import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
from dotenv import load_dotenv

from backend.detectors import detect_all

load_dotenv()
truth = json.loads(Path("data/ground_truth.json").read_text(encoding="utf-8"))


def outcome(flagged, at_risk):
    if flagged and at_risk:
        return "TP"
    if flagged and not at_risk:
        return "FP"
    if not flagged and at_risk:
        return "FN"
    return "TN"


def metrics(results, key):
    tp = sum(1 for r in results if r[key] == "TP")
    fp = sum(1 for r in results if r[key] == "FP")
    fn = sum(1 for r in results if r[key] == "FN")
    p = tp / (tp + fp) if tp + fp else 0.0
    rc = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * rc / (p + rc) if p + rc else 0.0
    return tp, fp, fn, p, rc, f1


results = []
with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
    for acct_id, t in sorted(truth.items()):
        hits = detect_all(conn, t["tenant_id"], acct_id)
        flag_a = len(hits) > 0
        flag_b = any(not (h["detector"] == "usage_drop" and h.get("recovered")) for h in hits)
        results.append({
            "account_id": acct_id,
            "tenant_id": t["tenant_id"],
            "at_risk": t["at_risk"],
            "decoy": t["decoy"],
            "difficulty": t["difficulty"],
            "hits": [h["detector"] for h in hits],
            "baseline_a": outcome(flag_a, t["at_risk"]),
            "baseline_b": outcome(flag_b, t["at_risk"]),
        })

print("%-7s %-8s %-6s %-6s %-4s %-4s %s" % ("acct", "truth", "diff", "decoy", "A", "B", "detector hits"))
for r in results:
    print("%-7s %-8s %-6s %-6s %-4s %-4s %s" % (
        r["account_id"], "AT RISK" if r["at_risk"] else "ok", r["difficulty"],
        "yes" if r["decoy"] else "", r["baseline_a"], r["baseline_b"], ", ".join(r["hits"]) or "-"))

print()
for key, label in (("baseline_a", "Baseline A (any detector)"), ("baseline_b", "Baseline B (ignore recovered dips)")):
    tp, fp, fn, p, rc, f1 = metrics(results, key)
    print("%-36s TP=%d FP=%d FN=%d  precision=%.2f recall=%.2f F1=%.2f" % (label, tp, fp, fn, p, rc, f1))

Path("data/detector_baseline.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
print("\nSaved data/detector_baseline.json")
