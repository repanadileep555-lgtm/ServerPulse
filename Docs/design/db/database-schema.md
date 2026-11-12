# ServerPulse SQLite Schema

SQLite database design for the FastAPI backend, aligned with the
[High-Level Design](../machine/HLD.md) and [roadmap](../../roadmap.md).
The authoritative complete DDL is [schema.sql](../../../Backend/db/schema/schema.sql);
install/upgrade databases using the migration runner, not the partial excerpt below.

Migrations `0001_initial`, `0002_users`, and `0003_monitoring` define the current
schema. Runtime support exists for users, host credentials, resource snapshots,
process history, and monitoring receipts. Log/service ingestion and alert evaluation
remain planned even though their tables exist.

Scope: Windows localhost, local WSL distributions, and external Windows/Linux
hosts. Collectors poll their own machines and push authenticated batches to the
backend. Only the backend opens this database.

Application logs are existing records from installed software, not records from
a custom/demo application or a log generator.

## Design decisions

| Topic | Decision |
| --- | --- |
| Database | SQLite file, no separate server |
| Hosts | Stable registered host IDs for localhost, WSL, and external servers |
| Collection | Local polling and authenticated batch push; no SSH/WinRM requirement |
| Checkpoints | Collector-local resume state; backend stores an acknowledged mirror only after event storage commits |
| Deduplication | `UNIQUE (source_id, source_record_id)` on `log_events` |
| Unavailable sources | `last_status = 'unavailable'` is kept separate from "no events" |
| Service state | Ordered observations and transitions; collection errors, staleness, and stopped state are separate |
| Resource/process monitoring | Migration `0003_monitoring`; per-host CPU/memory and all-visible-process snapshots |
| Runtime classification | PID + creation time identity; host threshold defaults to 3600 seconds, informational only |
| Monitoring retention | 24-hour query window, cleanup on host ingestion; receipts retained seven days |
| Timestamps | UTC ISO-8601 text; SQL defaults use milliseconds, monitoring normalization uses microseconds |
| Alerts | Service failure and N error/critical records from one source in M minutes |
| Authentication | Host collector token digests; user access/refresh JWTs backed by Argon2-hashed user accounts |
| User roles | Admin/viewer checks implemented; granular roles and JWT revocation remain future work |

## Schema

The entity-relationship diagram is in [ERD.md](ERD.md).

## Resource and process tables

Migration [0003_monitoring.up.sql](../../../Backend/db/migrations/0003_monitoring.up.sql)
is the executable extension to the base DDL below. The consolidated
[schema.sql](../../../Backend/db/schema/schema.sql) includes it for fresh databases;
use the migration runner for existing databases. Do not edit applied migrations.

| Table / column | Purpose and invariants |
| --- | --- |
| `hosts.long_running_seconds` | Integer 60-31536000, default 3600; per-host informational lifetime threshold |
| `monitoring_samples` | Host FK, UTC observed/received times, CPU 0-100, total/available/used memory, memory percentage, visible/denied/vanished counts, long-running and nullable zombie counts |
| `process_samples` | Composite PK `(sample_id, pid)`; nullable creation time, name, native state, normalized CPU, RSS, memory percentage, runtime, classifications, permission flag |
| `monitoring_receipts` | PK `(host_id, batch_id)`, payload digest, accepted time, nullable sample FK with `ON DELETE SET NULL` |

Samples own process rows with cascade delete. Identity queries join samples by
host and use PID **plus creation time**, not PID alone. Unknown fields remain NULL;
Windows zombie fields/counts are NULL/not applicable. Counts describe visible
observations, not guaranteed unrestricted process visibility.

Ingestion inserts a complete sample, processes, receipt, and heartbeat atomically.
The host comes from the credential; retries of the same ID require the same
payload digest. Latest uses observed time then ID, so delayed batches do not
replace newer snapshots. A mismatched registered platform is rejected.

History queries exclude observations older than 24 hours. On a new ingestion,
delete older samples for that host (cascading process rows) and receipts older than
seven days. A receipt can acknowledge an already-deleted sample with a NULL
sample ID. Snapshots outside the 24-hour window are rejected unless their existing
receipt establishes a committed duplicate. Offline hosts can retain a stale last
sample until new ingestion; this is intentionally visible, not current health.

This design adds no resource alert rule or automatic remediation: long-running
processes are informational. Read access is for enabled dashboard users;
registration/configuration/token rotation require an enabled administrator.

## Base host, log, service, and alert schema

The following excerpt corresponds to `0001_initial`. User tables are added by
`0002_users`, and the monitoring extension above by `0003_monitoring`. Applying
only this excerpt does not install the complete current schema.

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;

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
CREATE INDEX ix_log_events_host_time ON log_events (host_id, occurred_at);
CREATE INDEX ix_log_events_service_time ON log_events (service_id, occurred_at);

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

-- Each rule has exactly one configured target.
CREATE UNIQUE INDEX ux_alerts_active
    ON alerts (rule_id)
    WHERE status <> 'resolved';

CREATE UNIQUE INDEX ux_alerts_historical_window
    ON alerts (rule_id, event_window_start, event_window_end)
    WHERE historical = 1;

