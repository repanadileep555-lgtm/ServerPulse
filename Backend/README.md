# ServerPulse API

## Development

From the `Backend` directory:

```powershell
uv sync
uv run python db\migrate.py up
uv run uvicorn server:app --reload
```

Open <http://127.0.0.1:8000/docs> for Swagger UI or
<http://127.0.0.1:8000/redoc> for ReDoc.

Documentation JavaScript, CSS, and favicon assets are served locally using
`fastapi-offline`; no CDN access is required after dependencies are installed.
After dependency changes, run `uv sync` and restart the backend.

Startup initializes one async pool; migrations are an explicit separate step.
The configured database is `Store/serverpulse.db` relative to the repository root.
Use `uv run python db\migrate.py down` only for an intentional rollback: rolling
back `0003_monitoring` deletes resource/process history and monitoring receipts.

## Status and configuration

Implemented: user/admin authentication, host registration and credentials,
resource/process collection and queries, and the Machines dashboard.
Existing-log ingestion, Windows/systemd service checks, alert evaluation, and
reports are planned. Their tables alone do not provide those features. See the
[roadmap](../Docs/roadmap.md) and [HLD](../Docs/design/machine/HLD.md).

Settings use the `SERVERPULSE_` prefix and optionally a `.env` file in the backend
working directory. Do not commit credentials.

| Variable | Default / purpose |
| --- | --- |
| `SERVERPULSE_HOST` | `127.0.0.1`; loopback binding for development |
| `SERVERPULSE_PORT` | `8000` |
| `SERVERPULSE_CORS_ORIGINS` | JSON array `["http://localhost:5173"]`; exact browser origins |
| `SERVERPULSE_JWT_SECRET_KEY` | Generated per process if unset; set a private stable value for persistent sessions |
| `SERVERPULSE_JWT_ALGORITHM` | `HS256` |
| `SERVERPULSE_JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `30` |
| `SERVERPULSE_JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `1` |

`SERVERPULSE_COLLECTOR_TOKEN` is read by the collector, not used as a user JWT.
Backend bind/CORS changes do not replace HTTPS or firewall rules for external hosts.

## API route organization

Domain routers live in `app/api/routes/`:

- `system.py`: `/` and `/health`, grouped under `system` in Swagger UI.
- `users.py`: `/users/create` and `/users/login`, grouped under `users`.
- `hosts.py`: administrator host registration/configuration and authenticated monitoring queries.
- `collector.py`: host-scoped credential validation and monitoring snapshot ingestion.
- `__init__.py`: combines the domain routers for inclusion in `app.main`.

Add future domain routers to this package and include them in its aggregate router.
Keep business logic in `app/services` and shared database dependencies in `app/db`.

## User registration and login

Apply the existing migrations before using the user endpoints:

```powershell
uv run python db\migrate.py up
```

- `POST /users/create`: JSON `{"username": "student", "password": "a-long-password"}`.
  Returns HTTP 201 with public user fields; duplicate usernames return 409.
  Usernames are case-sensitive, 3-64 ASCII letters/digits or `_`, `.`, `-`.
  Passwords are 8-128 characters and stored as salted Argon2 hashes.
- `POST /users/login`: the same JSON credentials. Returns `access_token` and
  `refresh_token`, plus `token_type: "bearer"`. Invalid credentials or disabled
  users return 401.
- `POST /users/refresh`: JSON `{"refresh_token": "<refresh JWT>"}`; returns a new
  access token without rotating the refresh token. Expired/invalid refresh tokens
  or disabled accounts return 401.
- `GET /users/me`: the enabled account profile for the bearer access token.
- `GET /users`: enabled administrators can list accounts.
- `POST /users/admins`: enabled administrators can create another administrator
  using the same username/password input.
- Send the access token as `Authorization: Bearer <token>` to endpoints using
  the existing `get_current_user` dependency. The JWT subject is the user's ID
  as a string. This does not automatically protect every route.

Registration creates enabled, non-admin users; role flags are not accepted from
clients. Passwords/hashes are never returned. Password hashing runs outside the
event loop, and database access uses the shared startup pool.

Bootstrap the first administrator once after migrations:

```powershell
uv run create-admin --username admin
```

