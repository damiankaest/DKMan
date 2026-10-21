BEGIN IMMEDIATE;
CREATE TABLE execution_receipts (
    operation_id TEXT PRIMARY KEY REFERENCES operations(operation_id),
    receipt TEXT NOT NULL,
    receipt_hash TEXT NOT NULL
);
PRAGMA user_version=3;
COMMIT;
