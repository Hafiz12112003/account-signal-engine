import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

load_dotenv()
client = Groq(api_key=os.environ["GROQ_API_KEY"])
MODEL = "openai/gpt-oss-120b"
OUT = Path("data/call_transcripts.json")

briefs = json.loads(Path("data/call_briefs.json").read_text(encoding="utf-8"))

done = {}
if OUT.exists():
    for t in json.loads(OUT.read_text(encoding="utf-8")):
        done[t["id"]] = t

STYLE = {
    "explicit": "The key point is stated plainly, but it comes up in the middle of the call, not at the start.",
    "indirect": "The key point is only hinted at through vague, indirect phrasing in passing. Nobody states it directly and nobody names it as a problem.",
    "none": "This is an ordinary call. Nothing alarming is said.",
}

PROMPT = """Write a realistic transcript of a customer success call.

Call title: {title}
Date: {date}
CSM: {csm}
Customer attendees: {attendees}

What happens on the call: {brief}

Rules:
- Format every line as "Speaker Name: what they say".
- 350 to 500 words.
- Natural speech: filler words, small talk, tangents, a bit of rambling, and a couple of unrelated topics (a feature question, scheduling, a joke).
- {style}
- Do not use the words churn, risk, or at-risk, and do not add notes or a summary outside the dialogue.
- Output only the transcript."""


def generate(b):
    prompt = PROMPT.format(
        title=b["title"],
        date=b["occurred_on"],
        csm=b["csm"],
        attendees=", ".join(b["customer_attendees"]),
        brief=b["brief"],
        style=STYLE[b["signal"]],
    )
    kwargs = dict(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=3000,
        temperature=0.9,
        extra_body={"reasoning_effort": "low"},
    )
    for attempt in range(8):
        try:
            res = client.chat.completions.create(**kwargs)
            text = (res.choices[0].message.content or "").strip()
            if text:
                return text
            kwargs["max_tokens"] = 5000
        except Exception as e:
            msg = str(e).lower()
            if "reasoning" in msg and "extra_body" in kwargs:
                kwargs.pop("extra_body")
                continue
            if "429" in msg or "rate" in msg:
                print("   rate limited, waiting 30s...")
                time.sleep(30)
                continue
            raise
    raise RuntimeError("failed after retries: " + b["id"])


for i, b in enumerate(briefs, start=1):
    if b["id"] in done:
        print("[%d/%d] %s already done" % (i, len(briefs), b["id"]))
        continue
    text = generate(b)
    done[b["id"]] = dict(
        id=b["id"],
        tenant_id=b["tenant_id"],
        account_id=b["account_id"],
        occurred_on=b["occurred_on"],
        title=b["title"],
        transcript=text,
    )
    OUT.write_text(json.dumps(list(done.values()), indent=1), encoding="utf-8")
    print("[%d/%d] %s done (%d words)" % (i, len(briefs), b["id"], len(text.split())))
    time.sleep(4)

print("All transcripts saved to", OUT)
