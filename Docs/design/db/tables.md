# ServerPulse Database Tables

Explains the purpose of each table in the SQLite schema, with example data.
The DDL is in [schema.sql](../../../Backend/db/schema/schema.sql), and the
relationships are shown in [ERD.md](ERD.md).

Conventions used throughout:

- Timestamps are UTC text in ISO 8601 form, for example `2026-11-11T12:40:00.000Z`.
- Booleans are `INTEGER` with values `0` or `1`.
- Passwords use Argon2 hashes and collector tokens use digests; user JWTs are not
  stored in SQLite.
- Example values are fictional. Digests are shortened; `sha256:` is an illustrative
  label, not a literal prefix in stored collector digests.

Tables are grouped by area: hosts and collectors, resources/processes, logs,
services, alerts, and users. See the [detailed reference](table-reference.md) for
full column lists and the [roadmap](../../roadmap.md) for implementation status.

**Runtime status:** host registration/credentials, user/JWT authentication, and
resource/process snapshot ingestion/querying are implemented. Log, service,
and alert tables are schema-ready; their examples below describe planned features.
`user_tokens` is reserved, not the current login or refresh mechanism.
Examples are documentation only, not generated input for real collectors.

---

## Migration metadata

### schema_migrations

Created by the migration runner, not the consolidated application DDL.
`version` is the primary-key migration name and `applied_at` is its UTC application
time. Current versions are `0001_initial`, `0002_users`, and `0003_monitoring`.
Use the runner to apply/roll back migrations; do not edit this table manually.

## Hosts and collectors

### hosts

One row per machine that ServerPulse monitors. This is the root table for most other
host-scoped data. Deleting a host cascades to its credentials, receipts, sources,
events, services, and resource/process history.

| Column | Meaning |
| --- | --- |
| `id` | Primary key. |
| `name` | Display name for the machine, unique among the machines with the same `owner_user_id` (legacy hosts with no owner are unique among themselves). |
| `owner_user_id` | The user who registered the host; `NULL` for hosts registered before ownership existed (visible to administrators only). Deleting the user sets this to `NULL`. |
| `platform` | `windows` or `linux`. |
| `deployment_type` | `localhost` (the same Windows machine as the server), `wsl` (a WSL distro), or `external` (a remote machine). A `wsl` host must be `linux` and must have `wsl_distro` set. |
| `wsl_distro` | WSL distro name, only for `wsl` hosts. |
| `enabled` | `0` stops collection for this host. |
| `last_heartbeat_at` | Backend receipt time of the last new monitoring snapshot; offline after 60 seconds without one. |
| `collector_status_json` | Reserved diagnostic JSON; not populated by the current resource collector. |
| `long_running_seconds` | Per-host lifetime threshold, 60-31536000 seconds; default 3600, informational only. |
| `created_at` | When the host was registered. |

Example rows:

| id | name | platform | deployment_type | wsl_distro | owner_user_id | enabled | last_heartbeat_at | collector_status_json | created_at |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | WIN-DEV-01 | windows | localhost | NULL | 2 | 1 | 2026-11-11T12:40:00.000Z | `{"version":"0.1.0","uptime_s":8640}` | 2026-11-10T09:00:00.000Z |
| 2 | ubuntu-wsl | linux | wsl | Ubuntu-22.04 | 2 | 1 | 2026-11-11T12:39:30.000Z | NULL | 2026-11-10T09:05:00.000Z |
| 3 | web-prod-01 | linux | external | NULL | NULL | 0 | 2026-11-09T22:10:00.000Z | NULL | 2026-11-08T14:00:00.000Z |

Host 3 is disabled and hasn't sent a heartbeat for two days, so its data isn't refreshed.
The diagnostic JSON examples are hypothetical future values; normal current
collection leaves that column NULL.

### collector_credentials

Tokens that a collector on a specific host uses to submit data. Each collector gets its
own token, so it can write only for its own host. Only the digest is stored. Revoking a
token sets `revoked_at` and keeps the row for audit.

