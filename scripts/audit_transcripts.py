import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from groq import Groq

from backend import settings

client = Groq(api_key=settings.GROQ_API_KEY)
briefs = {b["id"]: b for b in json.loads(Path("data/call_briefs.json").read_text(encoding="utf-8"))}
transcripts = {t["id"]: t for t in json.loads(Path("data/call_transcripts.json").read_text(encoding="utf-8"))}

PROMPT = """You are auditing a synthetic call transcript for data quality.

FACT THAT MUST BE CONVEYED: {brief}

TRANSCRIPT:
{transcript}

Does the transcript convey every key fact in the FACT above? Indirect or hinted wording counts, and so does a plain statement. But a fact that is missing, softened until it no longer carries the same meaning, or replaced by something different does not count.

Also check: does the transcript state any important fact that contradicts the FACT or adds a different reason that is not in the FACT (for example a different cause for the situation)?

Return only JSON:
{{"conveyed": true or false, "contradicts_or_adds_cause": true or false, "evidence": "a short phrase of at most 12 words from the transcript, or empty", "missing": "what is missing, or empty"}}"""


def ask(prompt):
    kwargs = dict(
        model=settings.LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
        temperature=0,
        response_format={"type": "json_object"},
        extra_body={"reasoning_effort": "medium"},
    )
    for _ in range(8):
        try:
            res = client.chat.completions.create(**kwargs)
            text = (res.choices[0].message.content or "").strip()
            if text:
                return json.loads(text)
            kwargs["max_tokens"] = 4000
        except Exception as e:
            msg = str(e).lower()
            if "connection" in msg or "timeout" in msg:
                time.sleep(5)
            elif "429" in msg or "rate" in msg:
                time.sleep(30)
            elif "reasoning" in msg and "extra_body" in kwargs:
                kwargs.pop("extra_body")
            elif "response_format" in msg and "response_format" in kwargs:
                kwargs.pop("response_format")
            else:
                raise
    raise RuntimeError("audit call failed")


rows = []
for i, cid in enumerate(sorted(briefs), start=1):
    b, t = briefs[cid], transcripts[cid]
    r = ask(PROMPT.format(brief=b["brief"], transcript=t["transcript"]))
    ok = bool(r.get("conveyed")) and not bool(r.get("contradicts_or_adds_cause"))
    rows.append({"id": cid, "account_id": b["account_id"], "signal": b["signal"], "pass": ok, **r})
    print("[%d/%d] %-14s %s" % (i, len(briefs), cid, "PASS" if ok else "FAIL"))
    time.sleep(2)

Path("data/transcript_audit.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")

print()
fails = [r for r in rows if not r["pass"]]
print("passed: %d of %d" % (len(rows) - len(fails), len(rows)))
for r in fails:
    print("\nFAIL %s (%s)" % (r["id"], r["signal"]))
    print("  conveyed: %s | contradicts/adds cause: %s" % (r.get("conveyed"), r.get("contradicts_or_adds_cause")))
    print("  missing: %s" % r.get("missing", ""))
print("\nSaved data/transcript_audit.json")
