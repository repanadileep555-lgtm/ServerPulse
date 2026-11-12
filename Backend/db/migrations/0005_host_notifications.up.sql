-- Notifies a machine's owner when an administrator changes its settings or rotates its collector token.

CREATE TABLE host_notifications (
    id                INTEGER PRIMARY KEY,
    recipient_user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    host_id           INTEGER NOT NULL REFERENCES hosts (id) ON DELETE CASCADE,
    message           TEXT    NOT NULL,
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    read_at           TEXT
);

CREATE INDEX ix_host_notifications_recipient ON host_notifications (recipient_user_id, read_at, id);
