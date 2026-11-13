# ServerPulse

<img src="Frontend/public/logo.svg" alt="Server Pulse logo" width="120">

Centralized Windows/Linux monitoring for a college project, using React,
FastAPI, and SQLite. Start with Windows localhost and a Linux WSL distribution;
the same collector also supports registered external hosts over HTTPS.

## Current functionality

- Login, registration, JWT refresh, administrator accounts, and an account directory.
- Host registration, host-scoped collector credentials, and token rotation.
- CPU/memory monitoring, all-visible-process snapshots, exact-identity process history,
  and informational long-running classification (default one hour per host).
- Linux zombie classification; Windows reports not applicable.
- Machines dashboard with filters, pagination, freshness, and partial-visibility indicators.

Existing system/application/security log collection, OS service-state monitoring,
alerts, log search, and reporting are **planned**, not implemented by the resource
collector. No custom application or synthetic log generator is required.

## Run locally

Requirements: Python 3.14+, uv, Node.js/npm compatible with the frontend's Vite
version, and Git. Run these commands from the repository root.

Backend, in one PowerShell terminal:

```powershell
Set-Location .\Backend
uv sync
uv run python db\migrate.py up
uv run create-admin --username admin
uv run uvicorn server:app --reload
```

Create the initial admin once; the CLI prompts for a password. For subsequent
starts, skip account creation. Startup opens the shared database pool but does
not automatically apply migrations.

Frontend, in a separate terminal:

```powershell
Set-Location .\Frontend
npm install
npm run dev
```

Open <http://localhost:5173>. API documentation is at
<http://127.0.0.1:8000/docs> and uses locally served assets.

Sign in, open **Machines**, register a host, and copy its one-time collector token.
Registration alone does not collect data. Follow the [Windows collector setup](Docs/guides/setup/windows.md)
or [Linux and WSL collector setup](Docs/guides/setup/linux.md) to install and run `collect-host`.

## Documentation

- [User guide: using the dashboard and understanding the collector](Docs/guides/user-guide.md)
- [Admin guide: setup, machine registration, and running collectors](Docs/guides/admin-guide.md)
- [Roadmap and implementation status](Docs/roadmap.md)
- [High-Level Design](Docs/design/machine/HLD.md)
- [Database schema and retention](Docs/design/db/database-schema.md)
- [Entity relationships](Docs/design/db/ERD.md)
- [Table guide](Docs/design/db/tables.md)
- [Detailed table reference](Docs/design/db/table-reference.md)
- [Backend setup, APIs, collector, and configuration](Backend/README.md)
- [Frontend setup and dashboard behavior](Frontend/README.md)
- [Academic proposal](Docs/Proposal.docx) and [synopsis](Docs/Synopsis.docx)

## Validation and limitations

The current backend suite contains 48 passing tests. Frontend build/lint and
desktop/mobile browser checks passed; real Windows collection was verified through
HTTP ingestion into isolated SQLite. Native Linux/WSL and external HTTPS collection
still need deployment verification; no WSL distribution was available in the test
environment. See the [roadmap](Docs/roadmap.md) for remaining work.

SQLite is intended for a small lab. Monitoring history queries cover 24 hours;
expired samples are physically pruned when that host next ingests data. Collectors
buffer one pending snapshot and pause sampling during delivery failures, rather
than recording an unlimited offline timeline.