-- SSH access to external machines whose collector the server installs and starts.

CREATE TABLE ssh_collectors (
    host_id          INTEGER PRIMARY KEY REFERENCES hosts (id) ON DELETE CASCADE,
    address          TEXT    NOT NULL,
    port             INTEGER NOT NULL CHECK (port BETWEEN 1 AND 65535),
    username         TEXT    NOT NULL,
    auth_method      TEXT    NOT NULL CHECK (auth_method IN ('password', 'private_key')),
    encrypted_secret TEXT    NOT NULL,
    host_key         TEXT    NOT NULL,
    remote_dir       TEXT    NOT NULL,
    remote_port      INTEGER NOT NULL CHECK (remote_port BETWEEN 1024 AND 65535),
    desired_state    TEXT    NOT NULL CHECK (desired_state IN ('running', 'stopped')),
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
