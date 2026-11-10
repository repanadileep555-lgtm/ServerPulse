# ServerPulse API

## Development

From the `Backend` directory:

```powershell
uv sync
uv run uvicorn server:app --reload
```

Open <http://127.0.0.1:8000/docs> for Swagger UI or
<http://127.0.0.1:8000/redoc> for ReDoc.

Documentation JavaScript, CSS, and favicon assets are served locally using
`fastapi-offline`; no CDN access is required after dependencies are installed.
After dependency changes, run `uv sync` and restart the backend.

## API route organization

Domain routers live in `app/api/routes/`:

- `system.py`: `/` and `/health`, grouped under `system` in Swagger UI.
- `users.py`: `/users/create` and `/users/login`, grouped under `users`.
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
  `token_type: "bearer"`. Invalid credentials or disabled users return 401.
- Send the access token as `Authorization: Bearer <token>` to endpoints using
  the existing `get_current_user` dependency. The JWT subject is the user's ID
  as a string. This does not automatically protect every route.

Registration creates enabled, non-admin users; role flags are not accepted from
clients. Passwords/hashes are never returned. Password hashing runs outside the
event loop, and database access uses the shared startup pool.

Set a stable, private `SERVERPULSE_JWT_SECRET_KEY` for tokens to survive restarts;
the generated default changes when the process restarts. Login uses the existing
JWT expiry setting. JWTs are not stored in `user_tokens` and have no logout/revocation
flow yet; disabling a user blocks new logins, not previously issued JWTs.
Public registration is intended for the college prototype, not administrator
provisioning. Restrict it and add login rate limiting before wider deployment.

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
