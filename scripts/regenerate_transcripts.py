import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from groq import Groq

from backend import settings

client = Groq(api_key=settings.GROQ_API_KEY)
TRANSCRIPTS = Path("data/call_transcripts.json")
briefs = {b["id"]: b for b in json.loads(Path("data/call_briefs.json").read_text(encoding="utf-8"))}
transcripts = {t["id"]: t for t in json.loads(TRANSCRIPTS.read_text(encoding="utf-8"))}
audit = json.loads(Path("data/transcript_audit_v1.json").read_text(encoding="utf-8"))
to_fix = [a["id"] for a in audit if not a["pass"]]

STYLE = {
    "explicit": "State the fact plainly, in the customer's own words.",
    "indirect": "Only hint at the fact in passing, with casual indirect phrasing. Nobody calls it a problem, but a careful reader can still tell exactly what it means.",
    "none": "This is an ordinary, positive or neutral call. Nothing about the account's health is in doubt.",
}

GEN = """Write a realistic transcript of a customer success call.

Call title: {title}
Date: {date}
CSM: {csm}
Customer attendees: {attendees}

FACTS THAT MUST APPEAR (this is the only substantive content about the account's situation): {brief}

Rules:
- Format every line as "Speaker Name: what they say".
- 350 to 500 words.
- Natural speech: filler words, small talk, tangents, and a couple of unrelated topics (a feature question, scheduling, a joke). The unrelated topics must be neutral: no complaints, delays, budget talk, staffing changes, competitors, approvals or doubts.
- Every fact in FACTS must be present, said by the right person, in the middle of the call, not at the very start or the very end. {style}
- Do not add any other reason, concern, plan or event related to the account's health beyond the FACTS. Do not invent approvals, sign-offs, reviews or deadlines that are not in the FACTS.
- If the FACTS say a person is leaving or joining, make it clear enough that a reader can tell who that person is and what their role is.
- Do not use the words churn, risk or at-risk. No notes or summary outside the dialogue.
- Output only the transcript."""

AUDIT = """You are auditing a synthetic call transcript for data quality.

FACT THAT MUST BE CONVEYED: {brief}

TRANSCRIPT:
{transcript}

Does the transcript convey every key fact in the FACT above? Indirect or hinted wording counts, and so does a plain statement. But a fact that is missing, softened until it no longer carries the same meaning, or replaced by something different does not count.

Also check: does the transcript state any important fact that contradicts the FACT or adds a different reason that is not in the FACT (for example a different cause for the situation)?

Return only JSON:
{{"conveyed": true or false, "contradicts_or_adds_cause": true or false, "evidence": "a short phrase of at most 12 words from the transcript, or empty", "missing": "what is missing, or empty"}}"""


def chat(prompt, json_mode, temperature, max_tokens):
    kwargs = dict(
        model=settings.LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
        extra_body={"reasoning_effort": "medium" if json_mode else "low"},
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    for _ in range(8):
        try:
            res = client.chat.completions.create(**kwargs)
            text = (res.choices[0].message.content or "").strip()
            if text:
                return text
            kwargs["max_tokens"] = max_tokens * 2
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
    raise RuntimeError("LLM call failed")


def passes(brief_text, transcript):
    if re.search(r"\b(churn|risk)\b", transcript, re.I):
        return False, "contains a banned word"
    r = json.loads(chat(AUDIT.format(brief=brief_text, transcript=transcript), True, 0, 2000))
    ok = bool(r.get("conveyed")) and not bool(r.get("contradicts_or_adds_cause"))
    return ok, r.get("missing") or ""


log = {}
for n, cid in enumerate(to_fix, start=1):
    b = briefs[cid]
    best, ok, note = None, False, ""
    for attempt in range(1, 4):
        prompt = GEN.format(
            title=b["title"], date=b["occurred_on"], csm=b["csm"],
            attendees=", ".join(b["customer_attendees"]), brief=b["brief"], style=STYLE[b["signal"]],
        )
        text = chat(prompt, False, 0.8, 3000)
        ok, note = passes(b["brief"], text)
        best = text
        print("[%d/%d] %-14s attempt %d: %s" % (n, len(to_fix), cid, attempt, "PASS" if ok else "FAIL " + note[:60]))
        if ok:
            break
        time.sleep(2)
    transcripts[cid]["transcript"] = best
    log[cid] = {"attempts": attempt, "passed": ok}
    TRANSCRIPTS.write_text(json.dumps(list(transcripts.values()), indent=1), encoding="utf-8")
    time.sleep(2)

Path("data/regen_log.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
print()
print("regenerated: %d | passed audit: %d | still failing: %s" % (
    len(log), sum(1 for v in log.values() if v["passed"]),
    [k for k, v in log.items() if not v["passed"]] or "none"))
