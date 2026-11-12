# ServerPulse Table Reference

Describes every table in the ServerPulse SQLite database (`Store/serverpulse.db`),
its purpose, and example data. The authoritative DDL is
[schema.sql](../../../Backend/db/schema/schema.sql); the design rationale is in
[database-schema.md](database-schema.md) and the relationships are in [ERD.md](ERD.md).

All example rows are **illustrative** and do not describe the contents of the
live database. Timestamps are UTC ISO 8601 text; SQL defaults use milliseconds and
monitoring fields normalize to microseconds. Passwords and raw tokens are never
stored in plaintext; examples show truncated hashes/digests. The illustrative
`sha256:` prefix is not part of the stored collector digest.

Current runtime support: users/JWTs, host registration and credentials, resource
and process snapshots, and monitoring receipts. Log/service/alert tables are
schema-ready only; their example rows and workflows below are **planned** behavior,
not proof that those collectors or APIs exist. `user_tokens` is reserved and is
not used for JWT login/refresh. See the [roadmap](../../roadmap.md).

## Table overview

| Table | Group | Purpose |
| --- | --- | --- |
| `schema_migrations` | Migration | Records which migrations have been applied |
| `hosts` | Inventory | Machines monitored by ServerPulse |
| `collector_credentials` | Inventory | Hashed tokens that let a collector push data for a host |
| `ingestion_receipts` | Ingestion | Record of each accepted collector batch, for idempotent retries |
| `monitoring_samples` | Monitoring | Implemented CPU/memory snapshots and visibility counts |
| `process_samples` | Monitoring | Implemented process observations owned by a snapshot |
| `monitoring_receipts` | Monitoring | Implemented monitoring batch deduplication |
| `log_sources` | Logs | Log channels or files configured to collect from a host |
| `log_events` | Logs | Individual collected log records |
| `monitored_services` | Services | Services (for example, Windows services or systemd units) on a host |
| `service_state_changes` | Services | History of service state transitions |
| `alert_rules` | Alerting | Conditions that raise alerts |
| `alerts` | Alerting | Alerts raised by rules |
| `users` | Auth | Dashboard and administrator accounts |
| `user_tokens` | Auth | Reserved opaque-token schema; not the current JWT flow |

Foreign keys cascade on delete from `hosts` down through their sources, services,
events, credentials, and monitoring data. Deleting a monitoring sample cascades to
its process rows and sets receipt `sample_id` to NULL. Disabling rows is preferred
over deleting them so history is kept.

---

## `schema_migrations`

**Purpose.** Tracks applied schema migrations. Created by the migration runner
([migrate.py](../../../Backend/db/migrate.py)), not by `schema.sql`. The runner uses it to
skip migrations that have already run and to roll back the latest one.

**Columns.** `version` (migration name, primary key), `applied_at` (UTC timestamp).

**Example data (illustrative).**

| version | applied_at |
| --- | --- |
| `0001_initial` | `2026-01-15T10:00:00.000Z` |
| `0002_users` | `2026-01-16T10:00:00.000Z` |
| `0003_monitoring` | `2026-11-11T13:00:00.000Z` |

---

## `hosts`

**Purpose.** One row per machine ServerPulse monitors. A WSL distribution is a
separate host from the Windows machine that runs it. `deployment_type` is
`localhost` (the backend's own Windows machine), `wsl` (a distribution on a
Windows machine), or `external` (a remote server that pushes data to the backend).
A WSL row must have `platform = 'linux'` and a non-null `wsl_distro`.

**Columns.** `id`, `name` (unique display label, not a network address),
`platform` (`windows` / `linux`), `deployment_type`, `wsl_distro`, `enabled`,
`last_heartbeat_at` (backend receipt time of a new monitoring sample),
`collector_status_json` (reserved for diagnostics), `created_at`,
`long_running_seconds` (60-31536000, default 3600; informational classification).

The current collector does not populate `collector_status_json`; the illustrative
values below describe a future diagnostic capability. Connectivity is computed
as never-seen, online, offline (after 60 seconds), or disabled, not stored as a column.

**Example data.**

| id | name | platform | deployment_type | wsl_distro | enabled | last_heartbeat_at | collector_status_json |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `windows-local` | `windows` | `localhost` | NULL | 1 | `2026-01-16T17:55:00.000Z` | `{"version":"0.1.0","spool_pressure":"low"}` |
| 2 | `wsl-ubuntu` | `linux` | `wsl` | `Ubuntu-22.04` | 1 | `2026-01-16T17:55:02.000Z` | `{"version":"0.1.0"}` |
| 3 | `linux-node-01` | `linux` | `external` | NULL | 0 | NULL | NULL |