The CLI securely prompts for and confirms the password; it does not promote an
existing account with the same username. Subsequent admins can be created through
the admin UI/API.

Set a stable, private `SERVERPULSE_JWT_SECRET_KEY` for tokens to survive restarts;
the generated default changes when the process restarts. Login uses the existing
JWT expiry settings. JWTs are not stored in `user_tokens`; that table is reserved
for a possible opaque-token flow. There is no server-side JWT logout/revocation
flow yet. Disabled accounts cannot log in, refresh, use `/users/me`, read monitoring,
or pass enabled-admin checks. The generic `get_current_user` dependency validates
the JWT itself, so routes using only that dependency do not automatically recheck
account availability. Client sign-out clears browser tokens, not issued JWTs.
Public registration is intended for the college prototype, not administrator
provisioning. Restrict it and add login rate limiting before wider deployment.

## Machine resource and process monitoring

1. Run `uv sync`, then `uv run python db\migrate.py up` to apply migration
   `0003_monitoring` (do not recreate an existing database).
2. Sign in and open **Machines** in the dashboard. Register Windows localhost, a Linux WSL
   distribution, or an external Windows/Linux host. Any signed-in user can register a machine;
   you only see machines you registered (administrators see all). The per-host long-running
   threshold defaults to 3600 seconds.
3. Copy the one-time collector token. Only its SHA-256 digest is stored. Rotation
   revokes previous collector credentials; disabling a host rejects further pushes.
4. On each monitored machine, install this backend package with Python 3.14+ and
   `uv sync`. The collector does not need a local database, an administrator JWT,
   or the backend server running on that machine.
5. Set `SERVERPULSE_COLLECTOR_TOKEN` in that collector's environment without
   committing it to a file or Git, then run:

   ```powershell
   uv run collect-host --url http://127.0.0.1:8000 --state-file collector-state.json
   ```

   For WSL run the collector inside the distribution, not from Windows Python.
   Use the Windows backend address reachable from WSL. External hosts use a
   reachable HTTPS backend origin. `--allow-http` is for trusted isolated labs
   only when loopback is not available; never disable TLS certificate validation.
   `--once` sends one snapshot and exits; `--interval 10` controls collection.
   Sampling never overlaps: on machines with many processes, the effective interval
   is at least the time needed to finish collection and delivery.

The collector reads real CPU, physical/guest memory, and every visible process
using `psutil`. WSL reports its Linux environment's resources, not total physical
Windows resources. Process details include PID, creation time, name, status,
CPU percentage, RSS bytes, and percentage of total memory. No command lines,
environment variables, or usernames are collected.

- Host CPU is a one-second sample (0-100). Process CPU is the delta since its
  previous observation divided by logical CPU count (0-100 across the machine).
  First observations and recycled PIDs have unknown CPU, not zero.
- Used memory means total minus available; process memory uses RSS. Shared pages
  can be counted in multiple processes, so process RSS totals are not host usage.
- Long-running means elapsed lifetime at least the host threshold; it is
  informational, not evidence that a process is hung or consuming CPU.
- Linux zombies are terminated processes awaiting parent reaping. Windows zombie
  values are null/not applicable. No automatic kill, restart, or remediation occurs.
- Permission failures retain partial rows and a denied count; processes that exit
  while reading are counted as vanished. Restricted visibility is explicit.

Each snapshot is persisted atomically to the collector state file before upload.
Retries preserve its batch ID; the backend rejects conflicting reuse and commits
the entire snapshot before acknowledging. Only one collector should run for a
host/state file at a time. Stop an old collector before starting its replacement.
Transient network/5xx failures retry with backoff; permanent 4xx failures stop
visibly with pending data retained. A snapshot older than 24 hours requires an
operator to archive/delete that exact pending file and restart collection; do not
silently discard it. Disk/permission/sampling errors also stop explicitly.

The collector buffers one snapshot, not unlimited outage history: it pauses
sampling while delivery is blocked. Snapshots are limited to 20,000 processes and
16 MiB. This targets a small lab; recording all processes every 10 seconds can
consume significant SQLite disk space. Increase the interval if needed.

### APIs and freshness

User JWT required (enabled accounts only):

