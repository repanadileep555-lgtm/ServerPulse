DELETE FROM alerts WHERE host_id IS NOT NULL;
DELETE FROM alert_rules WHERE rule_type = 'machine_metric';

CREATE TABLE alert_rules_old (
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

CREATE TABLE alerts_old (
    id                 INTEGER PRIMARY KEY,
    rule_id            INTEGER NOT NULL REFERENCES alert_rules (id) ON DELETE CASCADE,
    service_id         INTEGER REFERENCES monitored_services (id) ON DELETE CASCADE,
    source_id          INTEGER REFERENCES log_sources (id) ON DELETE CASCADE,
    status             TEXT    NOT NULL DEFAULT 'open'
                       CHECK (status IN ('open', 'acknowledged', 'resolved')),
    message            TEXT    NOT NULL,
    triggered_at       TEXT    NOT NULL,
    event_window_start TEXT,
    event_window_end   TEXT,
    historical         INTEGER NOT NULL DEFAULT 0 CHECK (historical IN (0, 1)),
    acknowledged_at    TEXT,
    resolved_at        TEXT,
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

INSERT INTO alert_rules_old (id, name, rule_type, service_id, source_id, threshold_count, window_minutes,
                             enabled, created_at)
SELECT id, name, rule_type, service_id, source_id, threshold_count, window_minutes, enabled, created_at
FROM alert_rules;

INSERT INTO alerts_old (id, rule_id, service_id, source_id, status, message, triggered_at,
                        event_window_start, event_window_end, historical, acknowledged_at, resolved_at)
SELECT id, rule_id, service_id, source_id, status, message, triggered_at,
       event_window_start, event_window_end, historical, acknowledged_at, resolved_at
FROM alerts;

DROP TABLE alerts;
DROP TABLE alert_rules;
ALTER TABLE alert_rules_old RENAME TO alert_rules;
ALTER TABLE alerts_old RENAME TO alerts;

CREATE UNIQUE INDEX ux_alerts_active
    ON alerts (rule_id)
    WHERE status <> 'resolved';

CREATE UNIQUE INDEX ux_alerts_historical_window
    ON alerts (rule_id, event_window_start, event_window_end)
    WHERE historical = 1;

CREATE INDEX ix_alerts_status_time ON alerts (status, triggered_at);
