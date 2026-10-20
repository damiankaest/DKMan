CREATE TABLE notes_schema (version INTEGER PRIMARY KEY CHECK (version = 1));
CREATE TABLE notes (
    id UUID PRIMARY KEY,
    author_subject VARCHAR(255) NOT NULL,
    text VARCHAR(4000) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_notes_time ON notes (created_at, id);
INSERT INTO notes_schema (version) VALUES (1);
