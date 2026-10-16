import psycopg
from psycopg.types.json import Jsonb

from backend import settings

TEMPLATES = {
    "budget_pressure": (
        "Run a value review and offer a right-sized plan",
        "Hi {contact}, I'd like to set up 30 minutes with you and whoever owns the budget to walk through "
        "what {name} gets from the product today and to look at plan options that fit current spend. "
        "Renewal is on {renewal}, so I'd rather plan this together early. Does this week or next work?",
    ),
    "competitor_risk": (
        "Ask for decision criteria and run a competitive review",
        "Hi {contact}, I understand you're looking at other options, which is completely reasonable. "
        "Could we spend 30 minutes on what matters most to your team, so I can show where we fit and "
        "where we don't? Renewal is on {renewal}.",
    ),
    "champion_departure": (
        "Multi-thread: meet the new stakeholders",
        "Hi {contact}, congratulations on the changes at {name}. Could you introduce me to the people "
        "who will own this going forward? I'd like to give them a short walkthrough and make the "
        "handover easy. Renewal is on {renewal}.",
    ),
    "renewal_delay": (
        "Unblock procurement and legal for the renewal",
        "Hi {contact}, I want to make sure the renewal on {renewal} doesn't get stuck. Is there a "
        "procurement or legal step I can help with, such as a security questionnaire, a redline "
        "turnaround or a call with the reviewers?",
    ),
    "disengagement": (
        "Re-engage the champion with a short value review",
        "Hi {contact}, it's been a while since we caught up properly. Could we do a 20-minute check-in "
        "on how things are going and what you want to see next quarter? I'd also like to hear what "
        "leadership is focused on, so we stay useful to you.",
    ),
    "usage_decline": (
        "Start an adoption review",
        "Hi {contact}, I noticed activity at {name} has changed recently. Could we look at it together "
        "and see whether training, a different setup or a few workflow changes would help your team?",
    ),
    "other": (
        "Review the account with the account owner",
        "Hi {contact}, I'd like to check in on how things are going at {name} and whether there's "
        "anything we could do better before the renewal on {renewal}.",
    ),
}


def build_play(account, finding):
    name, owner, renewal, contact = account
    conf = float(finding["confidence"])
    if finding["kind"] == "needs_review":
        action = "Manual review by %s" % (owner or "the account owner")
        draft = (
            "Internal task, no customer message.\n\n"
            "Signals on %s are mixed (confidence %.2f), so a person should look before anyone acts.\n"
            "Why it was flagged: %s\n\n"
            "Check: the cited call excerpts, whether the CRM record still matches reality, and "
            "whether the champion or sponsor is still in place. Decide whether to escalate or clear it."
            % (name, conf, finding["summary"])
        )
        return action, draft

    action, body = TEMPLATES.get(finding["cause"] or "other", TEMPLATES["other"])
    draft = body.format(contact=contact or "there", name=name, renewal=("%d %s" % (renewal.day, renewal.strftime("%B %Y"))) if renewal else "the renewal date")
    # the rationale is shown separately in the UI
    return action, draft


def generate_plays(conn):
    rows = conn.execute(
        "SELECT f.id, f.tenant_id, f.account_id, f.kind, f.summary, f.confidence, f.cause, "
        "a.name, a.owner, a.renewal_date "
        "FROM findings f JOIN accounts a ON a.id = f.account_id AND a.tenant_id = f.tenant_id "
        "WHERE f.status = 'pending' "
        "AND NOT EXISTS (SELECT 1 FROM plays p WHERE p.finding_id = f.id AND p.tenant_id = f.tenant_id)"
    ).fetchall()
    created = 0
    for fid, tenant_id, account_id, kind, summary, confidence, cause, name, owner, renewal in rows:
        champ = conn.execute(
            "SELECT champion FROM crm_snapshots WHERE tenant_id = %s AND account_id = %s "
            "ORDER BY snapshot_date DESC LIMIT 1", (tenant_id, account_id)
        ).fetchone()
        contact = champ[0].split(" (")[0].split()[0] if champ and champ[0] and not champ[0].startswith("(") else None
        action, draft = build_play(
            (name, owner, renewal, contact),
            {"kind": kind, "summary": summary, "confidence": confidence, "cause": cause},
        )
        pid = conn.execute(
            "INSERT INTO plays (tenant_id, finding_id, action, draft, status) "
            "VALUES (%s, %s, %s, %s, 'pending') RETURNING id",
            (tenant_id, fid, action, draft),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO audit_log (tenant_id, actor, action, entity, entity_id, detail) "
            "VALUES (%s, 'system:playbook', 'play_drafted', 'play', %s, %s)",
            (tenant_id, str(pid), Jsonb({"finding_id": fid, "action": action})),
        )
        created += 1
    return created


if __name__ == "__main__":
    with psycopg.connect(settings.DATABASE_URL, autocommit=True) as conn:
        n = generate_plays(conn)
        total = conn.execute("SELECT count(*) FROM plays").fetchone()[0]
    print("plays created now: %d | plays in database: %d" % (n, total))


