-- ServerPulse SQLite schema (current state).
-- Applied through migrations in Backend/db/migrations; connection PRAGMAs are set by Backend/db/migrate.py.

CREATE TABLE hosts (
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

CREATE UNIQUE INDEX ux_hosts_unowned_name ON hosts (name) WHERE owner_user_id IS NULL;
CREATE INDEX ix_hosts_owner ON hosts (owner_user_id);

CREATE TABLE collector_credentials (
    id           INTEGER PRIMARY KEY,
    host_id      INTEGER NOT NULL REFERENCES hosts (id) ON DELETE CASCADE,
    token_digest TEXT    NOT NULL UNIQUE,
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    revoked_at   TEXT
);

CREATE INDEX ix_credentials_host ON collector_credentials (host_id);

CREATE TABLE ingestion_receipts (
    id             INTEGER PRIMARY KEY,
    host_id        INTEGER NOT NULL REFERENCES hosts (id) ON DELETE CASCADE,
    batch_id       TEXT    NOT NULL,
    batch_type     TEXT    NOT NULL CHECK (batch_type IN ('logs', 'services')),
    payload_digest TEXT    NOT NULL,
    response_json  TEXT    NOT NULL,
    committed_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (host_id, batch_id)
);

CREATE TABLE log_sources (
    id                    INTEGER PRIMARY KEY,
    host_id               INTEGER NOT NULL REFERENCES hosts (id) ON DELETE CASCADE,
    source_type           TEXT    NOT NULL CHECK (source_type IN ('windows_eventlog', 'journald', 'auditd', 'file')),
    category              TEXT    NOT NULL CHECK (category IN ('system', 'application', 'security', 'audit')),
    channel               TEXT    NOT NULL,
    selection_json        TEXT    NOT NULL DEFAULT '{}',
    enabled               INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    acknowledged_checkpoint_json TEXT,
    last_status           TEXT    NOT NULL DEFAULT 'never_run'
                          CHECK (last_status IN ('never_run', 'ok', 'unavailable', 'error')),
    last_error            TEXT,
    last_attempt_at       TEXT,
    last_success_at       TEXT,
    UNIQUE (host_id, source_type, channel, category),
    UNIQUE (id, host_id)
);

CREATE TABLE log_events (
    id               INTEGER PRIMARY KEY,
    host_id          INTEGER NOT NULL REFERENCES hosts (id) ON DELETE CASCADE,
    source_id        INTEGER NOT NULL,
    service_id       INTEGER,
    source_record_id TEXT    NOT NULL,
    category         TEXT    NOT NULL CHECK (category IN ('system', 'application', 'security', 'audit')),
    occurred_at      TEXT    NOT NULL,
    collected_at     TEXT    NOT NULL,
    received_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    timestamp_quality TEXT   NOT NULL CHECK (timestamp_quality IN ('native', 'fallback')),
    severity         TEXT    NOT NULL CHECK (severity IN ('debug', 'info', 'warning', 'error', 'critical', 'unknown')),
    native_severity  TEXT,
    event_id         INTEGER,
    provider         TEXT,
    message          TEXT    NOT NULL,
    raw_json         TEXT,
    UNIQUE (source_id, source_record_id),
    FOREIGN KEY (source_id, host_id) REFERENCES log_sources (id, host_id) ON DELETE CASCADE,
    FOREIGN KEY (service_id, host_id) REFERENCES monitored_services (id, host_id)
);

CREATE INDEX ix_log_events_source_time   ON log_events (source_id, occurred_at);
CREATE INDEX ix_log_events_severity_time ON log_events (severity, occurred_at);
CREATE INDEX ix_log_events_host_time     ON log_events (host_id, occurred_at);
CREATE INDEX ix_log_events_service_time  ON log_events (service_id, occurred_at);

CREATE TABLE monitored_services (
    id              INTEGER PRIMARY KEY,
    host_id         INTEGER NOT NULL REFERENCES hosts (id) ON DELETE CASCADE,
    service_name    TEXT    NOT NULL,
    display_name    TEXT,
    enabled         INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    expected_running INTEGER NOT NULL DEFAULT 1 CHECK (expected_running IN (0, 1)),
    current_state   TEXT    NOT NULL DEFAULT 'unknown'
                    CHECK (current_state IN ('running', 'stopped', 'failed', 'paused', 'transitional', 'unknown')),
    native_state    TEXT,
    last_observation_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_observation_sequence >= 0),
    last_status     TEXT NOT NULL DEFAULT 'never_run'
                    CHECK (last_status IN ('never_run', 'ok', 'unavailable', 'error')),
    last_checked_at TEXT,
    last_error      TEXT,
    UNIQUE (host_id, service_name),
    UNIQUE (id, host_id)
);

