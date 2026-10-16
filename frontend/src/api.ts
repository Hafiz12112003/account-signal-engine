export const API = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://127.0.0.1:8000";

export type Tenant = { id: string; name: string };

export type Play = { id: number; action: string; draft: string; status: string };

export type Finding = {
  id: number;
  account_id: string;
  account_name: string;
  owner: string | null;
  arr: number | null;
  renewal_date: string | null;
  kind: "at_risk" | "needs_review";
  summary: string;
  confidence: number;
  cause: string | null;
  status: "pending" | "approved" | "rejected";
  citation_count: number;
  citations: string[];
  play: Play | null;
};

export type Evidence = { id: string; type: "call" | "crm" | "usage"; label: string; text: string };

export type AuditEntry = {
  actor: string;
  action: string;
  entity: string;
  entity_id: string | null;
  detail: Record<string, unknown>;
  created_at: string;
};

export type FindingDetail = Finding & { evidence: Evidence[]; audit: AuditEntry[] };

async function request<T>(path: string, tenant?: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (tenant) headers["X-Tenant-Id"] = tenant;
  const res = await fetch(API + path, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const getTenants = () => request<Tenant[]>("/api/tenants");

export const getFindings = (tenant: string) => request<Finding[]>("/api/findings", tenant);

export const getFinding = (tenant: string, id: number) =>
  request<FindingDetail>("/api/findings/" + id, tenant);

export const decide = (tenant: string, playId: number, decision: "approve" | "reject", actor: string, note?: string) =>
  request<{ play_id: number; status: string }>("/api/plays/" + playId + "/decision", tenant, {
    method: "POST",
    body: JSON.stringify({ decision, actor, note: note || null }),
  });