| Column | Meaning |
| --- | --- |
| `id` | Primary key. |
| `host_id` | The host this token belongs to. |
| `token_digest` | Unique digest of the token. The plaintext is shown once, at creation. |
| `created_at` | When the token was issued. |
| `revoked_at` | When the token was revoked. NULL means it is still valid. |

Example rows:

| id | host_id | token_digest | created_at | revoked_at |
| --- | --- | --- | --- | --- |
| 1 | 1 | `sha256:4a7e…c901` | 2026-11-10T09:00:00.000Z | NULL |
| 2 | 2 | `sha256:b13d…07ef` | 2026-11-10T09:05:00.000Z | 2026-11-10T18:00:00.000Z |
| 3 | 2 | `sha256:e082…5a1b` | 2026-11-10T18:02:00.000Z | NULL |

Host 2 was rotated: its first token was revoked and a new one was issued.

### ingestion_receipts

A record of each batch a collector submitted. It makes retries safe. If the same
`(host_id, batch_id)` arrives again, the server can return the stored response instead of
inserting the data twice. `payload_digest` detects a repeated batch ID with different content.

| Column | Meaning |
| --- | --- |
| `batch_id` | ID the collector assigned to the batch. |
| `batch_type` | `logs` or `services`. |
| `payload_digest` | Digest of the batch contents. |
| `response_json` | The response returned to the collector. |
| `committed_at` | When the batch was stored. |

Example rows:

| id | host_id | batch_id | batch_type | payload_digest | response_json | committed_at |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | `b-0001` | logs | `sha256:7f3a…2d10` | `{"accepted":120,"rejected":0}` | 2026-11-11T12:00:05.000Z |
| 2 | 1 | `b-0002` | services | `sha256:c9e1…88b4` | `{"accepted":14,"rejected":0}` | 2026-11-11T12:05:03.000Z |

---

## Resources and processes

These tables and the host threshold were added by migration `0003_monitoring`.
All times are UTC. A collector token selects the host; payloads cannot choose
another host. Snapshots and their receipt are committed atomically.

### monitoring_samples

One CPU/memory observation and process-visibility summary for a host.

| Column | Meaning |
| --- | --- |
| `id`, `host_id` | Snapshot ID and owning host FK. |
| `sampled_at`, `received_at` | Observation time and backend acceptance time; distinct for delayed delivery. |
| `cpu_percent` | Host CPU, 0-100, measured over one second. |
| `memory_total_bytes`, `memory_available_bytes`, `memory_used_bytes` | Used equals total minus available. |
| `memory_percent` | Used memory as a percentage of total. |
| `process_count` | Visible retained process rows, including partial rows. |
| `denied_count`, `vanished_count` | Permission-denied partial rows and processes that disappeared during reads. |
| `long_running_count` | Processes with known lifetime at least the host threshold. |
| `zombie_count` | Observed Linux zombies; NULL/not applicable on Windows. |

Example selected values:

| id | host_id | cpu_percent | memory_percent | process_count | denied_count | vanished_count | long_running_count | zombie_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 101 | 1 | 24.5 | 60 | 250 | 2 | 1 | 90 | NULL |
| 102 | 2 | 12 | 40 | 60 | 1 | 0 | 20 | 1 |

Queries cover the last 24 hours; older samples are physically deleted on the next
new ingestion for that host. Latest orders by observation time, then ID, so a late
arrival cannot replace a newer snapshot. Offline data stays visibly stale.

### process_samples

One process row within a snapshot. Primary key `(sample_id, pid)`; cross-snapshot
identity is host plus PID **and creation time**. PID alone is not safe.

