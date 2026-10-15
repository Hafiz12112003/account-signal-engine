import json
import random
from datetime import date, timedelta
from pathlib import Path

rng = random.Random(42)
END = date(2026, 10, 14)
DAYS = 60
START = END - timedelta(days=DAYS - 1)
WEEKS = 9
OUT = Path("data")
OUT.mkdir(exist_ok=True)

TENANTS = [
    {"id": "t_cloudmetric", "name": "CloudMetric"},
    {"id": "t_flowdesk", "name": "FlowDesk"},
]

def acct(id, tenant, name, segment, arr, users, usage, crm, champion, renewal_in, owner):
    return dict(id=id, tenant=tenant, name=name, segment=segment, arr=arr, users=users,
                usage=usage, crm=crm, champion=champion, renewal_in=renewal_in, owner=owner)

ACCOUNTS = [
    acct("cm-01", "t_cloudmetric", "Brightwave Logistics", "Mid-market", 84000, 120, "decline", "steady", "Anita Rao", 45, "Dev Kapoor"),
    acct("cm-02", "t_cloudmetric", "Harbor and Pine Retail", "Mid-market", 62000, 80, "mild_decline", "champion_left", "Marcus Lee", 50, "Dev Kapoor"),
    acct("cm-03", "t_cloudmetric", "Orchid Health Partners", "Enterprise", 210000, 300, "steady", "slip", "Sunita Verma", 38, "Ria Shah"),
    acct("cm-04", "t_cloudmetric", "Kestrel Foods", "Mid-market", 58000, 95, "dip_week", "steady", "Tom Becker", 70, "Ria Shah"),
    acct("cm-05", "t_cloudmetric", "Lumen Education", "SMB", 24000, 40, "steady", "steady", "Farah Iqbal", 85, "Dev Kapoor"),
    acct("cm-06", "t_cloudmetric", "Atlas Freight", "Enterprise", 175000, 260, "growth", "steady", "Greg Salazar", 90, "Ria Shah"),
    acct("cm-07", "t_cloudmetric", "Sable Studios", "Mid-market", 71000, 70, "steady", "steady", "Nina Petrov", 42, "Dev Kapoor"),
    acct("cm-08", "t_cloudmetric", "Quill Legal", "SMB", 31000, 35, "steady", "steady", "Raj Malhotra", 75, "Ria Shah"),
    acct("fd-01", "t_flowdesk", "Tidewater Insurance", "Enterprise", 240000, 340, "decline", "steady", "Helen Cho", 40, "Sam Ortiz"),
    acct("fd-02", "t_flowdesk", "Northgate Robotics", "Mid-market", 96000, 110, "mild_decline", "champion_and_slip", "Vikram Nair", 35, "Sam Ortiz"),
    acct("fd-03", "t_flowdesk", "Fernhill Media", "Mid-market", 67000, 85, "steady", "steady", "Alicia Gomez", 48, "Mei Tan"),
    acct("fd-04", "t_flowdesk", "Copperline Energy", "Enterprise", 188000, 220, "dip_migration", "steady", "Peter Hanson", 66, "Mei Tan"),
    acct("fd-05", "t_flowdesk", "Juniper Travel", "SMB", 29000, 45, "steady", "steady", "Lina Haddad", 80, "Sam Ortiz"),
    acct("fd-06", "t_flowdesk", "Redwood Biotech", "Mid-market", 89000, 100, "growth", "steady", "Omar Siddiqui", 88, "Mei Tan"),
    acct("fd-07", "t_flowdesk", "Granite Builders", "Mid-market", 54000, 75, "steady", "procurement", "Beth Walker", 30, "Sam Ortiz"),
    acct("fd-08", "t_flowdesk", "Meridian Pet Care", "SMB", 22000, 30, "steady", "steady", "Carlos Rivera", 72, "Mei Tan"),
]