Host 3 is disabled, so its collector's batches are rejected.

---

## `collector_credentials`

**Purpose.** Authenticates collectors. Each row stores a SHA-256 digest of a
per-host collector token. The raw token is shown once at creation and never stored.
Revoking sets `revoked_at`. The authenticated credential determines which host a
batch belongs to.

**Columns.** `id`, `host_id` (FK → `hosts`), `token_digest` (unique),
`created_at`, `revoked_at`.

**Example data.**

| id | host_id | token_digest | created_at | revoked_at |
| --- | --- | --- | --- | --- |
| 1 | 1 | `sha256:9f2c...e41a` | `2026-11-10T11:52:10.000Z` | NULL |
| 2 | 2 | `sha256:b7d0...03c9` | `2026-11-10T11:53:44.000Z` | `2026-11-10T16:02:11.000Z` |

Credential 2 has been revoked, so the WSL collector must be re-enrolled.

---

## `monitoring_samples`

**Purpose.** One committed resource snapshot for a registered host. Added in
`0003_monitoring`. Host identity is derived from the collector token. Latest
queries order by observation time then ID, not arrival time.

**Columns.** `id`, `host_id` (FK), `sampled_at`, `received_at`, `cpu_percent`,
`memory_total_bytes`, `memory_available_bytes`, `memory_used_bytes`,
`memory_percent`, `process_count`, `denied_count`, `vanished_count`,
`long_running_count`, `zombie_count` (NULL on Windows).

CPU and memory percentages are 0-100. Used memory is total minus available.
`process_count` counts retained visible rows, including partial denied rows;
vanished processes are counted separately and omitted from that snapshot.
Linux zombie count covers observed states only, not guaranteed unrestricted visibility.

**Example data (selected columns, illustrative).**

| id | host_id | sampled_at | cpu_percent | memory_percent | process_count | denied_count | vanished_count | long_running_count | zombie_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 101 | 1 | `2026-11-11T12:40:00.000000Z` | 24.5 | 60 | 250 | 2 | 1 | 90 | NULL |
| 102 | 2 | `2026-11-11T12:40:02.000000Z` | 12 | 40 | 60 | 1 | 0 | 20 | 1 |

History queries cover 24 hours. Physical pruning occurs on the next new ingestion
for that host, not on a background timer; an offline host can retain stale last data.

---

## `process_samples`

**Purpose.** Process observations owned by a resource snapshot. Composite primary
key `(sample_id, pid)` allows one row per PID within a snapshot. History identity
is host plus PID **and creation time**, because operating systems recycle PIDs.

**Columns.** `sample_id` (FK with cascade delete), `pid`, `create_time` (nullable),
`name`, `status`, `cpu_percent`, `rss_bytes`, `memory_percent`, `runtime_seconds`,
`long_running`, `zombie`, `access_denied`.

Optional metrics/classifications stay NULL when unavailable. The first CPU
observation is unknown; later CPU deltas are normalized across logical CPUs.
Long-running is lifetime at least the host threshold, not a hung-process alert.
Windows zombie values are always NULL/not applicable. No command lines or
environment variables are collected.

**Example data (selected columns, illustrative).**

| sample_id | pid | create_time | name | status | cpu_percent | runtime_seconds | long_running | zombie | access_denied |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 101 | 1200 | `2026-11-11T10:40:00.000000Z` | `svchost.exe` | `running` | 0.5 | 7200 | 1 | NULL | 0 |
| 101 | 1300 | NULL | NULL | NULL | NULL | NULL | NULL | NULL | 1 |
| 102 | 500 | `2026-11-11T12:35:02.000000Z` | `existing-worker` | `zombie` | NULL | 300 | 0 | 1 | 0 |

Rows illustrate the schema only; they do not instruct a collector to fabricate processes.

---

## `monitoring_receipts`

**Purpose.** Idempotent resource/process ingestion, separate from the planned
log/service `ingestion_receipts` flow. Composite primary key `(host_id, batch_id)`.

**Columns.** `host_id` (FK), `batch_id` (collector UUID), `payload_digest`,
`sample_id` (nullable FK), `accepted_at`. A same-ID retry requires the same
validated payload digest; conflicting content is rejected.

