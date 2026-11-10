-- ServerPulse SQLite schema (current state).
-- Applied through migrations in Backend/db/migrations; connection PRAGMAs are set by Backend/db/migrate.py.

CREATE TABLE hosts (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL UNIQUE,
    platform    TEXT    NOT NULL CHECK (platform IN ('windows', 'linux')),
    deployment_type TEXT NOT NULL CHECK (deployment_type IN ('localhost', 'wsl', 'external')),
    wsl_distro  TEXT,
    enabled     INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    last_heartbeat_at TEXT,
    collector_status_json TEXT,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (deployment_type <> 'wsl' OR (platform = 'linux' AND wsl_distro IS NOT NULL))
);

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
    id              INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL,
    rule_type       TEXT    NOT NULL CHECK (rule_type IN ('service_failure', 'error_burst')),
    service_id      INTEGER REFERENCES monitored_services (id) ON DELETE CASCADE,
    source_id       INTEGER REFERENCES log_sources (id) ON DELETE CASCADE,
    threshold_count INTEGER CHECK (threshold_count > 0),
    window_minutes  INTEGER CHECK (window_minutes > 0),
    enabled         INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
        (rule_type = 'service_failure' AND service_id IS NOT NULL
            AND source_id IS NULL AND threshold_count IS NULL AND window_minutes IS NULL)
        OR
        (rule_type = 'error_burst' AND source_id IS NOT NULL AND service_id IS NULL
            AND threshold_count IS NOT NULL AND window_minutes IS NOT NULL)
    )
);

CREATE TABLE alerts (
    id              INTEGER PRIMARY KEY,
    rule_id         INTEGER NOT NULL REFERENCES alert_rules (id) ON DELETE CASCADE,
    service_id      INTEGER REFERENCES monitored_services (id) ON DELETE CASCADE,
    source_id       INTEGER REFERENCES log_sources (id) ON DELETE CASCADE,
    status          TEXT    NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'acknowledged', 'resolved')),
    message         TEXT    NOT NULL,
    triggered_at    TEXT    NOT NULL,
    event_window_start TEXT,
    event_window_end TEXT,
    historical      INTEGER NOT NULL DEFAULT 0 CHECK (historical IN (0, 1)),
    acknowledged_at TEXT,
    resolved_at     TEXT,
    CHECK ((service_id IS NOT NULL AND source_id IS NULL)
        OR (source_id IS NOT NULL AND service_id IS NULL)),
    CHECK ((event_window_start IS NULL AND event_window_end IS NULL)
        OR (event_window_start IS NOT NULL AND event_window_end IS NOT NULL
            AND event_window_start <= event_window_end)),
    CHECK ((status = 'resolved' AND resolved_at IS NOT NULL)
        OR (status <> 'resolved' AND resolved_at IS NULL)),
    CHECK (status <> 'acknowledged' OR acknowledged_at IS NOT NULL),
    CHECK (historical = 0 OR (status = 'resolved' AND event_window_start IS NOT NULL))
);

-- Each rule has at most one unresolved alert.
CREATE UNIQUE INDEX ux_alerts_active
    ON alerts (rule_id)
    WHERE status <> 'resolved';

CREATE UNIQUE INDEX ux_alerts_historical_window
    ON alerts (rule_id, event_window_start, event_window_end)
    WHERE historical = 1;

CREATE INDEX ix_alerts_status_time ON alerts (status, triggered_at);

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
