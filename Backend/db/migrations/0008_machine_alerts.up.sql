-- Machine alerts reuse alert_rules and alerts. A machine_metric rule fires when a metric stays
-- at or above its threshold for sustained_minutes; its open alert has status 'open' until resolved.
-- Process metrics (process_*) apply to every process whose name matches process_name.
CREATE TABLE alert_rules_new (
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

CREATE TABLE alerts_new (
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

INSERT INTO alert_rules_new (id, name, rule_type, service_id, source_id, threshold_count, window_minutes,
                             enabled, created_at, updated_at)
SELECT id, name, rule_type, service_id, source_id, threshold_count, window_minutes,
       enabled, created_at, created_at
FROM alert_rules;

INSERT INTO alerts_new (id, rule_id, service_id, source_id, status, message, triggered_at,
                        event_window_start, event_window_end, historical, acknowledged_at, resolved_at)
SELECT id, rule_id, service_id, source_id, status, message, triggered_at,
       event_window_start, event_window_end, historical, acknowledged_at, resolved_at
FROM alerts;

DROP TABLE alerts;
DROP TABLE alert_rules;
ALTER TABLE alert_rules_new RENAME TO alert_rules;
ALTER TABLE alerts_new RENAME TO alerts;

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