CREATE TABLE service_state_changes (
    id             INTEGER PRIMARY KEY,
    service_id     INTEGER NOT NULL REFERENCES monitored_services (id) ON DELETE CASCADE,
    observation_sequence INTEGER NOT NULL CHECK (observation_sequence > 0),
    previous_state TEXT CHECK (previous_state IN ('running', 'stopped', 'failed', 'paused', 'transitional', 'unknown')),
    new_state      TEXT    NOT NULL CHECK (new_state IN ('running', 'stopped', 'failed', 'paused', 'transitional', 'unknown')),
    changed_at     TEXT    NOT NULL,
    error_message  TEXT,
    UNIQUE (service_id, observation_sequence),
    CHECK (previous_state IS NULL OR previous_state <> new_state)
);

CREATE INDEX ix_state_changes_service_time ON service_state_changes (service_id, changed_at);

CREATE TABLE alert_rules (
    id                INTEGER PRIMARY KEY,
    name              TEXT    NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    rule_type         TEXT    NOT NULL CHECK (rule_type IN ('service_failure', 'error_burst', 'machine_metric')),
    service_id        INTEGER REFERENCES monitored_services (id) ON DELETE CASCADE,
    source_id         INTEGER REFERENCES log_sources (id) ON DELETE CASCADE,
    host_id           INTEGER REFERENCES hosts (id) ON DELETE CASCADE,
    metric            TEXT    CHECK (metric IN ('cpu_percent', 'memory_percent', 'long_running_count', 'zombie_count',
                                                'process_cpu_percent', 'process_memory_percent', 'process_count')),
    process_name      TEXT    CHECK (process_name IS NULL OR length(process_name) BETWEEN 1 AND 256),
    threshold         REAL    CHECK (threshold >= 0),
    sustained_minutes INTEGER CHECK (sustained_minutes BETWEEN 1 AND 1440),
    threshold_count   INTEGER CHECK (threshold_count > 0),
    window_minutes    INTEGER CHECK (window_minutes > 0),
    enabled           INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
        (rule_type = 'service_failure' AND service_id IS NOT NULL
            AND source_id IS NULL AND host_id IS NULL AND metric IS NULL
            AND threshold IS NULL AND sustained_minutes IS NULL
            AND threshold_count IS NULL AND window_minutes IS NULL)
        OR
        (rule_type = 'error_burst' AND source_id IS NOT NULL
            AND service_id IS NULL AND host_id IS NULL AND metric IS NULL
            AND threshold IS NULL AND sustained_minutes IS NULL
            AND threshold_count IS NOT NULL AND window_minutes IS NOT NULL)
        OR
        (rule_type = 'machine_metric' AND host_id IS NOT NULL
            AND service_id IS NULL AND source_id IS NULL AND metric IS NOT NULL
            AND threshold IS NOT NULL AND sustained_minutes IS NOT NULL
            AND threshold_count IS NULL AND window_minutes IS NULL
            AND ((metric IN ('cpu_percent', 'memory_percent', 'long_running_count', 'zombie_count')
                    AND process_name IS NULL)
                OR (metric IN ('process_cpu_percent', 'process_memory_percent', 'process_count')
                    AND process_name IS NOT NULL)))
    )
);