| Column | Meaning |
| --- | --- |
| `sample_id`, `pid` | Owning snapshot FK with cascade delete, and native process ID. |
| `create_time` | Creation time; NULL if access failed. Required to query identity history. |
| `name`, `status` | Process name and native state, where readable. |
| `cpu_percent` | CPU delta normalized across logical CPUs, 0-100; NULL until measured or if unavailable. |
| `rss_bytes`, `memory_percent` | Resident memory and its share of total memory; NULL if unavailable. |
| `runtime_seconds` | Elapsed lifetime at observation time, not CPU execution time. |
| `long_running` | Threshold classification; NULL when runtime is unknown. |
| `zombie` | Linux zombie classification; NULL on Windows or when state is unknown. |
| `access_denied` | Partial read due to permissions. Unknown metrics remain NULL, not zero. |

Example selected values:

| sample_id | pid | name | status | runtime_seconds | long_running | zombie | access_denied |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 101 | 1200 | svchost.exe | running | 7200 | 1 | NULL | 0 |
| 101 | 1300 | NULL | NULL | NULL | NULL | NULL | 1 |
| 102 | 500 | existing-worker | zombie | 300 | 0 | 1 | 0 |

Shared resident pages may appear in several processes, so RSS totals need not
equal host memory usage. Long-running is informational, not an alert or a kill
instruction. No usernames, command lines, or environment variables are collected.

### monitoring_receipts

Resource/process batch deduplication, separate from planned log/service receipts.

| Column | Meaning |
| --- | --- |
| `host_id`, `batch_id` | Composite primary key; batch ID is a collector UUID. |
| `payload_digest` | Same-ID retries must match the validated payload. |
| `sample_id` | Nullable snapshot FK; deletion sets it to NULL so a committed retry can still be acknowledged. |
| `accepted_at` | Backend acceptance time; receipts retained seven days and pruned on host ingestion. |

Nonduplicate snapshots older than 24 hours are rejected. The collector persists
one pending snapshot and retries it before sampling again, rather than maintaining
an unlimited offline history. Permission errors, missing data, and retry conflicts
are surfaced explicitly.

---

## Log collection

### log_sources

A place logs are collected from, on a given host. Examples are the Windows System
event log or the journald unit for a service. The `(host_id, source_type, channel, category)`
combination is unique, so the same source isn't registered twice.

| Column | Meaning |
| --- | --- |
| `source_type` | `windows_eventlog`, `journald`, `auditd`, or `file`. |
| `category` | `system`, `application`, `security`, or `audit`. |
| `channel` | The log name, such as `System`, `Application`, `journal`, or a file path. |
| `selection_json` | Extra filter settings, such as a provider or unit, as JSON. |
| `enabled` | `0` stops collection from this source. |
| `acknowledged_checkpoint_json` | Last position the collector has confirmed, so it can resume after a restart. |
| `last_status` | `never_run`, `ok`, `unavailable`, or `error`. |
| `last_error` | Most recent error message, if any. |
| `last_attempt_at`, `last_success_at` | When collection was last tried and last succeeded. |

Example rows:

| id | host_id | source_type | category | channel | selection_json | enabled | last_status | last_error | last_success_at |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | windows_eventlog | system | System | `{"provider":"Service Control Manager"}` | 1 | ok | NULL | 2026-11-11T12:40:00.000Z |
| 2 | 1 | windows_eventlog | application | Application | `{}` | 1 | ok | NULL | 2026-11-11T12:40:00.000Z |
| 3 | 2 | journald | system | journal | `{"unit":"nginx.service"}` | 1 | error | `permission denied` | 2026-11-10T19:00:00.000Z |

### log_events

The collected log entries. Each row is one event, normalized to a common shape across
Windows and Linux. A row is unique on `(source_id, source_record_id)`, so re-collecting the
same record doesn't duplicate it. `occurred_at` is when the event happened. `collected_at`
is when the collector read it. `received_at` is when the server stored it.

