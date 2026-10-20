BEGIN IMMEDIATE;
CREATE TABLE operations (
    operation_id TEXT PRIMARY KEY,
    installation_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    command TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('running','succeeded','failed','reconciliation_required')),
    result TEXT NOT NULL
);
CREATE INDEX ix_operations_installation ON operations(installation_id, state);
CREATE TABLE resources (
    installation_id TEXT PRIMARY KEY,
    plan TEXT NOT NULL,
    blocked_by TEXT REFERENCES operations(operation_id)
);
PRAGMA user_version=1;
COMMIT;
