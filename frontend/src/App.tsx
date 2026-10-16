import { useCallback, useEffect, useMemo, useState } from "react";
import { decide, getFinding, getFindings, getTenants } from "./api";
import type { AuditEntry, Evidence, Finding, FindingDetail, Tenant } from "./api";

const CAUSE: Record<string, string> = {
  budget_pressure: "Budget pressure",
  competitor_risk: "Competitor risk",
  champion_departure: "Champion departure",
  renewal_delay: "Renewal delay",
  disengagement: "Disengagement",
  usage_decline: "Usage decline",
  other: "Other",
};

const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

function pct(n: number) {
  return Math.round(n * 100) + "%";
}

function day(s: string | null) {
  if (!s) return "date not set";
  const d = new Date(s.length === 10 ? s + "T00:00:00" : s);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

function stamp(s: string) {
  return new Date(s).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function message(e: unknown) {
  const m = e instanceof Error ? e.message : String(e);
  if (m.toLowerCase().includes("fetch")) {
    return "Cannot reach the API. Check that the backend is running and try again.";
  }
  return m;
}

function look(f: Finding) {
  if (f.status === "approved") return { label: "Approved", dot: "approved", text: "kind-approved" };
  if (f.status === "rejected") return { label: "Rejected", dot: "", text: "kind-rejected" };
  if (f.kind === "at_risk") return { label: "At risk", dot: "risk", text: "kind-risk" };
  return { label: "Needs review", dot: "review", text: "kind-review" };
}

function auditText(a: AuditEntry) {
  const who = a.actor.replace(/^(human|system):/, "");
  switch (a.action) {
    case "finding_created":
      return "Finding created by the correlator";
    case "play_drafted":
      return "Play drafted from the finding";
    case "play_approved":
      return "Play approved by " + who;
    case "play_rejected":
      return "Play rejected by " + who;
    default:
      return a.action + " by " + who;
  }
}

function Gauge({ value, color }: { value: number; color: string }) {
  const R = 44;
  const C = 2 * Math.PI * R;
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const id = requestAnimationFrame(() => setShown(value));
    return () => cancelAnimationFrame(id);
  }, [value]);
  return (
    <div className="gauge" role="img" aria-label={"Confidence " + pct(value)}>
      <svg width="104" height="104" viewBox="0 0 104 104">
        <circle className="gauge-track" cx="52" cy="52" r={R} />
        <circle
          className="gauge-arc"
          cx="52"
          cy="52"
          r={R}
          stroke={color} style={{ color }}
          strokeDasharray={C}
          strokeDashoffset={C * (1 - shown)}
        />
      </svg>
      <div className="gauge-num">
        <span>
          {pct(value)}
          <small>confidence</small>
        </span>
      </div>
    </div>
  );
}

function EvidenceItem({ ev }: { ev: Evidence }) {
  const [open, setOpen] = useState(false);
  const long = ev.text.length > 260;
  return (
    <div className={"ev " + ev.type}>
      <div className="ev-label">{ev.label}</div>
      <p className={"ev-text" + (long && !open ? " clamped" : "")}>{ev.text}</p>
      {long && (
        <button className="ev-toggle" onClick={() => setOpen(!open)}>
          {open ? "Show less" : "Show full excerpt"}
        </button>
      )}
    </div>
  );
}

