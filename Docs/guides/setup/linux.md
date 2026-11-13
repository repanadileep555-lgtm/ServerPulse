# Linux and WSL Collector Setup

This guide is for anyone setting up the ServerPulse collector on Linux, including Linux
distributions running under WSL. Run all Linux commands in the Linux shell, not Windows
PowerShell. For a native Windows machine, see the [Windows collector setup](windows.md).

## Before you start

- Register the machine in ServerPulse as **Platform: Linux**. For WSL, choose **Deployment: WSL**
  and enter the distro name. In PowerShell, `wsl.exe -l -q` lists installed WSL distributions.
- Copy the machine's one-time collector token. The machine must be enabled.
- Have the ServerPulse project available on this Linux machine. In WSL, a Windows checkout at
  `D:\Projects\ServerPulse` is commonly accessible at `/mnt/d/Projects/ServerPulse`.
- Install Python 3.14 or newer.

## Install uv

In the Linux shell:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv --version
```

If the `source` command reports that the file does not exist, add uv to the current shell's path:

```bash
export PATH="$HOME/.local/bin:$PATH"
uv --version
```

## Install the collector in a Linux virtual environment

Go to the project's `Backend` directory. For the example Windows checkout in WSL:

```bash
cd /mnt/d/Projects/ServerPulse/Backend
```

Use an environment in the Linux home directory. This is especially important when the checkout
is on a Windows-mounted drive: it prevents WSL `uv` from using or modifying the Windows
`Backend/.venv`.

```bash
unset VIRTUAL_ENV
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/serverpulse-collector"
uv python install 3.14
uv sync --python 3.14
uv run python -c 'import sys; print(sys.executable)'
```

The printed Python executable should be under your Linux home directory. Keep this shell open
so `UV_PROJECT_ENVIRONMENT` remains set when you start the collector. No database or administrator
login is needed on the collector machine.

## Set the token

Use the collector token for this exact Linux/WSL machine, not a server, administrator, or Windows
machine credential. Run this command by itself, paste only the token at the hidden prompt, and
press Enter:

```bash
unset SERVERPULSE_COLLECTOR_TOKEN
read -r -s -p 'Paste collector token, then press Enter: ' SERVERPULSE_COLLECTOR_TOKEN
printf '\n'
export SERVERPULSE_COLLECTOR_TOKEN
```

Verify the token length without displaying the token:

```bash
printf 'Token length: %s\n' "${#SERVERPULSE_COLLECTOR_TOKEN}"
```

A newly issued collector token is 43 characters. If the length differs, unset the variable and
enter the token again. If it was exposed or copied incorrectly, rotate it in ServerPulse and use
the new token. Do not paste shell commands into the hidden token prompt.

## Check backend connectivity

If the backend is on the same Linux machine, use `http://127.0.0.1:8000`. For a deployed backend,
use its HTTPS origin.

When the backend is running on Windows and the collector is in WSL, first confirm the backend
responds on Windows at `http://127.0.0.1:8000/health`. Its default bind address is loopback-only.
For WSL access, restart the backend in PowerShell with a WSL-reachable bind address:

```powershell
Set-Location .\Backend
$env:SERVERPULSE_HOST = "0.0.0.0"
uv run uvicorn server:app --reload
```

Binding to `0.0.0.0` listens on network interfaces. Configure Windows Firewall to allow port 8000
only on the trusted network/interface needed for WSL; do not expose the development backend to
untrusted networks.

In WSL's default NAT networking mode, find the Windows host gateway and test it:

```bash
WIN_HOST=$(ip route show | awk '/default/ {print $3; exit}')
echo "$WIN_HOST"
curl --connect-timeout 5 "http://$WIN_HOST:8000/health"
```

Use the address that succeeds as the backend URL below. WSL networking modes differ. If the
gateway check fails, verify the backend bind address, Windows Firewall, and WSL networking mode.
Do not continue until the health check succeeds. Use the `--allow-http` option for this local
development connection only; it sends the collector token without HTTPS.

## Test and run

Set the backend origin. Use the Windows gateway address for a Windows-hosted backend in WSL,
`http://127.0.0.1:8000` for a backend on the same Linux machine, or your HTTPS origin for a
deployed backend:

```bash
# Windows-hosted backend from WSL:
SERVER_URL="http://$WIN_HOST:8000"
# Same Linux machine: SERVER_URL="http://127.0.0.1:8000"
# Deployed backend: SERVER_URL="https://serverpulse.example.edu"
```

Create a state-file location in the Linux home directory and send one test snapshot:

```bash
mkdir -p "$HOME/.local/state/serverpulse"
uv run collect-host \
  --url "$SERVER_URL" \
  --state-file "$HOME/.local/state/serverpulse/collector-state.json" \
  --once
```

For WSL connecting to a Windows-hosted backend over the gateway, add `--allow-http` to the command
because the URL is not loopback. For example:

```bash
uv run collect-host \
  --url "$SERVER_URL" \
  --state-file "$HOME/.local/state/serverpulse/collector-state.json" \
  --once \
  --allow-http
```

A successful run logs `Delivered snapshot`. Start continuous collection by running the same
command without `--once` (and keep `--allow-http` if using the WSL-to-Windows gateway). Keep the
shell open while it runs; press **Ctrl+C** to stop.

`--allow-http` is only for a trusted, isolated development or lab network. Never use it to send
collector credentials over an untrusted network. For a deployed backend, set `SERVER_URL` to its
HTTPS origin and do not use `--allow-http`. WSL collectors must be started and stopped from the
WSL shell; the dashboard's **Start collector** control does not manage WSL processes.

## Troubleshooting

- **uv tries to remove `Backend/.venv/Lib`:** unset `VIRTUAL_ENV` and set
  `UV_PROJECT_ENVIRONMENT` to a directory under `$HOME` as shown above. Do not delete the Windows
  venv.
- **Collector says the token is not set:** run `export SERVERPULSE_COLLECTOR_TOKEN` in the same
  shell, then verify its length. Shell variables created by `read` are not automatically exported.
- **HTTP 401 or 403:** verify the 43-character token belongs to this machine, has not been rotated,
  and the machine is enabled. Rotate and re-enter it if exposed.
- **HTTP header value error or unexpected token length:** the hidden prompt likely received extra
  shell text or a line break. Unset the variable and enter only the token.
- **Backend unreachable:** verify `curl <backend-origin>/health` from this Linux shell and check
  host binding, firewall, and WSL networking. In default NAT mode, do not use `127.0.0.1` for the
  Windows backend.
- **Platform mismatch:** run this collector in Linux/WSL and register the machine with
  **Platform: Linux**.
- **Pending snapshot belongs to another host or backend:** choose a different `--state-file`.

For available collector flags, see [Collector options in the Admin Guide](../admin-guide.md#collector-options).