# (offset_days_from_END, title, signal_strength, brief, attendees_override)
CALLS = {
    "cm-01": [
        (-34, "Quarterly check-in", "indirect", "Customer says rollout to the second warehouse team is delayed. Mild frustration about onboarding, nothing alarming.", None),
        (-9, "Renewal prep call", "explicit", "Customer says finance froze new software spend until next fiscal year and is reviewing every tool. Asks what happens if they cut seats at renewal.", None),
    ],
    "cm-02": [
        (-30, "Routine product call", "indirect", "Champion Marcus is positive about the product but mentions in passing that he is moving on to a new role soon.", None),
        (-8, "Intro call with new contact", "explicit", "An interim contact who is new admits she has not used the product and asks basic questions about why the company pays for it.", ["Priya Menon"]),
    ],
    "cm-03": [
        (-28, "Executive sponsor call", "indirect", "Sponsor is positive on the product but asks detailed pricing comparison questions and hints procurement is looking at the market.", None),
        (-7, "Renewal status call", "explicit", "Legal and procurement review of the renewal is taking longer, a competitor was invited to present, and the decision may slip past the renewal date.", None),
    ],
    "cm-04": [
        (-40, "Planning call", "none", "Customer mentions their whole company will be on a planned shutdown week for the annual offsite and asks if anything needs doing before then.", None),
        (-6, "Post-offsite check-in", "none", "Team is back and busy, asks about new reporting features, positive tone.", None),
    ],
    "cm-05": [
        (-30, "Onboarding call", "none", "Onboarding three new team members, asks how to set up dashboards.", None),
        (-10, "Billing call", "none", "Short call about invoice formatting, mentions they plan to keep the plan as is.", None),
    ],
    "cm-06": [
        (-25, "Adoption review", "none", "Customer is excited about adoption across departments and asks about adding 40 seats.", None),
        (-5, "Expansion pricing", "none", "Pricing discussion for the expansion, customer wants a multi-year deal.", None),
    ],
    "cm-07": [
        (-30, "Quarterly check-in", "indirect", "Normal-sounding call, but the champion keeps saying things are a bit up in the air internally and that priorities are being re-looked at by leadership. No explicit complaint about the product.", None),
        (-8, "Follow-up call", "indirect", "Champion is less engaged, has cancelled the last two scheduled calls, says lets see how next quarter shapes up and steers away from renewal talk. Never says anything negative about the product.", None),
    ],
    "cm-08": [
        (-22, "Support follow-up", "none", "Routine call, a small bug was reported and resolved, customer is happy.", None),
        (-4, "Catch-up", "none", "Quick catch-up, customer says all good and see you at renewal.", None),
    ],
    "fd-01": [
        (-33, "Quarterly check-in", "explicit", "Customer says the team has been using a competitor tool for new projects because it integrates better with their stack.", None),
        (-10, "Escalation call", "explicit", "Customer complains about two unresolved support tickets, says adoption is falling and their VP is asking whether to consolidate tools.", None),
    ],
    "fd-02": [
        (-29, "Product call", "indirect", "Champion Vikram mentions a reorg and that he may be changing teams.", None),
        (-9, "Stakeholder intro", "explicit", "A new stakeholder joins and says budget has been moved to another initiative and renewal timing is uncertain.", ["Vikram Nair", "Joel Briggs"]),
    ],
    "fd-03": [
        (-27, "Executive check-in", "indirect", "Friendly call, but the executive sponsor mentions in passing that she leaves the company at month end and that her replacement has their own preferred vendors.", None),
        (-7, "Call with incoming owner", "indirect", "The incoming owner is polite and noncommittal and asks for a list of all contracts and costs in the account without saying why.", ["Alicia Gomez", "Daniel Okafor"]),
    ],
    "fd-04": [
        (-37, "Planning call", "none", "Customer explains they are migrating their data warehouse over the next few weeks so usage will temporarily drop, and they plan to resume fully afterwards.", None),
        (-5, "Post-migration call", "none", "Migration is finished, the team is ramping back up, and they ask for help reconnecting integrations.", None),
    ],
    "fd-05": [
        (-28, "Routine check-in", "none", "Routine check-in, asks about training resources.", None),
        (-6, "Billing question", "none", "Positive call, asks about an annual billing discount.", None),
    ],
    "fd-06": [
        (-26, "Expansion call", "none", "Expanding to a second lab team, asks about enterprise features.", None),
        (-4, "Reference call", "none", "Champion offers to be a reference customer.", None),
    ],
    "fd-07": [
        (-24, "Renewal logistics", "none", "Customer says procurement requires an extra vendor-security review this year, which delays signing paperwork, but they confirm they are renewing.", None),
        (-5, "Security review follow-up", "none", "Security questionnaire answered, signature expected in two weeks, customer is happy.", None),
    ],
    "fd-08": [
        (-20, "Routine call", "none", "Routine call with a small feature request.", None),
        (-3, "Renewal intent", "none", "Short call confirming they intend to renew.", None),
    ],
}

