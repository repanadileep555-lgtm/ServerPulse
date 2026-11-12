-- Host ownership: any enabled user can register a machine they own.
-- Names are unique per owner. Hosts registered before this migration have no owner and stay
-- visible to administrators only; their names remain unique through a partial index.
-- Rebuilt because SQLite cannot drop the inline UNIQUE(name) constraint.

CREATE TABLE hosts_new (
    id          INTEGER PRIMARY KEY,
    owner_user_id INTEGER REFERENCES users (id) ON DELETE SET NULL,
    name        TEXT    NOT NULL,
    platform    TEXT    NOT NULL CHECK (platform IN ('windows', 'linux')),
    deployment_type TEXT NOT NULL CHECK (deployment_type IN ('localhost', 'wsl', 'external')),
    wsl_distro  TEXT,
    enabled     INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    last_heartbeat_at TEXT,
    collector_status_json TEXT,
    long_running_seconds INTEGER NOT NULL DEFAULT 3600 CHECK (long_running_seconds BETWEEN 60 AND 31536000),
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (deployment_type <> 'wsl' OR (platform = 'linux' AND wsl_distro IS NOT NULL)),
    UNIQUE (owner_user_id, name)
);

INSERT INTO hosts_new (id, owner_user_id, name, platform, deployment_type, wsl_distro, enabled,
                       last_heartbeat_at, collector_status_json, long_running_seconds, created_at)
SELECT id, NULL, name, platform, deployment_type, wsl_distro, enabled,
       last_heartbeat_at, collector_status_json, long_running_seconds, created_at
FROM hosts;

DROP TABLE hosts;
ALTER TABLE hosts_new RENAME TO hosts;

CREATE UNIQUE INDEX ux_hosts_unowned_name ON hosts (name) WHERE owner_user_id IS NULL;
CREATE INDEX ix_hosts_owner ON hosts (owner_user_id);