CREATE TABLE alerts (
    id                 INTEGER PRIMARY KEY,
    rule_id            INTEGER NOT NULL REFERENCES alert_rules (id) ON DELETE CASCADE,
    service_id         INTEGER REFERENCES monitored_services (id) ON DELETE CASCADE,
    source_id          INTEGER REFERENCES log_sources (id) ON DELETE CASCADE,
    host_id            INTEGER REFERENCES hosts (id) ON DELETE CASCADE,
    status             TEXT    NOT NULL DEFAULT 'open'
                       CHECK (status IN ('open', 'acknowledged', 'resolved')),
    message            TEXT    NOT NULL,
    value              REAL,
    triggered_at       TEXT    NOT NULL,
    event_window_start TEXT,
    event_window_end   TEXT,
    historical         INTEGER NOT NULL DEFAULT 0 CHECK (historical IN (0, 1)),
    acknowledged_at    TEXT,
    resolved_at        TEXT,
    CHECK ((service_id IS NOT NULL) + (source_id IS NOT NULL) + (host_id IS NOT NULL) = 1),
    CHECK (host_id IS NULL OR value IS NOT NULL),
    CHECK ((event_window_start IS NULL AND event_window_end IS NULL)
        OR (event_window_start IS NOT NULL AND event_window_end IS NOT NULL
            AND event_window_start <= event_window_end)),
    CHECK ((status = 'resolved' AND resolved_at IS NOT NULL)
        OR (status <> 'resolved' AND resolved_at IS NULL)),
    CHECK (status <> 'acknowledged' OR acknowledged_at IS NOT NULL),
    CHECK (historical = 0 OR (status = 'resolved' AND event_window_start IS NOT NULL))
);

-- Owners can create several rules for the same machine and metric.
CREATE INDEX ix_alert_rules_machine ON alert_rules (host_id)
    WHERE rule_type = 'machine_metric';

-- Each rule has at most one unresolved alert.
CREATE UNIQUE INDEX ux_alerts_active
    ON alerts (rule_id)
    WHERE status <> 'resolved';

CREATE UNIQUE INDEX ux_alerts_historical_window
    ON alerts (rule_id, event_window_start, event_window_end)
    WHERE historical = 1;

CREATE INDEX ix_alerts_status_time ON alerts (status, triggered_at);
CREATE INDEX ix_alerts_host_time ON alerts (host_id, triggered_at);

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

CREATE TABLE monitoring_samples (
    id INTEGER PRIMARY KEY,
    host_id INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
    sampled_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    cpu_percent REAL NOT NULL CHECK (cpu_percent BETWEEN 0 AND 100),
    memory_total_bytes INTEGER NOT NULL CHECK (memory_total_bytes > 0),
    memory_available_bytes INTEGER NOT NULL CHECK (memory_available_bytes >= 0),
    memory_used_bytes INTEGER NOT NULL CHECK (memory_used_bytes >= 0),
    memory_percent REAL NOT NULL CHECK (memory_percent BETWEEN 0 AND 100),
    process_count INTEGER NOT NULL CHECK (process_count >= 0),
    denied_count INTEGER NOT NULL CHECK (denied_count >= 0),
    vanished_count INTEGER NOT NULL CHECK (vanished_count >= 0),
    long_running_count INTEGER NOT NULL CHECK (long_running_count >= 0),
    zombie_count INTEGER CHECK (zombie_count >= 0),
    CHECK (memory_available_bytes + memory_used_bytes = memory_total_bytes)
);

CREATE INDEX ix_monitoring_samples_host_time ON monitoring_samples(host_id, sampled_at, id);

CREATE TABLE process_samples (
    sample_id INTEGER NOT NULL REFERENCES monitoring_samples(id) ON DELETE CASCADE,
    pid INTEGER NOT NULL CHECK (pid >= 0),
    create_time TEXT,
    name TEXT,
    status TEXT,
    cpu_percent REAL CHECK (cpu_percent BETWEEN 0 AND 100),
    rss_bytes INTEGER CHECK (rss_bytes >= 0),
    memory_percent REAL CHECK (memory_percent BETWEEN 0 AND 100),
    runtime_seconds REAL CHECK (runtime_seconds >= 0),
    long_running INTEGER CHECK (long_running IN (0, 1)),
    zombie INTEGER CHECK (zombie IN (0, 1)),
    access_denied INTEGER NOT NULL CHECK (access_denied IN (0, 1)),
    PRIMARY KEY (sample_id, pid)
);

CREATE INDEX ix_process_samples_identity ON process_samples(pid, create_time, sample_id);

CREATE TABLE monitoring_receipts (
    host_id INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
    batch_id TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    sample_id INTEGER REFERENCES monitoring_samples(id) ON DELETE SET NULL,
    accepted_at TEXT NOT NULL,
    PRIMARY KEY (host_id, batch_id)
);

CREATE TABLE host_notifications (
    id                INTEGER PRIMARY KEY,
    recipient_user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    host_id           INTEGER NOT NULL REFERENCES hosts (id) ON DELETE CASCADE,
    message           TEXT    NOT NULL,
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    read_at           TEXT
);

CREATE INDEX ix_host_notifications_recipient ON host_notifications (recipient_user_id, read_at, id);

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
