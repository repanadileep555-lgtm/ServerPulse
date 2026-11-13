# ServerPulse Admin Guide

This guide explains how to set up ServerPulse, register machines, and run their collectors.
For day-to-day dashboard use, see the [User Guide](user-guide.md).

## 1. How the pieces fit together

```text
 Each monitored machine                       Central computer
+-------------------------+   HTTP(S) push   +----------------------------+
| collect-host (collector) | ───────────────> | ServerPulse backend (API)  |
|  - measures CPU/memory   |  with host token |  - stores data in SQLite   |
|  - lists processes       |                  |                            |
+-------------------------+                  +-------------▲--------------+
                                                           │ sign-in (JWT)
                                             +-------------┴--------------+
                                             | Dashboard (browser)        |
                                             +----------------------------+
```

- **Backend:** the central server. It stores users, machines, and monitoring history.
- **Dashboard:** the web interface used by users and administrators.
- **Collector:** a small program on each monitored machine. It pushes measurements to the backend.
  It needs only the backend address and its own token. It does not need a database,
  an administrator login, or the backend running on that machine.

Each machine gets its own collector token. A collector can only send data for the machine it was registered for.

## 2. First-time setup of the central server

Requirements: Python 3.14+, [uv](https://docs.astral.sh/uv/), Node.js (for the dashboard), and Git.
Run commands from the repository root.

**Backend** (one PowerShell window):

```powershell
Set-Location .\Backend
uv sync
uv run python db\migrate.py up
uv run create-admin --username admin
uv run uvicorn server:app --reload
```

- `migrate.py up` creates or updates the database. Run it once after setup and again after updates.
- `create-admin` creates the first administrator. It asks for a password. Run it once only.

**Dashboard** (a second PowerShell window):

```powershell
Set-Location .\Frontend
npm install
npm run dev
```

Open <http://localhost:5173> and sign in as the administrator.

### Settings that matter

Settings use the `SERVERPULSE_` prefix and can go in a `.env` file in the `Backend` folder.
Never commit secrets to Git.

| Setting | What to do |
| --- | --- |
| `SERVERPULSE_JWT_SECRET_KEY` | Set a long private value so users stay signed in after a server restart. |
| `SERVERPULSE_CORS_ORIGINS` | Set to the exact dashboard address (for example `["http://localhost:5173"]`). |
| `SERVERPULSE_HOST` / `SERVERPULSE_PORT` | Keep `127.0.0.1` / `8000` for local use. |

## 3. Registering a machine

Any signed-in user can register machines. Each user sees only the machines they registered;
administrators see all machines. A machine name only needs to be unique among the machines
registered by the same user.

1. Sign in, open **Machines**, and expand **Register a machine**.
2. Fill in the form:
   | Field | What to enter |
   | --- | --- |
   | Machine name | A unique name, for example `Office-PC-01`. Start with a letter or digit. Use letters, digits, spaces, `_`, `.`, or `-` (up to 100 characters). |
   | Platform | **Windows** or **Linux**. |
   | Deployment | **Localhost** (this computer), **WSL** (a Linux distribution inside Windows; Linux platform only), or **External** (another computer). |
   | WSL distribution | Only for WSL: the distribution name, for example `Ubuntu`. |
   | Long-running threshold | Seconds before a process is labeled long-running. Default `3600` (one hour). Allowed range: 60 to 31536000. |

3. Click **Register machine**.
4. A dialog shows the **collector token** once. Copy it and store it somewhere safe
   (for example, a password manager). It cannot be shown again. If you lose it, rotate it (section 5).

Registration alone does not collect data. Continue with section 4 on the monitored machine.

## 4. Setting up the collector

Collector setup instructions are split by operating system and can be followed by machine owners
or administrators:

- [Windows collector setup](setup/windows.md)
- [Linux and WSL collector setup](setup/linux.md)

The collector does not need a local database or administrator login. For either platform, use the
collector token issued for that exact machine. Remote collectors should use HTTPS. `--allow-http`
is only for trusted, isolated development or lab networks.

### Collector options

| Option | Meaning |
| --- | --- |
| `--url` | Address of the ServerPulse server (no path, no username or password in the address). |
| `--state-file` | Local file that holds one pending measurement. Keep it on the machine. Use a different file name for each collector. |
| `--interval` | Seconds between measurements, from 2 to 3600. Default 10. |
| `--once` | Send one measurement and exit. Useful for testing. |
| `--allow-http` | Allow plain HTTP for a non-local address on a trusted lab network. |

### Confirming it works

- Run with `--once` first. A successful run logs "Delivered snapshot".
- Then run without `--once` and check the machine on the **Machines** page. It should show as connected within a minute.

### What the collector sends

CPU, memory, and per-process details (PID, creation time, name, status, CPU %, memory use, and status).
It does **not** send command lines, environment variables, or user names.

## 5. Managing machines and tokens

Available in the **Machines** page for administrators:

- **Edit the long-running threshold.** Changes apply from the next measurement.
- **Enable or disable a machine.** A disabled machine's collector is rejected and its new measurements are not accepted.
- **Rotate the collector token.** Creates a new token and shows it once. The old token stops working immediately.
  Update the environment variable on that machine and restart its collector.

Rotate a token whenever it may have been exposed, or when the collector computer changes.

## 6. Managing users

- Non-administrator accounts can sign in and view monitoring data.
- Administrators can see the account directory, create other administrators, and manage machines.
- Public registration creates regular accounts only. Administrator access must be granted through `create-admin` or by an existing administrator.

For the college prototype, restrict who can reach the registration endpoint. Add login rate limiting before wider use.

## 7. Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| Machine shows **offline** | Collector stopped, or the server address is wrong or unreachable. Check the collector window and the `--url`. |
| Collector says "Set SERVERPULSE_COLLECTOR_TOKEN" | The variable is not set or exported in the shell where the collector runs. Follow the [Windows](setup/windows.md#set-the-token) or [Linux/WSL](setup/linux.md#set-the-token) token instructions. |
| Collector says the platform does not match | The machine was registered as the wrong platform. Register it again with the correct platform. |
| Collector reports HTTP 401 or 403 | Wrong, malformed, rotated, or disabled token, or the machine is disabled. Re-enter the token for this exact machine; rotate it if lost or exposed. |
| Collector reports HTTP 4xx and stops | The pending data is kept in the state file. Fix the cause, then restart. A snapshot older than 24 hours must be moved or deleted by hand; do not delete it silently. |
| Collector reports "Pending snapshot belongs to another backend/host" | The state file came from another machine or server. Use a different `--state-file` name. |
| WSL collector cannot connect | Confirm the backend health check works from WSL, the backend is listening on a WSL-reachable interface, and Windows Firewall allows the required connection. In default NAT mode, use the Windows gateway address, not `127.0.0.1`. |
| uv reports it cannot remove `Backend/.venv/Lib` from WSL | The Windows venv is on the mounted Windows drive. In WSL, unset `VIRTUAL_ENV` and set `UV_PROJECT_ENVIRONMENT` to a separate path under `$HOME` as described above; do not delete the Windows venv. |
| WSL collector reports HTTP 401 | Re-enter the 43-character collector token for this WSL machine. If it was exposed or copied incorrectly, rotate it and enter the newly issued token. |
| Two collectors for one machine | Stop the old one first. Only one collector should use a given state file. |
| Dashboard data stops | Check the server is running and that `migrate.py up` has been applied after updates. |

Data limits: history queries cover the last 24 hours. Older samples are removed when that machine next sends data.
Each collector keeps only one pending measurement, so long outages do not build up a large backlog.
SQLite is intended for a small lab; sending every process every 10 seconds can use noticeable disk space. Increase `--interval` if needed.

## 8. Current limits

Implemented: user accounts, machine registration, collector tokens, CPU/memory/process monitoring, the Machines dashboard, and a service inventory with observed state for Windows Services and systemd services.

Planned, not yet available: service state-change history, alerts, log search, and reports.

Linux, WSL, and separate-HTTPS-host support still need final verification on real machines. See the [roadmap](../roadmap.md).

## Related documents

- [Backend setup and API details](../../Backend/README.md)
- [Frontend setup](../../Frontend/README.md)
- [Architecture (HLD)](../design/machine/HLD.md)