| Column | Meaning |
| --- | --- |
| `source_id`, `host_id` | The source and host this event came from. |
| `service_id` | Monitored service the event relates to, if one could be matched. |
| `source_record_id` | ID from the source, such as the Windows Event Record ID or journald cursor. |
| `timestamp_quality` | `native` if the timestamp came from the log, `fallback` if the collector had to supply it. |
| `severity` | Normalized: `debug`, `info`, `warning`, `error`, `critical`, or `unknown`. |
| `native_severity` | The original level text, kept for reference. |
| `event_id` | Numeric event ID, such as a Windows Event ID. |
| `provider` | Source that wrote the event, such as a service name. |
| `message` | Event message text. |
| `raw_json` | Full original record, if kept. |

Example rows:

| id | host_id | source_id | service_id | source_record_id | category | occurred_at | timestamp_quality | severity | native_severity | event_id | provider | message |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | 1 | 1 | 48213 | system | 2026-11-11T11:58:21.000Z | native | error | Error | 7031 | Service Control Manager | The Print Spooler service terminated unexpectedly. |
| 2 | 2 | 3 | 2 | `s=8f2…;i=1a4` | system | 2026-11-11T12:10:44.000Z | native | warning | warning | NULL | nginx | upstream timed out while reading response header |
| 3 | 1 | 2 | NULL | 48214 | application | 2026-11-11T12:01:09.000Z | native | info | Information | 1000 | Application Error | Application started. |

Event 1 is linked to the monitored Print Spooler service (`service_id` 1). Event 3 has no
service link, so `service_id` is NULL.

---

## Monitored services

### monitored_services

Windows services or Linux systemd units that ServerPulse watches. `expected_running` says
whether the service is supposed to be up. A service that is expected to run but isn't
produces a state change and may trigger an alert. `(host_id, service_name)` is unique.

| Column | Meaning |
| --- | --- |
| `service_name` | The service's internal name, such as `Spooler` or `nginx.service`. |
| `display_name` | Human-readable name. |
| `enabled` | `0` stops monitoring this service. |
| `expected_running` | `1` means the service should be running. |
| `current_state` | `running`, `stopped`, `failed`, `paused`, `transitional`, or `unknown`. |
| `native_state` | The raw state text from the OS. |
| `last_observation_sequence` | Sequence number of the latest observation, used to order updates. |
| `last_status` | Result of the last check: `never_run`, `ok`, `unavailable`, or `error`. |
| `last_checked_at`, `last_error` | When the service was last checked and any error. |

Example rows:

| id | host_id | service_name | display_name | enabled | expected_running | current_state | native_state | last_observation_sequence | last_status | last_checked_at |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | Spooler | Print Spooler | 1 | 1 | failed | Stopped | 42 | ok | 2026-11-11T12:40:00.000Z |
| 2 | 2 | nginx.service | nginx | 1 | 1 | running | active (running) | 18 | ok | 2026-11-11T12:39:30.000Z |
| 3 | 2 | cron.service | cron | 1 | 1 | running | active (running) | 17 | ok | 2026-11-11T12:39:30.000Z |

### service_state_changes

The history of state transitions for each service. A row is written only when the state
actually changes, so the table shows the timeline of each service. The sequence number is
unique per service.

| Column | Meaning |
| --- | --- |
| `observation_sequence` | Sequence number of the observation that caused the change. |
| `previous_state`, `new_state` | State before and after. `previous_state` is NULL for the first observation. |
| `changed_at` | When the change was observed. |
| `error_message` | Error text reported with the change, if any. |

Example rows:

| id | service_id | observation_sequence | previous_state | new_state | changed_at | error_message |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | 1 | NULL | running | 2026-11-10T09:00:30.000Z | NULL |
| 2 | 1 | 42 | running | failed | 2026-11-11T11:58:21.000Z | Service terminated unexpectedly |
| 3 | 2 | 18 | stopped | running | 2026-11-11T07:15:02.000Z | NULL |

---

## Alerts

### alert_rules

The conditions that produce alerts. There are three types:

- `service_failure`: fires when a specific monitored service fails. It needs `service_id`
  and must not set the threshold or window fields.
- `error_burst`: fires when a log source produces `threshold_count` errors within
  `window_minutes`. It needs `source_id` and must set both threshold fields.