**Example data (illustrative).**

| host_id | batch_id | payload_digest | sample_id | accepted_at |
| --- | --- | --- | --- | --- |
| 1 | `41b39b31-33ee-40f3-af9b-0b248e2b3c05` | `41ce...8a07` | 101 | `2026-11-11T12:40:03.000000Z` |
| 2 | `65b4309d-1514-451b-a74c-87ef43b3a072` | `c310...5e2b` | NULL | `2026-11-10T12:40:03.000000Z` |

A NULL sample ID can acknowledge a committed batch whose sample expired.
Receipts are retained seven days and pruned on host ingestion. Nonduplicate
snapshots older than 24 hours are rejected; the collector must retain and visibly
report a pending batch rather than silently dropping it.

---

## `ingestion_receipts`

**Purpose.** Makes collector uploads idempotent. After a batch of logs or service
observations is committed, the backend stores a receipt keyed by `(host_id, batch_id)`.
If a collector retries the same batch, the backend returns the stored response
instead of inserting duplicates. A retry with the same `batch_id` but a different
`payload_digest` is rejected.

**Columns.** `id`, `host_id` (FK), `batch_id`, `batch_type` (`logs` / `services`),
`payload_digest`, `response_json` (the committed acknowledgement), `committed_at`.

**Example data.**

| id | host_id | batch_id | batch_type | payload_digest | response_json | committed_at |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | `b-7f3a0c12` | `logs` | `sha256:41ce...8a07` | `{"accepted":42,"duplicates":0,"progress":{"1":{"generation":3,"record_id":18422}}}` | `2026-11-10T12:05:31.118Z` |
| 2 | 1 | `b-7f3a0c13` | `services` | `sha256:c310...5e2b` | `{"accepted":12,"ignored_stale":0}` | `2026-11-10T12:06:01.902Z` |

---

## `log_sources`

**Purpose.** Each row is one place ServerPulse reads logs from, scoped to a host.
Sources are configured by an administrator. A collector cannot create new sources.
It stores the acknowledged checkpoint, so the backend knows how far collection has
progressed. `source_type` is `windows_eventlog`, `journald`, `auditd`, or `file`.
The `(host_id, source_type, channel, category)` combination is unique.

**Columns.** `id`, `host_id` (FK), `source_type`, `category`
(`system` / `application` / `security` / `audit`), `channel`, `selection_json`
(provider, unit, or parser filters), `enabled`, `acknowledged_checkpoint_json`,
`last_status` (`never_run` / `ok` / `unavailable` / `error`), `last_error`,
`last_attempt_at`, `last_success_at`.

**Example data.**

| id | host_id | source_type | category | channel | selection_json | enabled | acknowledged_checkpoint_json | last_status | last_success_at |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | `windows_eventlog` | `system` | `System` | `{}` | 1 | `{"generation":3,"record_id":18422}` | `ok` | `2026-11-10T12:05:31.118Z` |
| 2 | 1 | `windows_eventlog` | `application` | `Application` | `{}` | 1 | `{"generation":1,"record_id":9051}` | `ok` | `2026-11-10T12:05:31.118Z` |
| 3 | 1 | `windows_eventlog` | `security` | `Security` | `{}` | 0 | NULL | `unavailable` | NULL |
| 4 | 2 | `journald` | `system` | `journal` | `{"units":["ssh.service"]}` | 1 | `{"cursor":"s=8d1f...;i=2a4c"}` | `ok` | `2026-11-10T12:04:48.410Z` |

Source 3 shows `unavailable`, meaning the Security log could not be read (for
example, insufficient privileges). That is different from "no events."

---

## `log_events`

**Purpose.** Stores collected log records. Each row belongs to a host and a source,
and may be linked to a service. Deduplication is enforced by
`UNIQUE (source_id, source_record_id)`, so the same record is never stored twice.
`source_record_id` is built from the native position: `generation:record_id` for
Windows, the journal cursor for journald, or file generation plus byte offset.
Records with `timestamp_quality = 'fallback'` are excluded from burst-alert timing.

**Columns.** `id`, `host_id`, `source_id`, `service_id` (nullable),
`source_record_id`, `category`, `occurred_at`, `collected_at`, `received_at`,
`timestamp_quality` (`native` / `fallback`), `severity`
(`debug` / `info` / `warning` / `error` / `critical` / `unknown`), `native_severity`,
`event_id`, `provider`, `message`, `raw_json`.

**Example data.**

