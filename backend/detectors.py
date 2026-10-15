from statistics import median

STAGE_RANK = {"Pipeline": 1, "Best Case": 2, "Commit": 3}
DROP_THRESHOLD = 0.10
SLIP_DAYS = 14

USAGE_SQL = """
WITH mx AS (
    SELECT max(occurred_on) AS m FROM usage_events
    WHERE tenant_id = %(t)s AND account_id = %(a)s
)
SELECT ((mx.m - u.occurred_on) / 7) AS wk,
       avg(u.active_users)::float AS avg_users,
       min(u.occurred_on) AS first_day,
       max(u.occurred_on) AS last_day
FROM usage_events u, mx
WHERE u.tenant_id = %(t)s AND u.account_id = %(a)s
  AND extract(dow from u.occurred_on) NOT IN (0, 6)
  AND (mx.m - u.occurred_on) < 56
GROUP BY wk
ORDER BY wk
"""

CRM_SQL = """
SELECT id, snapshot_date, stage, close_date, champion
FROM crm_snapshots
WHERE tenant_id = %s AND account_id = %s
ORDER BY snapshot_date
"""


def detect_usage(conn, tenant_id, account_id):
    rows = conn.execute(USAGE_SQL, {"t": tenant_id, "a": account_id}).fetchall()
    weeks = {wk: (avg, first, last) for wk, avg, first, last in rows}
    baseline_vals = [weeks[w][0] for w in (4, 5, 6, 7) if w in weeks]
    if len(baseline_vals) < 3:
        return []
    baseline = median(baseline_vals)
    if baseline <= 0:
        return []

    drops = {}
    for w in (0, 1, 2, 3):
        if w in weeks:
            drops[w] = 1 - weeks[w][0] / baseline

    flagged = [w for w, d in drops.items() if d >= DROP_THRESHOLD]
    if not flagged:
        return []

    worst_w = max(flagged, key=lambda w: drops[w])
    first, last = weeks[worst_w][1], weeks[worst_w][2]
    latest_drop = drops.get(0, 0.0)
    recovered = latest_drop < DROP_THRESHOLD
    summary = (
        "Weekday active users fell %.0f%% below the baseline (%.0f users/day) in the week of %s to %s. "
        "The most recent week is %.0f%% %s the baseline."
        % (
            drops[worst_w] * 100, baseline, first, last,
            abs(latest_drop) * 100, "below" if latest_drop >= 0 else "above",
        )
    )
    return [{
        "detector": "usage_drop",
        "summary": summary,
        "worst_drop": round(drops[worst_w], 3),
        "latest_drop": round(latest_drop, 3),
        "recovered": recovered,
        "citations": ["usage:%s:%s..%s" % (account_id, first, last)],
    }]


def detect_crm(conn, tenant_id, account_id):
    rows = conn.execute(CRM_SQL, (tenant_id, account_id)).fetchall()
    if len(rows) < 2:
        return []
    first, latest = rows[0], rows[-1]
    f_id, f_date, f_stage, f_close, f_champ = first
    l_id, l_date, l_stage, l_close, l_champ = latest
    cites = ["crm:%d" % f_id, "crm:%d" % l_id]
    hits = []

    if STAGE_RANK.get(l_stage, 0) < STAGE_RANK.get(f_stage, 0):
        hits.append({
            "detector": "stage_downgrade",
            "summary": "CRM stage moved from %s (%s) to %s (%s)." % (f_stage, f_date, l_stage, l_date),
            "citations": cites,
        })

    if f_close and l_close and (l_close - f_close).days >= SLIP_DAYS:
        hits.append({
            "detector": "close_date_slip",
            "summary": "Expected close date moved from %s to %s (+%d days)." % (f_close, l_close, (l_close - f_close).days),
            "citations": cites,
        })

    if f_champ != l_champ:
        hits.append({
            "detector": "champion_change",
            "summary": "Champion on the CRM record changed from %s to %s." % (f_champ, l_champ),
            "citations": cites,
        })

    return hits


def detect_all(conn, tenant_id, account_id):
    return detect_usage(conn, tenant_id, account_id) + detect_crm(conn, tenant_id, account_id)