- `machine_metric`: fires when a machine metric stays at or above `threshold` for
  `sustained_minutes`. It needs `host_id`, `metric`, and a user-chosen `name`. Metrics are
  `cpu_percent`, `memory_percent`, `long_running_count`, `zombie_count` (Linux only),
  `process_cpu_percent`, `process_memory_percent`, and `process_count`. The three process
  metrics also need `process_name`, which matches processes case-insensitively and sums or
  counts every match in the latest sample. A machine can have several rules per metric, up
  to 50 (`MAX_ALERT_RULES_PER_HOST`). Owners create, edit, and delete rules in the Settings
  tab of the Machines page. Deleting a rule also deletes its alert history; notifications
  are kept.

A CHECK constraint enforces these combinations.

| Column | Meaning |
| --- | --- |
| `name` | Human-readable rule name, 1–80 characters. Required for every rule. |
| `rule_type` | `service_failure`, `error_burst`, or `machine_metric`. |
| `service_id` | Watched service, for `service_failure` rules. |
| `source_id` | Watched log source, for `error_burst` rules. |
| `host_id`, `metric` | Machine and metric, for `machine_metric` rules. |
| `process_name` | Process to match (1–256 characters), for process metrics only; NULL otherwise. |
| `threshold_count`, `window_minutes` | Trigger threshold and time window, for `error_burst` rules. |
| `threshold`, `sustained_minutes` | Breach value and required duration in minutes (1–1440), for `machine_metric` rules. Percent metrics are in (0, 100]. |
| `enabled` | `0` turns the rule off without deleting it. Disabling resolves any open alert. |
| `updated_at` | Last change to the rule. |

Example rows:

| id | name | rule_type | service_id | source_id | host_id | metric | threshold_count | window_minutes | threshold | sustained_minutes | enabled |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Print Spooler down | service_failure | 1 | NULL | NULL | NULL | NULL | NULL | NULL | NULL | 1 |
| 2 | System log error burst | error_burst | NULL | 1 | NULL | NULL | 10 | 5 | NULL | NULL | 1 |
| 3 | CPU | machine_metric | NULL | NULL | 1 | cpu_percent | NULL | NULL | 90 | 5 | 1 |

### alerts

Alerts raised by rules. Each row goes through a lifecycle: `open`, then `acknowledged` when
someone looks at it, then `resolved` when the condition clears. A rule can have at most one
unresolved alert at a time (`ux_alerts_active`). Historical alerts are also stored for past
windows (`historical = 1`), and each window is recorded once. Machine alerts use `open` while
the metric is breaching and `resolved` when it clears.

| Column | Meaning |
| --- | --- |
| `rule_id` | The rule that raised the alert. |
| `service_id`, `source_id`, `host_id` | The service, log source, or machine the alert is about. Exactly one is set. |
| `status` | `open`, `acknowledged`, or `resolved`. |
| `message` | Alert text shown to the user. |
| `value` | Sample value that triggered a machine alert. Required when `host_id` is set. |
| `triggered_at` | When the alert was raised. |
| `event_window_start`, `event_window_end` | Time range of the events that caused the alert, for error bursts and historical alerts. |
| `historical` | `1` if the alert was created from past data. |
| `acknowledged_at`, `resolved_at` | When the alert was acknowledged and resolved. Set only when the status requires them. |

Example rows:

| id | rule_id | service_id | source_id | host_id | status | message | value | triggered_at | event_window_start | event_window_end | historical | acknowledged_at | resolved_at |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | 1 | NULL | NULL | acknowledged | Print Spooler is failed on WIN-DEV-01 | NULL | 2026-11-11T11:58:21.000Z | NULL | NULL | 0 | 2026-11-11T12:10:00.000Z | NULL |
| 2 | 2 | NULL | 1 | NULL | resolved | 14 errors in System log within 5 minutes | NULL | 2026-11-10T16:20:00.000Z | 2026-11-10T16:15:00.000Z | 2026-11-10T16:20:00.000Z | 0 | 2026-11-10T16:25:00.000Z | 2026-11-10T16:40:00.000Z |
| 3 | 3 | NULL | NULL | 1 | open | CPU at 96.2% for 5 minutes (threshold 90%) | 96.2 | 2026-11-11T12:05:00.000Z | NULL | NULL | 0 | NULL | NULL |