| id | host_id | source_id | service_id | source_record_id | category | occurred_at | timestamp_quality | severity | native_severity | event_id | provider | message |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | 1 | 1 | `3:18422` | `system` | `2026-11-10T09:14:02.000Z` | `native` | `error` | `Error` | 7031 | `Service Control Manager` | `The Print Spooler service terminated unexpectedly.` |
| 2 | 1 | 1 | NULL | `3:18423` | `system` | `2026-11-10T09:14:05.000Z` | `native` | `info` | `Information` | 7036 | `Service Control Manager` | `The Windows Update service entered the running state.` |
| 3 | 2 | 4 | NULL | `s=8d1f...;i=2a4d` | `system` | `2026-11-10T10:02:17.000Z` | `native` | `warning` | `4` | NULL | `sshd` | `Failed password for invalid user test from 10.0.0.23` |

`raw_json` holds the original record for diagnosis; it is omitted here for brevity.

---

## `monitored_services`

**Purpose.** Services ServerPulse watches on each host, such as the Windows Print
Spooler or a systemd unit. `expected_running` controls whether a stopped state
should raise an alert. `current_state` is the latest normalized state, and
`native_state` keeps the raw platform value. `last_observation_sequence` makes
updates ordered, so an older observation cannot overwrite a newer one.

**Columns.** `id`, `host_id` (FK), `service_name` (unique per host), `display_name`,
`enabled`, `expected_running`, `current_state`
(`running` / `stopped` / `failed` / `paused` / `transitional` / `unknown`),
`native_state`, `last_observation_sequence`, `last_status`, `last_checked_at`,
`last_error`.

**Example data.**

| id | host_id | service_name | display_name | enabled | expected_running | current_state | native_state | last_observation_sequence | last_status | last_checked_at |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | `Spooler` | `Print Spooler` | 1 | 1 | `failed` | `SERVICE_STOPPED` | 12 | `ok` | `2026-11-10T09:15:00.000Z` |
| 2 | 1 | `wuauserv` | `Windows Update` | 1 | 1 | `running` | `SERVICE_RUNNING` | 40 | `ok` | `2026-11-10T17:50:00.000Z` |
| 3 | 2 | `ssh.service` | `OpenBSD Secure Shell server` | 1 | 1 | `running` | `active` | 18 | `ok` | `2026-11-10T17:50:03.000Z` |

---

## `service_state_changes`

**Purpose.** Append-only history of service transitions. A row is written only when
the normalized state actually changes. A failed check is recorded as `unknown` or
`error`, never as a fabricated `stopped`. `UNIQUE (service_id, observation_sequence)`
prevents duplicate transitions.

**Columns.** `id`, `service_id` (FK), `observation_sequence`, `previous_state`
(NULL for the first observation), `new_state`, `changed_at`, `error_message`.

**Example data.**

| id | service_id | observation_sequence | previous_state | new_state | changed_at | error_message |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | 9 | `running` | `stopped` | `2026-11-10T09:14:02.000Z` | NULL |
| 2 | 1 | 11 | `stopped` | `failed` | `2026-11-10T09:14:40.000Z` | `Unexpected termination (exit code 1067)` |
| 3 | 2 | 38 | `transitional` | `running` | `2026-11-10T17:12:08.000Z` | NULL |

---

## `alert_rules`

**Purpose.** Defines what triggers an alert. There are three types:
`service_failure` targets one service (`service_id` set), `error_burst` counts
error or critical events from one source within a time window
(`source_id`, `threshold_count`, `window_minutes` set), and `machine_metric` fires when
a machine metric (`host_id`, `metric`) stays at or above `threshold` for
`sustained_minutes`. Machine rules are user-named and there can be several per host and
metric, up to 50 per host. Process metrics also store `process_name`. A CHECK constraint
enforces that each type has exactly the right target fields.

**Columns.** `id`, `name`, `rule_type` (`service_failure` / `error_burst` / `machine_metric`),
`service_id`, `source_id`, `host_id`, `metric`, `process_name`, `threshold_count`,
`window_minutes`, `threshold`, `sustained_minutes`, `enabled`, `created_at`, `updated_at`.

**Example data.**