CREATE INDEX ix_alerts_status_time ON alerts (status, triggered_at);
```

## Notes

Log/source/service/alert behavior below describes the **planned** implementation
contract; the current resource collector does not execute these paths.

### Existing sources

- Windows uses existing System, Application, and Security Event Log channels.
- Linux uses existing journal entries and installed-software log files, including
  authentication files where configured. Package-manager logs are one possible
  application source; presence, parsing, and permissions must be checked first.
- `source_type = 'file'` means an existing log file, not a generated demo file.
- `selection_json` describes allowlisted unit/provider filters or a known parser.
  Configure disjoint selections when reading multiple categories from one journal.
- Source category is administrator-configured. The ingestion API validates that
  each event's category matches its source; collectors cannot invent new sources.
- Security/authentication and audit are distinct categories. Missing audit support
  in WSL is an unavailable capability, not a reason to synthesize audit events.

### Connection and ownership rules

- Enable foreign keys and the bounded busy timeout on every connection. WAL is
  configured when initializing the database; it does not remove SQLite's single-writer limit.
- The authenticated credential determines host ownership. Reject disabled hosts,
  revoked credentials, and source/service IDs not belonging to that host.
- Composite foreign keys prevent events referencing another host's source/service.
  Alert targets must additionally match their rule in backend validation.
- `name` is an administrator-assigned display label, not a network address or
  authentication identity. WSL and its parent Windows machine have separate host IDs.
- `last_heartbeat_at` is backend receipt time of a newly committed monitoring
  snapshot; 60 seconds without one means offline. It must not overwrite service
  state. `collector_status_json` is reserved for future diagnostics; the current
  collector does not populate it.
- All timestamps use the fixed UTC format above. Backend validation enforces
  formatting, timestamp quality, JSON shapes, and field lengths; SQLite TEXT alone
  does not validate these. Fallback timestamps retain the original value in
  optional native fields and must be excluded from occurrence-time burst rules.

### Delivery, checkpoints, and deduplication

- Insert records, update acknowledged progress, evaluate related alerts, and write
  the ingestion receipt in one transaction. Acknowledge only after commit.
- `response_json` stores the committed acknowledgement, including per-source
  progress and record counts. A repeated `(host_id, batch_id)` returns that outcome
  only if batch type and canonical payload digest match; otherwise reject it.
- Keep receipts through the supported retry window. Retention and collector retry
  limits must be coordinated; batches beyond that window require an explicit
  recovery decision, not an assumption that they were never committed.
- `acknowledged_checkpoint_json` mirrors committed progress; the collector's own
  durable checkpoint/spool determines resumption. Never regress it on a replay.
  Serialize delivery per source, as well as service observations.
- Checkpoint JSON contains the relevant native cursor and generation information:
  Windows channel generation + record ID; journal cursor; or file generation +
  byte offset. Detect reset, rotation, or invalid cursors and report collection gaps.
- `source_record_id` includes Windows channel generation + record ID, the journal
  cursor, or file generation + starting byte offset. For multiline records use
  the start of the complete record. An audit parser must use a stable native event
  identity that distinguishes records if it emits multiple records per audit event.
- Deduplication is per source; avoid overlapping configured sources. An existing
  event identity with different content is an integrity error, not a silent update.

### Service ordering and alerts

- Observation sequences increase persistently across collector restarts. Accept a
  service update only when its sequence exceeds `last_observation_sequence`;
  update latest state/status and insert a transition, if any, atomically.
- After collector state loss, reconcile with backend sequences before resuming.
  Resetting the counter to zero must not silently disable service updates.
- Record a transition only when normalized state changes; update freshness on
  every newer observation. Failed checks report unavailable/error and unknown,
  never a fabricated stopped state. Preserve native state for diagnosis.
- Service-failure rules apply to enabled services expected to run. Stopped/failed
  triggers an incident; confirmed running resolves it. Unknown/transitional states
  are not proof of failure or recovery.
- Copy an alert's target from its rule and do not retarget an existing rule;
  create a new rule to preserve history. The unique active-rule index prevents
  repeated polls/retries creating duplicate unresolved alerts.
- Burst rules count unique error/critical events by valid native occurrence time.
  Persist evaluated window bounds. Late events can produce resolved historical
  alerts; historical windows are deduplicated and are not current incidents.
- Acknowledgement is independent of resolution. Periodic reevaluation resolves
  current burst incidents after their rolling count drops below threshold.

### Storage lifecycle

- Disable hosts, sources, services, and rules to preserve history rather than
  deleting them. Foreign-key cascades represent an explicit destructive purge.
  A referenced service cannot be deleted while associated log records remain.
- Delete expired log records in small batches using configurable retention.
  Rule/alert and receipt retention require separate policies.
- Keep SQLite on local backend storage and use its backup API for live backups.
- Administrator accounts use `users` with Argon2 password hashes and `is_admin`.
  Login issues access/refresh JWTs; JWTs are not stored in `user_tokens`.
  That table is schema-ready for a future opaque-token feature, not an implemented
  logout/revocation store. No plaintext passwords or collector secrets belong here.
  Granular `roles` remain a future addition.
