-- Account Signal Engine schema (all data is synthetic)

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS tenants (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    id            TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL REFERENCES tenants(id),
    name          TEXT NOT NULL,
    segment       TEXT,
    arr           NUMERIC,
    renewal_date  DATE,
    owner         TEXT
);
CREATE INDEX IF NOT EXISTS idx_accounts_tenant ON accounts(tenant_id);

CREATE TABLE IF NOT EXISTS usage_events (
    id             BIGSERIAL PRIMARY KEY,
    tenant_id      TEXT NOT NULL REFERENCES tenants(id),
    account_id     TEXT NOT NULL REFERENCES accounts(id),
    occurred_on    DATE NOT NULL,
    active_users   INT NOT NULL,
    feature_events INT NOT NULL,
    UNIQUE (tenant_id, account_id, occurred_on)
);
CREATE INDEX IF NOT EXISTS idx_usage_tenant_account ON usage_events(tenant_id, account_id, occurred_on);

CREATE TABLE IF NOT EXISTS crm_snapshots (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL REFERENCES tenants(id),
    account_id    TEXT NOT NULL REFERENCES accounts(id),
    snapshot_date DATE NOT NULL,
    stage         TEXT NOT NULL,
    amount        NUMERIC,
    close_date    DATE,
    champion      TEXT,
    UNIQUE (tenant_id, account_id, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_crm_tenant_account ON crm_snapshots(tenant_id, account_id, snapshot_date);

CREATE TABLE IF NOT EXISTS call_transcripts (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id),
    account_id  TEXT NOT NULL REFERENCES accounts(id),
    occurred_on DATE NOT NULL,
    title       TEXT,
    transcript  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_calls_tenant_account ON call_transcripts(tenant_id, account_id, occurred_on);

CREATE TABLE IF NOT EXISTS transcript_chunks (
    id             BIGSERIAL PRIMARY KEY,
    tenant_id      TEXT NOT NULL REFERENCES tenants(id),
    account_id     TEXT NOT NULL REFERENCES accounts(id),
    transcript_id  TEXT NOT NULL REFERENCES call_transcripts(id),
    chunk_index    INT NOT NULL,
    content        TEXT NOT NULL,
    embedding      vector(384),
    UNIQUE (transcript_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_chunks_tenant_account ON transcript_chunks(tenant_id, account_id);

CREATE TABLE IF NOT EXISTS findings (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id),
    account_id  TEXT NOT NULL REFERENCES accounts(id),
    kind        TEXT NOT NULL,
    summary     TEXT NOT NULL,
    confidence  REAL NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    citations   JSONB NOT NULL DEFAULT '[]',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_findings_tenant ON findings(tenant_id, status);

CREATE TABLE IF NOT EXISTS plays (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id),
    finding_id  BIGINT NOT NULL REFERENCES findings(id),
    action      TEXT NOT NULL,
    draft       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id),
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    entity      TEXT NOT NULL,
    entity_id   TEXT,
    detail      JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_log(tenant_id, created_at);

ALTER TABLE findings ADD COLUMN IF NOT EXISTS cause TEXT;