| id | name | rule_type | service_id | source_id | host_id | metric | threshold_count | window_minutes | threshold | sustained_minutes | enabled | created_at |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `Print Spooler down` | `service_failure` | 1 | NULL | NULL | NULL | NULL | NULL | NULL | NULL | 1 | `2026-11-10T11:55:00.000Z` |
| 2 | `System error burst` | `error_burst` | NULL | 1 | NULL | NULL | 5 | 10 | NULL | NULL | 1 | `2026-11-10T11:58:00.000Z` |
| 3 | `CPU` | `machine_metric` | NULL | NULL | 1 | `cpu_percent` | NULL | NULL | 90 | 5 | 1 | `2026-11-11T11:00:00.000Z` |

---

## `alerts`

**Purpose.** An alert instance raised by a rule. A partial unique index allows only
one unresolved alert per rule, so repeated evaluations do not create duplicates.
Historical alerts (`historical = 1`) record burst windows found in late-arriving
events. They are resolved on creation and deduplicated by their window. Machine alerts
are `open` while the metric is breaching and `resolved` when it clears. Each one
carries the triggering `value` and a `host_id`.

**Columns.** `id`, `rule_id` (FK), `service_id`, `source_id`, `host_id`, `status`
(`open` / `acknowledged` / `resolved`), `message`, `value`, `triggered_at`,
`event_window_start`, `event_window_end`, `historical`, `acknowledged_at`,
`resolved_at`.

**Example data.**

| id | rule_id | service_id | source_id | host_id | status | message | value | triggered_at | event_window_start | event_window_end | historical | acknowledged_at | resolved_at |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | 1 | NULL | NULL | `acknowledged` | `Print Spooler is failed but expected running` | NULL | `2026-11-10T09:14:40.000Z` | NULL | NULL | 0 | `2026-11-10T09:30:12.000Z` | NULL |
| 2 | 2 | NULL | 1 | NULL | `resolved` | `7 error events in 10 minutes` | NULL | `2026-11-10T08:40:00.000Z` | `2026-11-10T08:30:00.000Z` | `2026-11-10T08:40:00.000Z` | 1 | NULL | `2026-11-10T08:41:00.000Z` |
| 3 | 3 | NULL | NULL | 1 | `open` | `CPU at 96.2% for 5 minutes (threshold 90%)` | 96.2 | `2026-11-11T12:05:00.000Z` | NULL | NULL | 0 | NULL | NULL |

Alert 1 is acknowledged but still unresolved, so it remains the one active alert for
rule 1. Alert 2 is a historical burst window that was resolved when it was recorded.
Alert 3 is a machine alert that is still breaching.

---

## `users`

**Purpose.** Dashboard and administrator accounts. Passwords are stored only as
Argon2id hashes. `is_admin` grants administrative access, and `enabled` blocks
sign-in without deleting the account. Added in migration `0002_users`.

**Columns.** `id`, `username` (unique), `password_hash`, `is_admin`, `enabled`,
`created_at`, `last_login_at`.

**Example data (illustrative; hashes omitted).**

| id | username | password_hash | is_admin | enabled | created_at | last_login_at |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `admin` | `$argon2id$v=...` (omitted) | 1 | 1 | `2026-01-15T10:05:00.000Z` | `2026-01-16T09:30:00.000Z` |
| 2 | `analyst` | `$argon2id$v=...` (omitted) | 0 | 1 | `2026-01-15T10:10:00.000Z` | NULL |

---

## `user_tokens`

**Purpose.** Reserved schema for a possible opaque API-token feature. Current login
and refresh issue signed JWTs and do not insert/query this table. Expiry/revocation
columns here do not revoke issued JWTs or implement backend logout.
In a future flow, only digests would be stored, `capability` would be `read` or
`admin`, and deleting a user would remove their token rows.

**Columns.** `id`, `user_id` (FK → `users`), `token_digest` (unique), `capability`
(`read` / `admin`), `created_at`, `expires_at`, `last_used_at`, `revoked_at`.

**Example data (illustrative).**

| id | user_id | token_digest | capability | created_at | expires_at | last_used_at | revoked_at |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2 | `sha256:e03b...71fd` | `read` | `2026-01-15T10:10:30.000Z` | `2026-01-16T10:10:30.000Z` | `2026-01-15T10:52:00.000Z` | NULL |
| 2 | 1 | `sha256:5ac8...d924` | `admin` | `2026-01-15T10:30:00.000Z` | `2026-01-15T11:30:00.000Z` | `2026-01-15T10:31:10.000Z` | `2026-01-15T10:45:00.000Z` |

Token 2 illustrates a future revoked/expired opaque-token record, not current
session behavior. Client sign-out clears browser tokens; it does not write here.
