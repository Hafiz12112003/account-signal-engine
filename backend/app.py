import json
import secrets
from typing import Any

import redis
from fastapi import Body, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend import settings
from backend.api import router as api_router

app = FastAPI(title="Account Signal Engine")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(api_router)

bus = redis.from_url(settings.REDIS_URL, decode_responses=True)

REQUIRED = {
    "tenant": ["id", "name"],
    "account": ["id", "tenant_id", "name"],
    "usage": ["tenant_id", "account_id", "occurred_on", "active_users", "feature_events"],
    "crm": ["tenant_id", "account_id", "snapshot_date", "stage"],
    "call": ["id", "tenant_id", "account_id", "occurred_on", "transcript"],
}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhooks/{kind}")
def webhook(kind: str, body: Any = Body(...), x_webhook_secret: str = Header(default="")):
    if not secrets.compare_digest(x_webhook_secret, settings.WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="bad webhook secret")
    if kind not in REQUIRED:
        raise HTTPException(status_code=404, detail="unknown event kind: " + kind)

    items = body if isinstance(body, list) else [body]
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail="item %d is not an object" % i)
        missing = [k for k in REQUIRED[kind] if k not in item]
        if missing:
            raise HTTPException(status_code=422, detail="item %d missing fields: %s" % (i, missing))

    for item in items:
        bus.publish(settings.CHANNEL, json.dumps({"kind": kind, "data": item}))
    return {"accepted": len(items)}

