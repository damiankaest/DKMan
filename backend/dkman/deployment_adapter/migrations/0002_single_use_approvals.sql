BEGIN IMMEDIATE;
CREATE TABLE consumed_approvals (
    approval_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL UNIQUE REFERENCES operations(operation_id)
);
PRAGMA user_version=2;
COMMIT;
