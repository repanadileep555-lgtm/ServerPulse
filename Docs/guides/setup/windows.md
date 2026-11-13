# Windows Collector Setup

This guide is for anyone setting up the ServerPulse collector on Windows.
For a WSL or Linux machine, see the [Linux collector setup](linux.md).

## Before you start

- Register the Windows machine in ServerPulse and copy its one-time collector token.
  The token must belong to this machine and the machine must be enabled.
- Have the ServerPulse project available on this machine.
- Install Python 3.14 or newer and [uv](https://docs.astral.sh/uv/).

## Install the collector

Open PowerShell in the project root, then change to the `Backend` directory:

```powershell
Set-Location .\Backend
uv sync
```

The collector does not need a local database or administrator login.

## Set the token

Enter the token at the secure prompt. It will not be echoed or included in the command history:

```powershell
$secureToken = Read-Host "Collector token" -AsSecureString
$tokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
try {
    $env:SERVERPULSE_COLLECTOR_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPointer)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPointer)
}
```

Keep the PowerShell window open while the collector runs. The environment variable is cleared
when that window closes. Do not save the token in a file or commit it to Git.

## Test and run

For a Windows machine on the same computer as the backend, use loopback:

```powershell
$serverUrl = "http://127.0.0.1:8000"
```

For a machine connecting to a deployed backend, use its HTTPS origin instead:

```powershell
$serverUrl = "https://serverpulse.example.edu"
```

Replace the example URL with your backend address. Test delivery once:

```powershell
$stateFile = Join-Path $env:LOCALAPPDATA "ServerPulse\collector-state.json"
New-Item -ItemType Directory -Force (Split-Path $stateFile) | Out-Null
uv run collect-host --url $serverUrl --state-file $stateFile --once
```

A successful run logs `Delivered snapshot`. Then start continuous collection by running the same
command without `--once`:

```powershell
uv run collect-host --url $serverUrl --state-file $stateFile
```

Keep the window open while it runs; press **Ctrl+C** to stop. A Windows `localhost` machine can
also be started and stopped from the dashboard's **Start collector** control.

## Troubleshooting

- **Token variable not set:** enter and export the token in the same PowerShell window used to run
  the collector.
- **HTTP 401 or 403:** verify that you used this machine's current collector token and that the
  machine is enabled. Rotate the token if it was exposed.
- **Platform mismatch:** this collector must run on Windows and the machine must be registered
  with **Platform: Windows**.
- **Backend unreachable:** check the backend URL and confirm it is running. Use HTTPS for deployed
  backends; do not use plain HTTP over an untrusted network.
- **Pending snapshot belongs to another host or backend:** choose a different `--state-file`.

For available collector flags, see [Collector options in the Admin Guide](../admin-guide.md#collector-options).