GROUND_TRUTH = {
    "cm-01": dict(at_risk=True, cause="budget_freeze_with_usage_decline", difficulty="easy", decoy=False),
    "cm-02": dict(at_risk=True, cause="champion_left", difficulty="medium", decoy=False),
    "cm-03": dict(at_risk=True, cause="renewal_slip_competitor_eval", difficulty="easy", decoy=False),
    "cm-04": dict(at_risk=False, cause="planned_shutdown_week", difficulty="medium", decoy=True),
    "cm-05": dict(at_risk=False, cause="healthy", difficulty="easy", decoy=False),
    "cm-06": dict(at_risk=False, cause="healthy_growing", difficulty="easy", decoy=False),
    "cm-07": dict(at_risk=True, cause="silent_disengagement", difficulty="hard", decoy=False),
    "cm-08": dict(at_risk=False, cause="healthy", difficulty="easy", decoy=False),
    "fd-01": dict(at_risk=True, cause="competitor_adoption_with_usage_decline", difficulty="easy", decoy=False),
    "fd-02": dict(at_risk=True, cause="champion_reorg_budget_moved", difficulty="medium", decoy=False),
    "fd-03": dict(at_risk=True, cause="sponsor_leaving_vendor_review", difficulty="hard", decoy=False),
    "fd-04": dict(at_risk=False, cause="data_migration_temporary_dip", difficulty="medium", decoy=True),
    "fd-05": dict(at_risk=False, cause="healthy", difficulty="easy", decoy=False),
    "fd-06": dict(at_risk=False, cause="healthy_growing", difficulty="easy", decoy=False),
    "fd-07": dict(at_risk=False, cause="procurement_delay_renewal_confirmed", difficulty="medium", decoy=True),
    "fd-08": dict(at_risk=False, cause="healthy", difficulty="easy", decoy=False),
}

def multiplier(pattern, d):
    if pattern == "steady":
        return 1.0
    if pattern == "growth":
        return 1.0 + 0.004 * d
    if pattern == "decline":
        return 1.0 if d < 28 else 1.0 - 0.45 * (d - 28) / (DAYS - 1 - 28)
    if pattern == "mild_decline":
        return 1.0 if d < 28 else 1.0 - 0.15 * (d - 28) / (DAYS - 1 - 28)
    if pattern == "dip_week":
        return 0.25 if 38 <= d <= 44 else 1.0
    if pattern == "dip_migration":
        return 0.45 if 34 <= d <= 45 else 1.0
    raise ValueError(pattern)

def crm_rows(a):
    rows = []
    renewal = END + timedelta(days=a["renewal_in"])
    for i in range(WEEKS):
        snap = END - timedelta(days=7 * (WEEKS - 1 - i))
        stage, close, champ = "Commit", renewal, a["champion"]
        kind = a["crm"]
        if kind == "slip" and i >= 5:
            stage, close = "Best Case", renewal + timedelta(days=45)
        elif kind == "champion_left" and i >= 5:
            champ = "Priya Menon (interim)"
        elif kind == "champion_and_slip":
            if i >= 4:
                champ = "(none listed)"
            if i >= 6:
                stage, close = "Best Case", renewal + timedelta(days=30)
        elif kind == "procurement" and i >= 6:
            close = renewal + timedelta(days=21)
        rows.append(dict(tenant_id=a["tenant"], account_id=a["id"], snapshot_date=snap.isoformat(),
                         stage=stage, amount=a["arr"], close_date=close.isoformat(), champion=champ))
    return rows

accounts_out, usage_out, crm_out, briefs_out = [], [], [], []

for a in ACCOUNTS:
    renewal = END + timedelta(days=a["renewal_in"])
    accounts_out.append(dict(id=a["id"], tenant_id=a["tenant"], name=a["name"], segment=a["segment"],
                             arr=a["arr"], renewal_date=renewal.isoformat(), owner=a["owner"]))
    for d in range(DAYS):
        day = START + timedelta(days=d)
        m = multiplier(a["usage"], d) * rng.uniform(0.92, 1.08)
        if day.weekday() >= 5:
            m *= 0.3
        users = max(1, round(a["users"] * m))
        events = round(users * rng.uniform(14, 22))
        usage_out.append(dict(tenant_id=a["tenant"], account_id=a["id"], occurred_on=day.isoformat(),
                              active_users=users, feature_events=events))
    crm_out.extend(crm_rows(a))
    for n, (offset, title, signal, brief, attendees) in enumerate(CALLS[a["id"]], start=1):
        briefs_out.append(dict(id="call-%s-%d" % (a["id"], n), tenant_id=a["tenant"], account_id=a["id"],
                               occurred_on=(END + timedelta(days=offset)).isoformat(), title=title,
                               customer_attendees=attendees or [a["champion"]], csm=a["owner"],
                               signal=signal, brief=brief))

seed = dict(tenants=TENANTS, accounts=accounts_out, usage_events=usage_out, crm_snapshots=crm_out)
truth = {k: dict(v, tenant_id=next(x["tenant"] for x in ACCOUNTS if x["id"] == k)) for k, v in GROUND_TRUTH.items()}

(OUT / "seed.json").write_text(json.dumps(seed, indent=1), encoding="utf-8")
(OUT / "call_briefs.json").write_text(json.dumps(briefs_out, indent=1), encoding="utf-8")
(OUT / "ground_truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")

print("tenants:", len(TENANTS))
print("accounts:", len(accounts_out))
print("usage rows:", len(usage_out))
print("crm rows:", len(crm_out))
print("call briefs:", len(briefs_out))
print("at risk:", sum(1 for v in truth.values() if v["at_risk"]),
      "| decoys:", sum(1 for v in truth.values() if v["decoy"]))
