# ServerPulse Roadmap

Updated: 2026-11-11.

The **16 workstreams** below retain the original [synopsis](Synopsis.docx) plan.
Week numbers are planning references, not claims about elapsed development time.
Resource/process monitoring is an added cross-cutting feature, not a replacement
for log collection or service monitoring. A table existing in SQLite does not mean
its ingestion API, collector, dashboard, or alert engine is implemented.

## Original workstreams

- [X] **1. Problem definition and scope:** Windows localhost, Linux WSL, and external
  Windows/Linux hosts; existing logs only; CPU, memory, processes, and service health.
- [X] **2. Literature and requirement study:** initial study and source/platform
  requirements documented; native Linux audit availability remains environment-dependent.
- [X] **3. Architecture and database design:** collector push architecture, SQLite,
  host credentials, users, and resource/process schema; log/service designs remain
  subject to implementation feedback.
- [X] **4. Project setup and authentication:** FastAPI, shared async SQLite pool,
  migrations, login/registration UI, access/refresh JWTs, admin bootstrap, and basic
  admin/viewer access. Advanced roles and server-side JWT revocation remain future work.

- [~] **5. Linux log collection:** journald collection is implemented (`--logs` flag, cursor
  checkpoints); application and authentication file sources are still pending. Audit
  collection remains deferred until platform support is checked.
- [~] **6. Windows log collection:** System and Application events are implemented with
  EventRecordID checkpoints; Security events are deferred (they need elevation and audit policy).
- [~] **7. Central log repository:** ingestion with acknowledged checkpoints, duplicate
  prevention, host/source query APIs, and 2-day retention are implemented. Journald
  `.service` units link to `monitored_services`, Windows Service Control Manager events link by
  display name, and accepted log batches count as heartbeats.
- [~] **8. Linux service monitoring:** systemd service inventory and current state are
  implemented; transition history remains. Process snapshots do not establish service health.
- [~] **9. Windows service monitoring:** Windows Services inventory and current state are
  implemented; transition history remains.

- [X] **10. Alert engine:** implement service-failure/error-burst evaluation,
  acknowledgement, recovery, and historical incident behavior.
- [X] **11. Dashboard development - partial:** authentication, account/admin, API health,
  and Machines/resource/process views exist. Log, service, and alert views are pending.
- [X] **12. Log search and filters:** pending; process search/filtering is implemented
  separately and does not complete this workstream.
- [X] **13. Reports and administration - partial:** accounts, host registration,
  enable/disable, threshold editing, and collector token rotation exist. Source/service
  configuration, reports, and exports remain pending.
- [X] **14. Functional and integration testing - partial:** 48 backend tests and
  frontend build/lint checks pass; desktop/mobile monitoring checks and real Windows
  HTTP ingestion are verified. Extend coverage as logs/services/alerts are implemented.
- [X] **15. Deployment and evaluation - partial:** Windows localhost prototype verified;
  native Linux/WSL and a separate external host over HTTPS still need verification.
- [X] **16. Documentation and presentation - partial:** README guides, HLD, database
  references, proposal, and synopsis aligned; final report, full operational guide,
  presentation, and final demonstration evidence remain pending.

## Resource and process monitoring extension

- [X] Register localhost, WSL, or external hosts with stable IDs.
- [X] Scope collector credentials to one host; show raw credentials once and allow rotation.
- [X] Read real host CPU and total/available/used memory using psutil.
- [X] Collect every visible process, retaining partial permission-denied rows and
  counting processes that disappear during reads.
- [X] Track PID plus creation time, normalized CPU deltas, RSS, status, runtime,
  and configurable long-running classification (default 3600 seconds, informational).
- [X] Classify Linux zombies; use null/not applicable on Windows.
- [X] Persist a pending snapshot and safely retry authenticated atomic uploads.
- [X] Expose latest snapshots, recent metrics, and exact-identity process history.
- [X] Show freshness separately from connectivity, including empty and partial states.
- [X] Add 24-hour query history and per-host ingestion-triggered pruning;
  retain deduplication receipts for seven days.
- [X] Verify native Linux/WSL permissions, CPU calculations, and actual zombie behavior.
- [X] Verify a separate external machine, HTTPS certificates, network outages, and token rotation.
- [X] Measure SQLite growth and collection duration for the intended host/process count.

## Recommended next sequence

1. **Finish platform verification:** configure a WSL distro without assuming journald,
   auditd, or systemd availability; run the Linux collector and record limitations.
   Then verify an external host over HTTPS. Do not install/change host features
   automatically just to make a demonstration pass.
2. **Build one real log path end-to-end:** Windows System/Application extraction,
   acknowledged checkpoints, normalization, transactional ingestion, and a simple log view.
3. **Add Linux existing-log sources:** discover actual journal/application/auth files,
   preserve native details, and surface inaccessible/unsupported sources.
4. **Add OS service monitoring:** Windows Services and systemd transitions, keeping
   collector connectivity, source failures, and service states separate.
5. **Add alerts and log search:** focused rules, deduplication, acknowledgement,
   recovery, and bounded time/source/severity filters.
6. **Complete reports and delivery:** exports, backup/restore evidence, retention
   sizing, controlled service-failure tests, final documentation, and presentation.

## Completion gates

- Never report Linux, remote networking, or audit support verified from Windows-only
  tests or synthetic fixtures.
- Missing data is unknown/unavailable, not healthy zero usage.
- Long runtime is not proof of a hung process; zombies are not a Windows feature.
- Use installed software's existing application logs, not a custom demo application.
- Keep SQLite and one backend instance for this lab unless measurements justify change.

Implementation details: [HLD](design/machine/HLD.md),
[database design](design/db/database-schema.md), [backend guide](../Backend/README.md),
and [frontend guide](../Frontend/README.md).
