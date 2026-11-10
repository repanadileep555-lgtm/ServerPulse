-- Dashboard/administrator accounts and their API tokens.
-- Passwords and tokens are stored only as hashes/digests, never in plaintext.

CREATE TABLE users (
    id            INTEGER PRIMARY KEY,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0 CHECK (is_admin IN (0, 1)),
    enabled       INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_login_at TEXT
);

CREATE TABLE user_tokens (
    id           INTEGER PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_digest TEXT    NOT NULL UNIQUE,
    capability   TEXT    NOT NULL DEFAULT 'read' CHECK (capability IN ('read', 'admin')),
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    expires_at   TEXT    NOT NULL,
    last_used_at TEXT,
    revoked_at   TEXT
);

CREATE INDEX ix_user_tokens_user ON user_tokens (user_id);
