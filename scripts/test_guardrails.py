import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
from fastapi.testclient import TestClient
from fastembed import TextEmbedding
from pgvector.psycopg import register_vector

from backend import correlator, settings, worker
from backend.app import app

results = []


def check(name, ok, detail=""):
    results.append({"test": name, "passed": bool(ok), "detail": detail})
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, (" (" + detail + ")") if detail else ""))


conn = psycopg.connect(settings.DATABASE_URL, autocommit=True)
register_vector(conn)


def one(sql, params=()):
    return conn.execute(sql, params).fetchone()


FD = ("t_flowdesk", "fd-01")
CM = ("t_cloudmetric", "cm-01")
crm_fd = one("SELECT id FROM crm_snapshots WHERE tenant_id = %s AND account_id = %s LIMIT 1", FD)[0]
crm_cm = one("SELECT id FROM crm_snapshots WHERE tenant_id = %s AND account_id = %s LIMIT 1", CM)[0]
chunk_cm = one("SELECT id FROM transcript_chunks WHERE tenant_id = %s AND account_id = %s LIMIT 1", CM)[0]

print("--- provenance checks ---")

v, bad = correlator.verify_citations(conn, FD[0], FD[1], ["crm:%d" % crm_fd])
check("a real citation is accepted", v == ["crm:%d" % crm_fd] and not bad)

fabricated = ["crm:99999999", "chunk:99999999", "usage:fd-01:2020-01-01..2020-01-07", "made-up-id"]
v, bad = correlator.verify_citations(conn, FD[0], FD[1], fabricated)
check("fabricated citations are all rejected", not v and len(bad) == 4, "%d of 4 rejected" % len(bad))

cross = ["crm:%d" % crm_cm, "chunk:%d" % chunk_cm, "usage:cm-01:2026-10-01..2026-10-07"]
v, bad = correlator.verify_citations(conn, FD[0], FD[1], cross)
check("citations to another tenant's records are rejected", not v and len(bad) == 3, "%d of 3 rejected" % len(bad))

embedder = TextEmbedding(model_name=settings.EMBED_MODEL)
META = {"latency_s": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def fake(verdict, confidence, citations):
    def _llm(client, prompt):
        body = {"verdict": verdict, "confidence": confidence, "cause": "competitor_risk",
                "summary": "Synthetic finding for the guardrail test.", "citations": citations}
        return json.dumps(body), META
    return _llm


good = "crm:%d" % crm_fd

correlator.call_llm = fake("at_risk", 0.95, ["crm:99999999", "chunk:99999999"])
r = correlator.analyze_account(conn, embedder, None, FD[0], FD[1])
check("a finding with only fabricated citations is rejected", r["status"] == "rejected_invalid_citation", r["status"])

correlator.call_llm = fake("at_risk", 0.95, [good, "crm:99999999"])
r = correlator.analyze_account(conn, embedder, None, FD[0], FD[1])
check("one bad citation rejects the whole finding", r["status"] == "rejected_invalid_citation", r["status"])

correlator.call_llm = fake("at_risk", 0.95, [])
r = correlator.analyze_account(conn, embedder, None, FD[0], FD[1])
check("a finding with no citations is rejected", r["status"] == "rejected_no_evidence", r["status"])

correlator.call_llm = fake("at_risk", 0.95, [good])
r = correlator.analyze_account(conn, embedder, None, FD[0], FD[1])
check("a finding with a valid citation is accepted", r["status"] == "accepted", r["status"])

correlator.call_llm = fake("at_risk", 0.40, [good])
r = correlator.analyze_account(conn, embedder, None, FD[0], FD[1])
check("a low-confidence at_risk verdict downgrades to needs_review",
      r["verdict"] == "needs_review" and r["downgraded"], "%s, downgraded=%s" % (r["verdict"], r["downgraded"]))

print("\n--- tenant isolation checks ---")

api = TestClient(app)
H_FD = {"X-Tenant-Id": "t_flowdesk"}
H_CM = {"X-Tenant-Id": "t_cloudmetric"}

fd_ids = {f["account_id"] for f in api.get("/api/findings", headers=H_FD).json()}
cm_ids = {f["account_id"] for f in api.get("/api/findings", headers=H_CM).json()}
check("flowdesk sees only flowdesk accounts", bool(fd_ids) and all(a.startswith("fd-") for a in fd_ids), "%d accounts" % len(fd_ids))
check("cloudmetric sees only cloudmetric accounts", bool(cm_ids) and all(a.startswith("cm-") for a in cm_ids), "%d accounts" % len(cm_ids))

cm_finding = one("SELECT id FROM findings WHERE tenant_id = %s LIMIT 1", ("t_cloudmetric",))[0]
check("reading another tenant's finding returns 404",
      api.get("/api/findings/%d" % cm_finding, headers=H_FD).status_code == 404)

cm_play = one("SELECT id FROM plays WHERE tenant_id = %s AND status = 'pending' LIMIT 1", ("t_cloudmetric",))[0]
res = api.post("/api/plays/%d/decision" % cm_play, headers=H_FD, json={"decision": "reject", "actor": "tester"})
still = one("SELECT status FROM plays WHERE id = %s", (cm_play,))[0]
check("deciding another tenant's play returns 404 and changes nothing",
      res.status_code == 404 and still == "pending", "status %d, play is %s" % (res.status_code, still))

check("a request with no tenant header returns 400", api.get("/api/findings").status_code == 400)
check("an unknown tenant returns 404",
      api.get("/api/findings", headers={"X-Tenant-Id": "t_nobody"}).status_code == 404)

event = {"tenant_id": "t_flowdesk", "account_id": "fd-01", "occurred_on": "2026-10-14", "active_users": 1, "feature_events": 1}
check("the webhook rejects a wrong secret",
      api.post("/webhooks/usage", json=event, headers={"X-Webhook-Secret": "wrong"}).status_code == 401)
check("the webhook rejects an event with missing fields",
      api.post("/webhooks/usage", json={"tenant_id": "t_flowdesk"}, headers={"X-Webhook-Secret": settings.WEBHOOK_SECRET}).status_code == 422)

wrong = dict(event, account_id="cm-01")
try:
    worker.handle(conn, None, "usage", wrong)
    refused = False
except ValueError as e:
    refused = "does not belong" in str(e)
rows = one("SELECT count(*) FROM usage_events WHERE tenant_id = %s AND account_id = %s", ("t_flowdesk", "cm-01"))[0]
check("the worker refuses an event that names the wrong tenant for an account and stores nothing",
      refused and rows == 0, "rows stored: %d" % rows)

passed = sum(1 for r in results if r["passed"])
print("\n%d of %d checks passed" % (passed, len(results)))
Path("data/guardrail_tests.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
print("Saved data/guardrail_tests.json")
sys.exit(0 if passed == len(results) else 1)