| Method | Path | Purpose |
| --- | --- | --- |
| GET / POST | `/hosts` | Directory / admin registration with one-time token |
| PATCH | `/hosts/{id}` | Admin enabled flag and long-running threshold |
| POST | `/hosts/{id}/credentials/rotate` | Owner or admin rotates collector token (admin rotations notify the owner) |
| GET | `/notifications` | List the caller's unread notifications |
| POST | `/notifications/{id}/read` | Mark a notification as read |
| GET | `/hosts/{id}/local-collector` | Whether the server-run collector for a localhost host is running |
| POST | `/hosts/{id}/local-collector/start` | Start the collector for a localhost host (issues a new token, replacing the old one) |
| POST | `/hosts/{id}/local-collector/stop` | Stop the server-run collector for a localhost host |
| GET | `/hosts/{id}/monitoring` | Latest sample and host connectivity |
| GET | `/hosts/{id}/metrics?limit=120` | Recent CPU/memory history |
| GET | `/hosts/{id}/processes` | Latest snapshot, paginated/filterable/sortable processes |
| GET | `/hosts/{id}/process-history?pid=42&create_time=...` | History for PID + creation time |

`/processes` supports `offset`, `limit` (up to 200), `search`, `long_running=true`,
`zombie=true`, and `sort=cpu|memory|runtime|name`. History limits are at most 500.
Process identity never consists of PID alone.

Collector token required, separate from user JWTs:

- `GET /collector/configuration`: this credential's registered host only.
- `POST /collector/snapshots`: bounded JSON monitoring snapshot. Host ownership
  comes from the token; the payload cannot choose a host. See the `MonitoringBatch`
  model for fields. This streamed upload validates JSON without echoing process
  payloads in validation errors.

Accepted snapshots update receipt-time heartbeat; after 60 seconds without one,
the host is offline. The last sample remains visible with its timestamp rather
than becoming zeros. Late arrivals cannot replace a newer snapshot. Threshold
edits take effect on subsequent samples.

History queries cover the last 24 hours. Physical cleanup of older samples and
their process rows occurs on the next new ingestion for that host, not on a timer;
an offline host can retain its stale last snapshot until collection resumes.
Receipts remain for seven days for retry acknowledgement even after sample deletion.
Hosts that never sent data show an empty state, not healthy zero usage.

## Async SQLite pool

FastAPI's lifespan opens one shared pool during server startup and stores it in
`app.state.db_pool`. Requests borrow connections from this pool rather than opening
a new pool. Startup fails if initialization fails, and shutdown closes the pool.

Routes can use the `get_database_pool` dependency from `app.db.db_client`:

```python
from typing import Annotated

from fastapi import Depends
from app.db.db_client import get_database_pool
from app.db.db_pool import DatabasePool

async def handler(pool: Annotated[DatabasePool, Depends(get_database_pool)]):
    return await pool.fetch_one("SELECT 1 AS ok")
```

Do not enter or close the shared pool inside a request; the lifespan owns it.
Query methods must be awaited. For standalone scripts or tests, open a separate
pool using an async context manager; construction alone does not open connections:

```python
from app.db.db_pool import DatabasePool

async with DatabasePool() as pool:
    row = await pool.fetch_one("SELECT 1 AS ok")
    async with pool.transaction() as connection:
        async with connection.execute("SELECT 2 AS ok") as cursor:
            result = await cursor.fetchone()
```

Use `async with pool.connection()` for direct connection access. Operations on
the returned `aiosqlite` connection/cursors are asynchronous as well. Transactions
commit on success and roll back on exceptions or cancellation. A borrowed
connection is rolled back before returning to the pool if a transaction remains.
Pool acquisition has a timeout and does not block the event loop.

Keep the pool on one event loop and finish all tasks borrowing connections before
closing it. There is one shared pool per server process, not one across workers.

## Verification

```powershell
uv run python -m unittest discover -s tests -p "test_*.py" -v
uv lock --check
```

Current results: 48 backend tests passed, including authentication, pool lifecycle,
monitoring migrations, credential scoping, snapshot retries, retention, process
identity/CPU warm-up, and permission/zombie fixtures. Real Windows collector
subprocesses were verified through HTTP into an isolated SQLite database.
Native Linux/WSL and separate-host HTTPS checks remain pending; fixtures alone do
not verify those environments. No WSL distribution was installed during validation.
