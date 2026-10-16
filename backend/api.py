import re
from typing import Literal, Optional

import psycopg
from fastapi import APIRouter, Header, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from backend import settings

router = APIRouter(prefix="/api")

USAGE_ID = re.compile(r"^usage:([^:\s]+):(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$")


def db():
    return psycopg.connect(settings.DATABASE_URL, autocommit=True)


def require_tenant(conn, tenant_id):
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-Id header is required")
    if not conn.execute("SELECT 1 FROM tenants WHERE id = %s", (tenant_id,)).fetchone():
        raise HTTPException(status_code=404, detail="unknown tenant")


def resolve_evidence(conn, tenant_id, account_id, cid):
    if cid.startswith("chunk:") and cid[6:].isdigit():
        row = conn.execute(
            "SELECT t.title, t.occurred_on, c.content FROM transcript_chunks c "
            "JOIN call_transcripts t ON t.id = c.transcript_id AND t.tenant_id = c.tenant_id "
            "WHERE c.id = %s AND c.tenant_id = %s AND c.account_id = %s",
            (int(cid[6:]), tenant_id, account_id),
        ).fetchone()
        if row:
            return {"id": cid, "type": "call", "label": "Call: %s (%s)" % (row[0], row[1]), "text": row[2]}
    elif cid.startswith("crm:") and cid[4:].isdigit():
        row = conn.execute(
            "SELECT snapshot_date, stage, close_date, champion FROM crm_snapshots "
            "WHERE id = %s AND tenant_id = %s AND account_id = %s",
            (int(cid[4:]), tenant_id, account_id),
        ).fetchone()
        if row:
            return {"id": cid, "type": "crm", "label": "CRM snapshot %s" % row[0],
                    "text": "Stage: %s | Expected close: %s | Champion: %s" % (row[1], row[2], row[3])}
    else:
        m = USAGE_ID.match(cid)
        if m and m.group(1) == account_id:
            row = conn.execute(
                "SELECT avg(active_users)::float FROM usage_events "
                "WHERE tenant_id = %s AND account_id = %s AND occurred_on BETWEEN %s AND %s "
                "AND extract(dow from occurred_on) NOT IN (0, 6)",
                (tenant_id, account_id, m.group(2), m.group(3)),
            ).fetchone()
            if row and row[0] is not None:
                return {"id": cid, "type": "usage", "label": "Usage %s to %s" % (m.group(2), m.group(3)),
                        "text": "Weekday average: %.0f active users per day" % row[0]}
    return None


FINDING_SQL = (
    "SELECT f.id, f.account_id, f.kind, f.summary, f.confidence, f.status, f.cause, f.citations, "
    "f.created_at, a.name, a.owner, a.arr, a.renewal_date, p.id, p.action, p.draft, p.status "
    "FROM findings f JOIN accounts a ON a.id = f.account_id AND a.tenant_id = f.tenant_id "
    "LEFT JOIN plays p ON p.finding_id = f.id AND p.tenant_id = f.tenant_id "
    "WHERE f.tenant_id = %s"
)


def shape(r):
    return {
        "id": r[0], "account_id": r[1], "kind": r[2], "summary": r[3], "confidence": r[4],
        "status": r[5], "cause": r[6], "citation_count": len(r[7] or []), "citations": r[7] or [],
        "created_at": r[8], "account_name": r[9], "owner": r[10],
        "arr": float(r[11]) if r[11] is not None else None, "renewal_date": r[12],
        "play": {"id": r[13], "action": r[14], "draft": r[15], "status": r[16]} if r[13] else None,
    }


@router.get("/tenants")
def tenants():
    with db() as conn:
        rows = conn.execute("SELECT id, name FROM tenants ORDER BY name").fetchall()
    return [{"id": i, "name": n} for i, n in rows]


@router.get("/findings")
def list_findings(x_tenant_id: str = Header(default="")):
    with db() as conn:
        require_tenant(conn, x_tenant_id)
        rows = conn.execute(
            FINDING_SQL + " ORDER BY (f.status = 'pending') DESC, (f.kind = 'at_risk') DESC, f.confidence DESC",
            (x_tenant_id,),
        ).fetchall()
    return [shape(r) for r in rows]


@router.get("/findings/{finding_id}")
def finding_detail(finding_id: int, x_tenant_id: str = Header(default="")):
    with db() as conn:
        require_tenant(conn, x_tenant_id)
        row = conn.execute(FINDING_SQL + " AND f.id = %s", (x_tenant_id, finding_id)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="finding not found")
        out = shape(row)
        evidence = []
        for cid in out["citations"]:
            ev = resolve_evidence(conn, x_tenant_id, out["account_id"], cid)
            if ev:
                evidence.append(ev)
        out["evidence"] = evidence
        play_id = str(out["play"]["id"]) if out["play"] else None
        audit = conn.execute(
            "SELECT actor, action, entity, entity_id, detail, created_at FROM audit_log "
            "WHERE tenant_id = %s AND ((entity = 'finding' AND entity_id = %s) OR (entity = 'play' AND entity_id = %s)) "
            "ORDER BY created_at",
            (x_tenant_id, str(finding_id), play_id),
        ).fetchall()
        out["audit"] = [{"actor": a, "action": b, "entity": c, "entity_id": d, "detail": e, "created_at": f}
                        for a, b, c, d, e, f in audit]
    return out


class Decision(BaseModel):
    decision: Literal["approve", "reject"]
    actor: str = Field(min_length=1, max_length=60)
    note: Optional[str] = Field(default=None, max_length=500)


@router.post("/plays/{play_id}/decision")
def decide(play_id: int, body: Decision, x_tenant_id: str = Header(default="")):
    new_status = "approved" if body.decision == "approve" else "rejected"
    with db() as conn:
        require_tenant(conn, x_tenant_id)
        with conn.transaction():
            row = conn.execute(
                "SELECT status, finding_id FROM plays WHERE id = %s AND tenant_id = %s FOR UPDATE",
                (play_id, x_tenant_id),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="play not found")
            if row[0] != "pending":
                raise HTTPException(status_code=409, detail="this play was already %s" % row[0])
            conn.execute("UPDATE plays SET status = %s WHERE id = %s AND tenant_id = %s",
                         (new_status, play_id, x_tenant_id))
            conn.execute("UPDATE findings SET status = %s WHERE id = %s AND tenant_id = %s",
                         (new_status, row[1], x_tenant_id))
            conn.execute(
                "INSERT INTO audit_log (tenant_id, actor, action, entity, entity_id, detail) "
                "VALUES (%s, %s, %s, 'play', %s, %s)",
                (x_tenant_id, "human:" + body.actor.strip(), "play_" + new_status, str(play_id),
                 Jsonb({"finding_id": row[1], "note": body.note})),
            )
    return {"play_id": play_id, "status": new_status}


@router.get("/audit")
def audit_log(x_tenant_id: str = Header(default="")):
    with db() as conn:
        require_tenant(conn, x_tenant_id)
        rows = conn.execute(
            "SELECT actor, action, entity, entity_id, detail, created_at FROM audit_log "
            "WHERE tenant_id = %s ORDER BY created_at DESC LIMIT 50",
            (x_tenant_id,),
        ).fetchall()
    return [{"actor": a, "action": b, "entity": c, "entity_id": d, "detail": e, "created_at": f}
            for a, b, c, d, e, f in rows]
