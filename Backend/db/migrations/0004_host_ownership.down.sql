-- Restores global host-name uniqueness. Fails if two owners registered the same host name.

CREATE TABLE hosts_old (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL UNIQUE,
    platform    TEXT    NOT NULL CHECK (platform IN ('windows', 'linux')),
    deployment_type TEXT NOT NULL CHECK (deployment_type IN ('localhost', 'wsl', 'external')),
    wsl_distro  TEXT,
    enabled     INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    last_heartbeat_at TEXT,
    collector_status_json TEXT,
    long_running_seconds INTEGER NOT NULL DEFAULT 3600 CHECK (long_running_seconds BETWEEN 60 AND 31536000),
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (deployment_type <> 'wsl' OR (platform = 'linux' AND wsl_distro IS NOT NULL))
);

INSERT INTO hosts_old (id, name, platform, deployment_type, wsl_distro, enabled,
                       last_heartbeat_at, collector_status_json, long_running_seconds, created_at)
SELECT id, name, platform, deployment_type, wsl_distro, enabled,
       last_heartbeat_at, collector_status_json, long_running_seconds, created_at
FROM hosts;

DROP TABLE hosts;
ALTER TABLE hosts_old RENAME TO hosts;
