# ServerPulse Frontend

React, TypeScript, Vite, and Axios dashboard for the ServerPulse college project.
See the [project overview](../readme.md) and [roadmap](../Docs/roadmap.md).

## Run

From `Frontend`:

```powershell
npm install
npm run dev
```

Open <http://localhost:5173>. Start the backend and apply migrations using the
[backend guide](../Backend/README.md) first. Use Node.js/npm versions compatible
with the installed Vite release.

## API configuration

`VITE_API_BASE_URL` defaults to `http://127.0.0.1:8000`. For another backend:

```powershell
$env:VITE_API_BASE_URL = "https://your-backend.example"
npm run dev
```

This value is public client configuration, not a secret. Vite embeds it at build
time for production: set the intended URL before `npm run build`, then rebuild
when it changes. The Axios client calls this URL directly; the health-only Vite
proxy is not a general API proxy.

The backend's `SERVERPULSE_CORS_ORIGINS` must include the exact browser origin.
`http://localhost:5173` is allowed by default; `http://127.0.0.1:5173`, a different
port, or a deployed frontend origin needs explicit backend configuration.

## Implemented views

- Login/registration, account identity, refresh-token session handling, and sign-out.
- Admin account directory and administrator creation; public registration creates
  regular users only. Bootstrap the first admin using the backend CLI.
- API/database health and session information.
- **Machines**, available to enabled users: host directory, CPU/memory history,
  process search, CPU/memory/runtime/name sorting, pagination, and process history.
- Admin-only machine registration, enable/disable, lifetime threshold editing, and
  collector token rotation. A newly issued collector token is shown once; copy it
  into the collector environment, not a browser persistence store.

Processes are identified by PID plus creation time. Unknown values stay unknown;
first-observation CPU is not zero. Long-running is informational, with a default
one-hour host threshold. Linux zombie classification is not applicable on Windows.
Denied/vanished counts explain incomplete visibility.

Monitoring refreshes without overlapping polling requests at a nominal ten-second
interval. Snapshot age is separate from connectivity: an online collector can
deliver old data. Stale/error states retain prior observations with warnings;
never-seen hosts do not display fabricated zero measurements. Process tables
support horizontal scrolling and keyboard focus on narrow screens.

Log search, OS service monitoring, alerts, and reports are planned, not hidden
features of the process table.

## Authentication

Axios sends bearer access tokens and shares a refresh request when concurrent
requests receive 401. Access tokens stay in memory; refresh tokens are stored in
`sessionStorage` to restore the current browser session. They are accessible to
page JavaScript, not protected HttpOnly cookies. Account roles come from the
backend, not from editable UI flags. See [tokenStore.ts](src/api/tokenStore.ts) and
[AuthProvider.tsx](src/auth/AuthProvider.tsx). Client sign-out clears local tokens
but does not revoke already-issued JWTs server-side.

Do not include account credentials or collector tokens in `VITE_` variables.
Restrict public registration and add deployment hardening before broader exposure.

## Code layout

| Location | Responsibility |
| --- | --- |
| `src/api/client.ts` | API URL, bearer requests, refresh handling, and error mapping |
| `src/api/monitoring.ts` | Typed host/resource/process API contracts |
| `src/auth/` | Authentication/session state |
| `src/components/MachinesMonitoring.tsx` | Machine configuration and monitoring UI |
| `src/components/monitoring.css` | Monitoring-specific responsive styles |
| `src/components/AdminDashboard.tsx`, `UserDashboard.tsx` | Role-specific navigation/views |

## Validation

```powershell
npm run build
npm run lint
npm run preview -- --host localhost --port 5173
```

`build` runs TypeScript checking and produces `dist`; `preview` serves that build,
not the development sources. Stop an existing preview you own before reusing its
port; do not terminate unrelated processes.

Build/lint and desktop/mobile browser checks have passed for the current Machines
feature. Real Windows observations were used for integration checks; mocked edge
states are test fixtures, not proof of native Linux or remote-host collection.
Native Linux/WSL and external HTTPS verification remain roadmap items.