export default function App() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [tenant, setTenant] = useState("");
  const [all, setAll] = useState<Record<string, Finding[]>>({});
  const [filter, setFilter] = useState<"pending" | "approved" | "rejected">("pending");
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<FindingDetail | null>(null);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [reviewer, setReviewer] = useState(() => {
    try {
      return localStorage.getItem("reviewer") ?? "";
    } catch {
      return "";
    }
  });

  const refreshAll = useCallback(async (ts: Tenant[]) => {
    const entries = await Promise.all(ts.map(async (t) => [t.id, await getFindings(t.id)] as const));
    setAll(Object.fromEntries(entries));
  }, []);

  useEffect(() => {
    let off = false;
    (async () => {
      try {
        const ts = await getTenants();
        if (off) return;
        setTenants(ts);
        if (ts.length) setTenant(ts[0].id);
        await refreshAll(ts);
      } catch (e) {
        if (!off) setError(message(e));
      }
    })();
    return () => {
      off = true;
    };
  }, [refreshAll]);

  const list = all[tenant] ?? [];
  const counts = useMemo(
    () => ({
      pending: list.filter((f) => f.status === "pending").length,
      approved: list.filter((f) => f.status === "approved").length,
      rejected: list.filter((f) => f.status === "rejected").length,
    }),
    [list],
  );
  const visible = list.filter((f) => f.status === filter);
  const tenantName = tenants.find((t) => t.id === tenant)?.name ?? "Accounts";

  const pick = (id: string) => {
    setTenant(id);
    setSelected(null);
    setDetail(null);
    setFilter("pending");
    setError("");
  };

  const open = async (id: number) => {
    setSelected(id);
    setNote("");
    setError("");
    try {
      setDetail(await getFinding(tenant, id));
    } catch (e) {
      setError(message(e));
    }
  };

  const flash = (text: string) => {
    setToast(text);
    window.setTimeout(() => setToast(""), 2400);
  };

  const act = async (choice: "approve" | "reject") => {
    if (!detail || !detail.play) return;
    setBusy(true);
    setError("");
    try {
      await decide(tenant, detail.play.id, choice, reviewer.trim(), note.trim());
      await refreshAll(tenants);
      setDetail(await getFinding(tenant, detail.id));
      setNote("");
      flash(choice === "approve" ? "Play approved" : "Play rejected");
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };

  const onReviewer = (v: string) => {
    setReviewer(v);
    try {
      localStorage.setItem("reviewer", v);
    } catch {
      /* storage can be unavailable */
    }
  };

  const ready = detail !== null && detail.id === selected;
  const canAct = reviewer.trim().length > 0 && !busy;
  const emptyText: Record<string, string> = {
    pending: "Nothing is waiting. New findings appear here after the engine runs.",
    approved: "No plays have been approved yet.",
    rejected: "No plays have been rejected yet.",
  };

  return (
    <div className="shell">
      <aside className="rail">
        <div className="brand">
          Signal engine
          <small>Reads every account, explains what it found, and waits for a person to decide.</small>
        </div>
        <div>
          <div className="rail-label">Workspaces</div>
          {tenants.map((t) => {
            const n = (all[t.id] ?? []).filter((f) => f.status === "pending").length;
            return (
              <button key={t.id} className="tenant-btn" aria-pressed={t.id === tenant} onClick={() => pick(t.id)}>
                <span>{t.name}</span>
                {n > 0 && <span className="tenant-count">{n}</span>}
              </button>
            );
          })}
        </div>
        <div className="rail-foot">
          <label htmlFor="reviewer">Reviewing as</label>
          <input
            id="reviewer"
            value={reviewer}
            placeholder="Your name"
            maxLength={60}
            onChange={(e) => onReviewer(e.target.value)}
          />
          <p className="rail-note">All data in this demo is synthetic.</p>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <h1>{tenantName}</h1>
          <p>Findings the engine wants a person to look at. Each one shows its evidence, and nothing goes out until you approve it.</p>
        </header>
        {error && <div className="error" role="alert">{error}</div>}

        <div className={"workspace" + (selected !== null ? " has-selection" : "")}>
          <section className="list" aria-label="Findings">
            <div className="tabs" role="tablist">
              {(["pending", "approved", "rejected"] as const).map((k) => (
                <button key={k} role="tab" className="tab" aria-selected={filter === k} onClick={() => setFilter(k)}>
                  {(k === "pending" ? "Waiting" : k === "approved" ? "Approved" : "Rejected") + " (" + counts[k] + ")"}
                </button>
              ))}
            </div>
            {visible.length === 0 && (
              <div className="empty">
                <strong>All clear</strong>
                {emptyText[filter]}
              </div>
            )}
            {visible.map((f) => {
              const k = look(f);
              return (
                <button key={f.id} className="row" aria-current={f.id === selected} onClick={() => open(f.id)}>
                  <div className="row-top">
                    <span className="row-name">{f.account_name}</span>
                    <span className="row-conf">{pct(f.confidence)}</span>
                  </div>
                  <div className={"row-kind " + k.text}>
                    <span className={"dot " + k.dot} />
                    {k.label}
                  </div>
                  <div className="row-meta">
                    {(CAUSE[f.cause ?? ""] ?? "Cause unclear") + ", renews " + day(f.renewal_date)}
                  </div>
                </button>
              );
            })}
          </section>

          <section className="detail" aria-live="polite">
            {selected === null && (
              <div className="empty">
                <strong>Pick an account</strong>
                You will see what the engine found, the records behind it, and the play it suggests.
              </div>
            )}
            {selected !== null && !ready && !error && <div className="empty">Loading the evidence.</div>}
            {ready && detail && (
              <div className="detail-inner" data-tone={detail.status === "pending" ? detail.kind : detail.status}>
                <button className="back" onClick={() => setSelected(null)}>Back to the list</button>
                <div className="d-head">
                  <div>
                    <h2 className="d-title">{detail.account_name}</h2>
                    <div className="d-sub">
                      {"Owned by " + (detail.owner ?? "nobody yet") + ". Renews " + day(detail.renewal_date) + ". " +
                        (detail.arr !== null ? money.format(detail.arr) + " a year." : "")}
                    </div>
                    <div className="d-sub">{"Likely cause: " + (CAUSE[detail.cause ?? ""] ?? "unclear")}</div>
                  </div>
                  <Gauge
                    key={detail.id}
                    value={detail.confidence}
                    color={detail.status === "approved" ? "var(--mint)" : detail.status === "rejected" ? "var(--slate)" : detail.kind === "at_risk" ? "var(--ruby)" : "var(--amber)"}
                  />
                </div>

                <p className="lede">{detail.summary}</p>

                <div className="section">
                  <h3>Evidence</h3>
                  <p className="section-hint">
                    Every claim above cites these records. The engine rejects any finding that cites a record that does not exist for this account.
                  </p>
                  <div className="evidence">
                    {detail.evidence.map((ev) => (
                      <EvidenceItem key={ev.id} ev={ev} />
                    ))}
                  </div>
                </div>

                {detail.play && (
                  <div className="section">
                    <h3>Proposed play</h3>
                    <div className="play">
                      <h4 className="play-action">{detail.play.action}</h4>
                      <p className="play-kind">
                        {detail.kind === "needs_review"
                          ? "Internal task. Nothing is sent to the customer."
                          : "Draft message. Nothing is sent from here."}
                      </p>
                      <div className="draft">{detail.play.draft}</div>
                      {detail.play.status === "pending" ? (
                        <>
                          <textarea
                            className="note"
                            aria-label="Note for the audit log"
                            placeholder="Add a note for the audit log (optional)"
                            value={note}
                            maxLength={500}
                            onChange={(e) => setNote(e.target.value)}
                          />
                          <div className="actions">
                            <button className="btn btn-approve" disabled={!canAct} onClick={() => act("approve")}>
                              Approve play
                            </button>
                            <button className="btn btn-reject" disabled={!canAct} onClick={() => act("reject")}>
                              Reject play
                            </button>
                          </div>
                          <p className="hint">
                            {reviewer.trim()
                              ? "Approving marks the play ready for the account owner to send."
                              : "Add your name in the left rail to approve or reject."}
                          </p>
                        </>
                      ) : (
                        <div className={"decided " + detail.play.status}>
                          {detail.play.status === "approved" ? "Approved" : "Rejected"}
                        </div>
                      )}
                    </div>
                  </div>
                )}

                <div className="section">
                  <h3>Activity</h3>
                  <ol className="audit">
                    {detail.audit.map((a, i) => {
                      const n = typeof a.detail?.note === "string" ? a.detail.note : "";
                      return (
                        <li key={i}>
                          {auditText(a)}
                          <time>{stamp(a.created_at)}</time>
                          {n && <div>{"Note: " + n}</div>}
                        </li>
                      );
                    })}
                  </ol>
                </div>
              </div>
            )}
          </section>
        </div>
      </main>
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}