---

## Users and authentication

### users

Dashboard and administrator accounts. The `is_admin` flag separates administrators, who can
change configuration, from regular users, who can only view data. There are no per-role
permissions yet. Passwords are stored as hashes only.

| Column | Meaning |
| --- | --- |
| `username` | Unique login name. |
| `password_hash` | Hash of the password. Never the plaintext. |
| `is_admin` | `1` for administrators. |
| `enabled` | `0` blocks login without deleting the account. |
| `created_at`, `last_login_at` | Account creation and most recent successful login. |

Example rows:

| id | username | password_hash | is_admin | enabled | created_at | last_login_at |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | admin | `argon2id$…` | 1 | 1 | 2026-11-10T08:00:00.000Z | 2026-11-11T12:30:00.000Z |
| 2 | viewer | `argon2id$…` | 0 | 1 | 2026-11-10T08:10:00.000Z | NULL |

### user_tokens

Reserved schema for possible opaque API tokens with `read` or `admin` capability.
Current login/refresh uses signed JWTs and does not read or populate this table.
The fields and examples describe a future flow; they do not implement current
JWT expiry tracking, logout, or revocation. Deleting a user cascades to these rows
if any exist.

| Column | Meaning |
| --- | --- |
| `user_id` | Owner of the token. |
| `token_digest` | Unique digest of the token. |
| `capability` | Intended future opaque-token permission: `read` or `admin`. The current JWT flow does not use this column. |
| `created_at`, `expires_at` | When the token was issued and when it stops working. |
| `last_used_at` | Last time the token was accepted. |
| `revoked_at` | When the token was revoked. NULL means it is still active. |

Example rows:

| id | user_id | token_digest | capability | created_at | expires_at | last_used_at | revoked_at |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | `sha256:d41c…9e02` | admin | 2026-11-11T12:30:00.000Z | 2026-11-11T13:30:00.000Z | 2026-11-11T12:45:00.000Z | NULL |
| 2 | 2 | `sha256:0f6b…73aa` | read | 2026-11-10T08:15:00.000Z | 2026-11-10T09:15:00.000Z | 2026-11-10T08:50:00.000Z | 2026-11-10T08:55:00.000Z |

Token 2 is a hypothetical revoked/expired opaque-token record. Client sign-out
currently clears browser tokens only; there is no server-side JWT logout flow.

### host_notifications

Messages telling an owner that an administrator changed one of their machines
(settings, or a collector token rotation with next steps). Deleting the recipient
or the host cascades to these rows.

| Column | Meaning |
| --- | --- |
| `recipient_user_id` | Owner who receives the message. |
| `host_id` | Machine the message is about. |
| `message` | Text describing the change and what to do next. |
| `created_at`, `read_at` | When the message was created and when the owner marked it read. NULL means unread. |

Alert rule notifications (firing and resolved) also use this table. The navbar
notification bell reads these rows.

### ssh_collectors

One row per machine that was installed or connected over SSH (migration 0006).
Deleting the host cascades to this row.

| Column | Meaning |
| --- | --- |
| `host_id` | Machine this row belongs to. Unique. |
| `address`, `port`, `username`, `auth_method` | SSH connection details. |
| `encrypted_secret` | Password or private key, encrypted with Fernet. The key lives in `Store/credential.key`. |
| `host_key` | Pinned server public key. Later connections must match it. |
| `remote_dir`, `remote_port` | Install directory on the server and the reverse-tunnel port. |
| `desired_state` | `running` or `stopped`. The backend restores running collectors at startup. |
