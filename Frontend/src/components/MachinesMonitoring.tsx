import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import {
  createAlertRule,
  createHost,
  deleteAlertRule,
  getLocalCollector,
  getLogs,
  getLogSources,
  getHostServices,
  getMetrics,
  getMonitoring,
  getProcessHistory,
  getProcesses,
  getSSHCollector,
  installSSHCollector,
  listAlertRules,
  listHosts,
  listMachineAlerts,
  rotateCollectorToken,
  scanSSHHost,
  startLocalCollector,
  startSSHCollector,
  stopLocalCollector,
  stopSSHCollector,
  updateAlertRule,
  updateHost,
  type AlertMetric,
  type AlertRule,
  type AlertRuleUpsert,
  type Connectivity,
  type DeploymentType,
  type Host,
  type HostPlatform,
  type HostService,
  type LocalCollectorState,
  type LogPage,
  type LogQuery,
  type LogSeverity,
  type LogSource,
  type MachineAlert,
  type ProcessHistoryObservation,
  type ProcessObservation,
  type ProcessPage,
  type Sample,
  type SSHCollectorState,
  type SSHScanResult,
} from '../api/monitoring'
import './monitoring.css'

const POLL_INTERVAL_MS = 10_000
const PROCESS_PAGE_SIZE = 50

interface HostCollection {
  items: Host[]
  loading: boolean
  error: string | null
}

interface MonitoringCollection {
  hostId: number
  latest: Sample | null
}

interface MetricsCollection {
  hostId: number
  items: Sample[]
}

interface ProcessCollection {
  key: string
  data: ProcessPage
}

interface SelectedProcess {
  hostId: number
  pid: number
  createTime: string
}

interface CollectorToken {
  hostName: string
  value: string
  action: 'registration' | 'rotation'
}

function requestFailure(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Your session has expired. Sign in again to continue.'
    if (error.status === 403) return 'You do not have permission to perform this action.'
    if (error.status === 404) return 'This machine is no longer available.'
  }
  return fallback
}

function formatTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString()
}

function formatRelativeTime(value: string | null | undefined): string {
  if (!value) return 'No snapshot yet'
  const time = new Date(value).getTime()
  if (Number.isNaN(time)) return 'Unknown snapshot age'
  const seconds = Math.max(0, Math.floor((Date.now() - time) / 1000))
  if (seconds < 10) return 'Updated just now'
  if (seconds < 60) return `Updated ${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `Updated ${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `Updated ${hours}h ago`
  return `Updated ${Math.floor(hours / 24)}d ago`
}

function formatPercent(value: number | null): string {
  return value === null || !Number.isFinite(value) ? '—' : `${value.toFixed(1)}%`
}

function formatBytes(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—'
  if (value < 0) return '—'
  if (value < 1024) return `${value} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let amount = value
  let unitIndex = -1
  do {
    amount /= 1024
    unitIndex += 1
  } while (amount >= 1024 && unitIndex < units.length - 1)
  return `${amount.toFixed(amount < 10 ? 1 : 0)} ${units[unitIndex]}`
}

function formatRuntime(value: number | null): string {
  if (value === null || !Number.isFinite(value) || value < 0) return '—'
  const seconds = Math.floor(value)
  const days = Math.floor(seconds / 86_400)
  const hours = Math.floor((seconds % 86_400) / 3_600)
  const minutes = Math.floor((seconds % 3_600) / 60)
  if (days > 0) return `${days}d ${hours}h`
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m ${seconds % 60}s`
}

function connectivityLabel(value: Connectivity): string {
  switch (value) {
    case 'online':
      return 'Online'
    case 'offline':
      return 'Offline'
    case 'disabled':
      return 'Disabled'
    default:
      return 'Never seen'
  }
}

function connectivityClass(value: Connectivity): string {
  if (value === 'online') return 'machine-status-online'
  if (value === 'offline') return 'machine-status-offline'
  if (value === 'disabled') return 'machine-status-disabled'
  return 'machine-status-unknown'
}

function displayBoolean(value: boolean | null): string {
  if (value === null) return '—'
  return value ? 'Yes' : 'No'
}

function MeterRow({ label, value }: { label: string; value: number | null }) {
  const width = Math.min(100, Math.max(0, value ?? 0))
  return (
    <span className="machine-meter">
      <span className="machine-meter-label">{label}</span>
      <span className="machine-meter-track" aria-hidden="true">
        <span className="machine-meter-fill" style={{ width: `${width}%` }} />
      </span>
      <span className="machine-meter-value">{value === null ? '—' : `${value.toFixed(1)}%`}</span>
    </span>
  )
}

function MetricChart({ samples }: { samples: Sample[] }) {
  if (samples.length === 0) {
    return <p className="machine-empty-note">No metric history has been collected yet.</p>
  }
  const width = 720
  const height = 190
  const padding = 18
  const pointList = (value: 'cpu_percent' | 'memory_percent') =>
    samples
      .map((sample, index) => {
        const x = padding + (index / Math.max(1, samples.length - 1)) * (width - padding * 2)
        const amount = Math.max(0, Math.min(100, sample[value]))
        const y = padding + ((100 - amount) / 100) * (height - padding * 2)
        return `${x},${y}`
      })
      .join(' ')

  return (
    <figure className="machine-chart">
      <div className="machine-chart-legend">
        <span><i className="machine-legend-cpu" />CPU</span>
        <span><i className="machine-legend-memory" />Memory</span>
        <span className="machine-chart-range">
          {formatTime(samples[0].sampled_at)} — {formatTime(samples[samples.length - 1].sampled_at)}
        </span>
      </div>
      <svg className="machine-chart-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby="machine-chart-title machine-chart-description">
        <title id="machine-chart-title">CPU and memory utilization history</title>
        <desc id="machine-chart-description">
          {samples.length} collected observations over the retained history period. CPU is shown in blue and memory in teal.
        </desc>
        {[0, 25, 50, 75, 100].map((tick) => {
          const y = padding + ((100 - tick) / 100) * (height - padding * 2)
          return (
            <g key={tick}>
              <line x1={padding} y1={y} x2={width - padding} y2={y} className="machine-chart-grid" />
              <text x="0" y={y + 4} className="machine-chart-tick">{tick}</text>
            </g>
          )
        })}
        <polyline points={pointList('cpu_percent')} className="machine-chart-line machine-chart-line-cpu" />
        <polyline points={pointList('memory_percent')} className="machine-chart-line machine-chart-line-memory" />
      </svg>
      <figcaption className="machine-chart-caption">Percent of reported capacity · retained observations, up to 24 hours</figcaption>
    </figure>
  )
}

function HostRegistration({ onCreated }: { onCreated: (host: Host, token: string) => void }) {
  const [name, setName] = useState('')
  const [platform, setPlatform] = useState<HostPlatform>('windows')
  const [deployment, setDeployment] = useState<DeploymentType>('localhost')
  const [distro, setDistro] = useState('')
  const [threshold, setThreshold] = useState('3600')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!name.trim()) {
      setError('Enter a machine name.')
      return
    }
    if (deployment === 'wsl' && !distro.trim()) {
      setError('Enter the WSL distribution name.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const response = await createHost({
        name: name.trim(),
        platform,
        deployment_type: deployment,
        wsl_distro: deployment === 'wsl' ? distro.trim() : null,
        long_running_seconds: Number(threshold),
      })
      setName('')
      setDistro('')
      setThreshold('3600')
      onCreated(response.host, response.collector_token)
    } catch (requestError) {
      const message =
        requestError instanceof ApiError && requestError.status === 409
          ? 'This machine is already registered.'
          : requestFailure(requestError, 'Could not register this machine. Check the API connection and try again.')
      setError(message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <details className="machine-register">
      <summary>Register a machine</summary>
      <form className="machine-form" onSubmit={submit}>
        <label className="machine-field">
          <span>Machine name</span>
          <input value={name} onChange={(event) => setName(event.target.value)} required maxLength={120} />
        </label>
        <div className="machine-form-row">
          <label className="machine-field">
            <span>Platform</span>
            <select
              value={platform}
              onChange={(event) => {
                const nextPlatform = event.target.value as HostPlatform
                setPlatform(nextPlatform)
                if (nextPlatform === 'windows' && deployment === 'wsl') setDeployment('localhost')
              }}
            >
              <option value="windows">Windows</option>
              <option value="linux">Linux</option>
            </select>
          </label>
          <label className="machine-field">
            <span>Deployment</span>
            <select value={deployment} onChange={(event) => setDeployment(event.target.value as DeploymentType)}>
              <option value="localhost">Localhost</option>
              {platform === 'linux' && <option value="wsl">WSL</option>}
              <option value="external">External</option>
            </select>
          </label>
        </div>
        {deployment === 'wsl' && (
          <label className="machine-field">
            <span>WSL distribution</span>
            <input value={distro} onChange={(event) => setDistro(event.target.value)} required maxLength={120} />
          </label>
        )}
        <label className="machine-field">
          <span>Long-running threshold (seconds)</span>
          <input
            type="number"
            min="1"
            step="1"
            value={threshold}
            onChange={(event) => setThreshold(event.target.value)}
            required
          />
        </label>
        {error && <p className="machine-alert machine-alert-error" role="alert">{error}</p>}
        <button type="submit" className="btn btn-primary" disabled={submitting}>
          {submitting ? 'Registering…' : 'Register machine'}
        </button>
      </form>
    </details>
  )
}

function SSHRegistration({ onInstalled }: { onInstalled: (host: Host) => void }) {
  const [address, setAddress] = useState('')
  const [port, setPort] = useState('22')
  const [scan, setScan] = useState<SSHScanResult | null>(null)
  const [trusted, setTrusted] = useState(false)
  const [name, setName] = useState('')
  const [username, setUsername] = useState('')
  const [authMethod, setAuthMethod] = useState<'password' | 'private_key'>('password')
  const [secret, setSecret] = useState('')
  const [threshold, setThreshold] = useState('3600')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function changeTarget(nextAddress: string, nextPort: string) {
    setAddress(nextAddress)
    setPort(nextPort)
    setScan(null)
    setTrusted(false)
  }

  function parsedPort(): number | null {
    const value = Number(port)
    return Number.isInteger(value) && value >= 1 && value <= 65535 ? value : null
  }

  async function checkHost() {
    const portNumber = parsedPort()
    if (!address.trim()) {
      setError('Enter the server address.')
      return
    }
    if (portNumber === null) {
      setError('Enter a valid SSH port between 1 and 65535.')
      return
    }
    setPending(true)
    setError(null)
    try {
      setScan(await scanSSHHost(address.trim(), portNumber))
    } catch (requestError) {
      setError(requestFailure(requestError, 'Could not reach the server over SSH. Check the address and port.'))
    } finally {
      setPending(false)
    }
  }

  async function install(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!scan) return
    if (!trusted) {
      setError('Confirm that the server fingerprint matches the one you expect.')
      return
    }
    if (!name.trim() || !username.trim() || !secret) {
      setError('Enter a machine name, SSH username, and password or private key.')
      return
    }
    setPending(true)
    setError(null)
    try {
      const response = await installSSHCollector({
        name: name.trim(),
        address: scan.address,
        port: scan.port,
        username: username.trim(),
        auth_method: authMethod,
        secret,
        host_key_fingerprint: scan.host_key_fingerprint,
        long_running_seconds: Number(threshold),
      })
      setSecret('')
      setName('')
      setUsername('')
      setThreshold('3600')
      changeTarget('', '22')
      onInstalled(response.host)
    } catch (requestError) {
      setError(requestFailure(requestError, 'Could not install the collector over SSH. Check the details and try again.'))
    } finally {
      setPending(false)
    }
  }

  return (
    <details className="machine-register">
      <summary>Connect a Linux server over SSH</summary>
      <div className="machine-form">
        <div className="machine-form-row">
          <label className="machine-field">
            <span>Server address</span>
            <input value={address} onChange={(event) => changeTarget(event.target.value, port)} maxLength={255} />
          </label>
          <label className="machine-field">
            <span>SSH port</span>
            <input type="number" min="1" max="65535" value={port} onChange={(event) => changeTarget(address, event.target.value)} />
          </label>
        </div>
        <button type="button" className="btn btn-ghost" onClick={() => void checkHost()} disabled={pending}>
          {pending && !scan ? 'Checking…' : 'Check server'}
        </button>

        {scan && (
          <form className="machine-form" onSubmit={install}>
            <div className="machine-settings-note">
              <p>Host key ({scan.host_key_algorithm}):</p>
              <code>{scan.host_key_fingerprint}</code>
              <p>Compare this with the fingerprint you expect for the server before continuing.</p>
            </div>
            <label className="machine-field machine-checkbox">
              <input type="checkbox" checked={trusted} onChange={(event) => setTrusted(event.target.checked)} />
              <span>The fingerprint matches the server I expect</span>
            </label>
            <label className="machine-field">
              <span>Machine name</span>
              <input value={name} onChange={(event) => setName(event.target.value)} required maxLength={100} />
            </label>
            <div className="machine-form-row">
              <label className="machine-field">
                <span>SSH username</span>
                <input value={username} onChange={(event) => setUsername(event.target.value)} required maxLength={64} />
              </label>
              <label className="machine-field">
                <span>Authentication</span>
                <select value={authMethod} onChange={(event) => setAuthMethod(event.target.value as 'password' | 'private_key')}>
                  <option value="password">Password</option>
                  <option value="private_key">Private key (unencrypted)</option>
                </select>
              </label>
            </div>
            <label className="machine-field">
              <span>{authMethod === 'password' ? 'Password' : 'Private key (PEM)'}</span>
              {authMethod === 'password' ? (
                <input type="password" value={secret} onChange={(event) => setSecret(event.target.value)} autoComplete="off" required />
              ) : (
                <textarea rows={5} value={secret} onChange={(event) => setSecret(event.target.value)} autoComplete="off" required />
              )}
            </label>
            <label className="machine-field">
              <span>Long-running threshold (seconds)</span>
              <input type="number" min="60" step="1" value={threshold} onChange={(event) => setThreshold(event.target.value)} required />
            </label>
            <p className="machine-settings-note">
              The server needs Linux with Python 3.11 or newer, pip access, and SSH TCP forwarding enabled.
              Credentials are stored encrypted on this ServerPulse instance.
            </p>
            <button type="submit" className="btn btn-primary" disabled={pending || !trusted}>
              {pending ? 'Installing…' : 'Install collector over SSH'}
            </button>
          </form>
        )}

        {error && <p className="machine-alert machine-alert-error" role="alert">{error}</p>}
      </div>
    </details>
  )
}

function SSHCollectorControl({ host }: { host: Host }) {
  const [state, setState] = useState<SSHCollectorState | null>(null)
  const [unavailable, setUnavailable] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const isExternal = host.deployment_type === 'external'

  useEffect(() => {
    if (!isExternal) return
    const controller = new AbortController()
    getSSHCollector(host.id, controller.signal)
      .then(setState)
      .catch((requestError: unknown) => {
        if (controller.signal.aborted) return
        if (requestError instanceof ApiError && requestError.status === 404) setUnavailable(true)
        else setError(requestFailure(requestError, 'Could not load the SSH collector status.'))
      })
    return () => controller.abort()
  }, [host.id, isExternal])

  if (!isExternal || unavailable) return null

  async function toggle() {
    const running = state?.ssh.desired_state === 'running'
    setPending(true)
    setError(null)
    setNotice(null)
    try {
      if (running) {
        const next = await stopSSHCollector(host.id)
        setState(next)
        if (next.remote_stopped === false) {
          setNotice('The server could not be reached, so the collector is still running there. It will stop the next time the server is reachable and you press Stop.')
        }
      } else {
        setState(await startSSHCollector(host.id))
      }
    } catch (requestError) {
      setError(requestFailure(requestError, 'Could not change the SSH collector. Try again.'))
    } finally {
      setPending(false)
    }
  }

  const running = state?.ssh.desired_state === 'running'
  return (
    <section className="machine-panel machine-local-collector" aria-labelledby="ssh-collector-title">
      <div className="machine-section-heading">
        <div>
          <p className="machine-eyebrow">Remote server over SSH</p>
          <h3 id="ssh-collector-title">Collector process</h3>
        </div>
      </div>
      {error && <p className="machine-alert machine-alert-error" role="alert">{error}</p>}
      {notice && <p className="machine-alert machine-alert-warning" role="status">{notice}</p>}
      <div className="machine-settings-row">
        <span>
          {state === null
            ? 'Checking collector…'
            : `${state.ssh.username}@${state.ssh.address}:${state.ssh.port} · ${running ? (state.ssh.connected ? 'Running, tunnel connected' : 'Running, reconnecting') : 'Stopped'}`}
        </span>
        <button type="button" className="btn btn-ghost" onClick={() => void toggle()} disabled={pending || state === null}>
          {pending ? 'Working…' : running ? 'Stop collector' : 'Start collector'}
        </button>
      </div>
      <span className="machine-settings-note">
        Starting issues a new collector credential for this machine and restarts the remote collector.
      </span>
    </section>
  )
}

function CollectorTokenDialog({
  token,
  onClose,
}: {
  token: CollectorToken
  onClose: () => void
}) {
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState(false)

  async function copyToken() {
    setCopyError(false)
    try {
      await navigator.clipboard.writeText(token.value)
      setCopied(true)
    } catch {
      setCopyError(true)
    }
  }

  return (
    <div className="machine-dialog-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose()
    }}>
      <section
        className="machine-token-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="collector-token-title"
        onKeyDown={(event) => {
          if (event.key === 'Escape') onClose()
        }}
      >
        <div className="machine-dialog-heading">
          <div>
            <p className="machine-eyebrow">One-time credential</p>
            <h2 id="collector-token-title">
              {token.action === 'registration' ? 'Collector token for' : 'Rotated collector token for'} {token.hostName}
            </h2>
          </div>
          <button type="button" className="machine-icon-button" onClick={onClose} aria-label="Close token dialog">×</button>
        </div>
        <p className="machine-alert machine-alert-warning">
          {token.action === 'rotation'
            ? 'Copy and store this token securely now. It cannot be retrieved again, and the previous token is no longer valid.'
            : 'Copy and store this token securely now. It cannot be retrieved again after you close this dialog.'}
        </p>
        <div className="machine-token-value">
          <code>{token.value}</code>
          <button type="button" className="btn btn-ghost" onClick={copyToken}>{copied ? 'Copied' : 'Copy token'}</button>
        </div>
        {copyError && <p className="machine-alert machine-alert-error" role="alert">Clipboard access failed. Select and copy the token manually.</p>}
        <details className="machine-setup">
          <summary>Collector setup</summary>
          <CollectorSetupGuide />
        </details>
        <div className="machine-dialog-actions">
          <button type="button" className="btn btn-primary" onClick={onClose}>Done</button>
        </div>
      </section>
    </div>
  )
}

const LOCAL_COLLECTOR_POLL_MS = 15_000

function LocalCollectorControl({ host }: { host: Host }) {
  const [state, setState] = useState<LocalCollectorState | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const isLocal = host.deployment_type === 'localhost'

  useEffect(() => {
    if (!isLocal) return
    const controller = new AbortController()
    const refresh = () =>
      getLocalCollector(host.id, controller.signal)
        .then(setState)
        .catch((requestError: unknown) => {
          if (!controller.signal.aborted) setError(requestFailure(requestError, 'Could not load the local collector status.'))
        })
    void refresh()
    // Polling picks up collectors started or stopped outside the app.
    const timer = window.setInterval(() => void refresh(), LOCAL_COLLECTOR_POLL_MS)
    return () => {
      controller.abort()
      window.clearInterval(timer)
    }
  }, [host.id, isLocal])

  if (!isLocal) return null

  async function toggle() {
    setPending(true)
    setError(null)
    try {
      setState(state?.running ? await stopLocalCollector(host.id) : await startLocalCollector(host.id))
    } catch (requestError) {
      setError(requestFailure(requestError, 'Could not change the local collector. Try again.'))
    } finally {
      setPending(false)
    }
  }

  const external = state?.running === true && state.source === 'external'
  const statusText = (() => {
    if (state === null) return 'Checking collector…'
    if (!state.running) return 'Not running'
    if (external) return state.pid === null ? 'Running outside ServerPulse' : `Running outside ServerPulse (PID ${state.pid})`
    return `Running (PID ${state.pid})`
  })()

  return (
    <section className="machine-panel machine-local-collector" aria-labelledby="local-collector-title">
      <div className="machine-section-heading">
        <div>
          <p className="machine-eyebrow">Local machine</p>
          <h3 id="local-collector-title">Collector process</h3>
        </div>
      </div>
      {error && <p className="machine-alert machine-alert-error" role="alert">{error}</p>}
      <div className="machine-settings-row">
        <span>{statusText}</span>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => void toggle()}
          disabled={pending || state === null || external}
        >
          {pending ? 'Working…' : state?.running ? 'Stop collector' : 'Start collector'}
        </button>
      </div>
      {external ? (
        <span className="machine-settings-note">
          This collector was started outside ServerPulse. Stop it from the terminal running it.
        </span>
      ) : (
        <span className="machine-settings-note">
          Starting issues a new collector credential for this machine and disconnects any other collector using the old one.
        </span>
      )}
    </section>
  )
}

function ProcessHistoryPanel({
  hostId,
  process,
}: {
  hostId: number
  process: SelectedProcess
}) {
  const identity = `${hostId}:${process.pid}:${process.createTime}`
  const [history, setHistory] = useState<{ identity: string; items: ProcessHistoryObservation[] } | null>(null)
  const [historyError, setHistoryError] = useState<{ identity: string; message: string } | null>(null)
  const items = history?.identity === identity ? history.items : null
  const error = historyError?.identity === identity ? historyError.message : null

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    getProcessHistory(hostId, { pid: process.pid, createTime: process.createTime }, controller.signal)
      .then((history) => {
        if (active) setHistory({ identity, items: history })
      })
      .catch((requestError: unknown) => {
        if (active && !controller.signal.aborted) {
          setHistoryError({ identity, message: requestFailure(requestError, 'Could not load process history.') })
        }
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [hostId, process.pid, process.createTime, identity])

  return (
    <section className="machine-history" aria-labelledby="process-history-title">
      <div className="machine-section-heading">
        <div>
          <p className="machine-eyebrow">Process detail · PID {process.pid}</p>
          <h3 id="process-history-title">Recent observations</h3>
        </div>
      </div>
      {error && <p className="machine-alert machine-alert-error" role="alert">{error}</p>}
      {items === null && !error ? (
        <p className="machine-empty-note"><span className="spinner" aria-hidden="true" /> Loading process history…</p>
      ) : items?.length === 0 ? (
        <p className="machine-empty-note">No recent observations for this process identity.</p>
      ) : items && (
        <div className="machine-table-wrap machine-history-table-wrap">
          <table className="machine-table">
            <thead>
              <tr><th>Observed</th><th>CPU</th><th>Memory</th><th>Runtime</th><th>Status</th></tr>
            </thead>
            <tbody>
              {items.map((item, index) => (
                <tr key={`${item.sampled_at}-${index}`}>
                  <td>{formatTime(item.sampled_at)}</td>
                  <td>{formatPercent(item.cpu_percent)}</td>
                  <td>{formatBytes(item.rss_bytes)}</td>
                  <td>{formatRuntime(item.runtime_seconds)}</td>
                  <td>{item.status ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

interface AlertMetricOption {
  metric: AlertMetric
  label: string
  unit: '%' | 'processes'
  defaultThreshold: number
  maxThreshold?: number
  needsProcess: boolean
  linuxOnly?: boolean
}

const ALERT_METRIC_OPTIONS: AlertMetricOption[] = [
  { metric: 'cpu_percent', label: 'CPU usage', unit: '%', defaultThreshold: 90, maxThreshold: 100, needsProcess: false },
  { metric: 'memory_percent', label: 'Memory usage', unit: '%', defaultThreshold: 90, maxThreshold: 100, needsProcess: false },
  { metric: 'long_running_count', label: 'Long-running processes', unit: 'processes', defaultThreshold: 1, needsProcess: false },
  { metric: 'zombie_count', label: 'Zombie processes', unit: 'processes', defaultThreshold: 1, needsProcess: false, linuxOnly: true },
  { metric: 'process_cpu_percent', label: 'Named process CPU', unit: '%', defaultThreshold: 50, needsProcess: true },
  { metric: 'process_memory_percent', label: 'Named process memory', unit: '%', defaultThreshold: 50, maxThreshold: 100, needsProcess: true },
  { metric: 'process_count', label: 'Named process count', unit: 'processes', defaultThreshold: 1, needsProcess: true },
]

interface AlertForm {
  name: string
  metric: AlertMetric
  processName: string
  threshold: string
  sustainedMinutes: string
  enabled: boolean
}

function optionFor(metric: AlertMetric): AlertMetricOption {
  return ALERT_METRIC_OPTIONS.find((option) => option.metric === metric) ?? ALERT_METRIC_OPTIONS[0]
}

function emptyAlertForm(): AlertForm {
  return {
    name: '',
    metric: 'cpu_percent',
    processName: '',
    threshold: String(optionFor('cpu_percent').defaultThreshold),
    sustainedMinutes: '5',
    enabled: true,
  }
}

function alertFormFromRule(rule: AlertRule): AlertForm {
  return {
    name: rule.name,
    metric: rule.metric,
    processName: rule.process_name ?? '',
    threshold: String(rule.threshold),
    sustainedMinutes: String(rule.sustained_minutes),
    enabled: rule.enabled,
  }
}

function alertRuleBody(form: AlertForm): AlertRuleUpsert {
  return {
    name: form.name.trim(),
    metric: form.metric,
    process_name: optionFor(form.metric).needsProcess ? form.processName.trim() : null,
    threshold: Number(form.threshold),
    sustained_minutes: Number(form.sustainedMinutes),
    enabled: form.enabled,
  }
}

function formatAlertValue(value: number, unit: string): string {
  return unit === '%' ? `${value.toFixed(1)}%` : `${value} ${value === 1 ? 'process' : 'processes'}`
}

function describeAlertRule(rule: AlertRule): string {
  const option = optionFor(rule.metric)
  const target = rule.process_name ? ` (${rule.process_name})` : ''
  return `${option.label}${target} at or above ${formatAlertValue(rule.threshold, option.unit)} for ${rule.sustained_minutes} min`
}

function AlertRulesPanel({ host }: { host: Host }) {
  const [rules, setRules] = useState<AlertRule[]>([])
  const [alerts, setAlerts] = useState<MachineAlert[]>([])
  const [form, setForm] = useState<AlertForm>(emptyAlertForm)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const [busyRuleId, setBusyRuleId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const options = ALERT_METRIC_OPTIONS.filter((option) => !option.linuxOnly || host.platform === 'linux')
  const selected = optionFor(form.metric)

  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = async () => {
      try {
        const [nextRules, nextAlerts] = await Promise.all([listAlertRules(host.id), listMachineAlerts(host.id)])
        if (!active) return
        setRules(nextRules)
        setAlerts(nextAlerts)
        setError(null)
      } catch (caught) {
        if (active) setError(requestFailure(caught, 'Could not load alert rules.'))
      } finally {
        if (active) timer = setTimeout(load, POLL_INTERVAL_MS)
      }
    }
    void load()
    return () => {
      active = false
      if (timer) clearTimeout(timer)
    }
  }, [host.id])

  function updateForm(patch: Partial<AlertForm>) {
    setForm((current) => ({ ...current, ...patch }))
  }

  function changeMetric(metric: AlertMetric) {
    updateForm({ metric, threshold: String(optionFor(metric).defaultThreshold) })
  }

  function startEditing(rule: AlertRule) {
    setEditingId(rule.id)
    setForm(alertFormFromRule(rule))
    setError(null)
  }

  function cancelEditing() {
    setEditingId(null)
    setForm(emptyAlertForm())
  }

  async function submitRule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setError(null)
    try {
      if (editingId === null) {
        const created = await createAlertRule(host.id, alertRuleBody(form))
        setRules((current) => [...current, created])
      } else {
        const updated = await updateAlertRule(host.id, editingId, alertRuleBody(form))
        setRules((current) => current.map((rule) => (rule.id === updated.id ? updated : rule)))
      }
      cancelEditing()
    } catch (caught) {
      setError(requestFailure(caught, 'Could not save the alert rule.'))
    } finally {
      setSaving(false)
    }
  }

  async function toggleRule(rule: AlertRule) {
    setBusyRuleId(rule.id)
    setError(null)
    try {
      const updated = await updateAlertRule(host.id, rule.id, alertRuleBody({ ...alertFormFromRule(rule), enabled: !rule.enabled }))
      setRules((current) => current.map((item) => (item.id === updated.id ? updated : item)))
    } catch (caught) {
      setError(requestFailure(caught, 'Could not update the alert rule.'))
    } finally {
      setBusyRuleId(null)
    }
  }

  async function removeRule(rule: AlertRule) {
    if (!window.confirm(`Delete "${rule.name}"? Its alert history will be removed as well.`)) return
    setBusyRuleId(rule.id)
    setError(null)
    try {
      await deleteAlertRule(host.id, rule.id)
      setRules((current) => current.filter((item) => item.id !== rule.id))
      if (editingId === rule.id) cancelEditing()
    } catch (caught) {
      setError(requestFailure(caught, 'Could not delete the alert rule.'))
    } finally {
      setBusyRuleId(null)
    }
  }

  return (
    <section className="machine-panel alert-rules" aria-labelledby="alert-rules-title">
      <div className="machine-section-heading">
        <div>
          <p className="machine-eyebrow">Monitoring</p>
          <h3 id="alert-rules-title">Alert rules</h3>
          <p className="alert-rules-description">Get notified when a machine metric crosses a threshold and stays there.</p>
        </div>
        <span className="alert-rules-count">{rules.length} {rules.length === 1 ? 'rule' : 'rules'}</span>
      </div>
      {error && <p className="machine-alert machine-alert-error" role="alert">{error}</p>}

      <div className="alert-rule-overview" aria-label="Alert rule summary">
        <div className="alert-rule-stat">
          <span className="alert-rule-stat-label">Configured</span>
          <strong>{rules.length}</strong>
        </div>
        <div className="alert-rule-stat">
          <span className="alert-rule-stat-label">Enabled</span>
          <strong>{rules.filter((rule) => rule.enabled).length}</strong>
        </div>
        <div className={`alert-rule-stat${rules.some((rule) => rule.firing) ? ' alert-rule-stat-firing' : ''}`}>
          <span className="alert-rule-stat-label">Firing now</span>
          <strong>{rules.filter((rule) => rule.firing).length}</strong>
        </div>
      </div>

      <div className={`alert-builder${editingId !== null ? ' alert-builder-editing' : ''}`}>
        <div className="alert-builder-heading">
          <div>
            <h4>{editingId === null ? 'Create a rule' : 'Edit rule'}</h4>
            <p>{editingId === null ? 'Choose a metric and decide when it should trigger.' : 'Update the conditions for this rule.'}</p>
          </div>
          <span className="alert-builder-icon" aria-hidden="true">{editingId === null ? '+' : '✎'}</span>
        </div>
        <form className="alert-rule-form" onSubmit={(event) => void submitRule(event)}>
          <label className="machine-field">
            <span>Rule name</span>
            <input
              type="text"
              maxLength={80}
              placeholder="e.g. High CPU usage"
              value={form.name}
              onChange={(event) => updateForm({ name: event.target.value })}
              required
            />
          </label>
          <label className="machine-field">
            <span>Metric</span>
            <select value={form.metric} onChange={(event) => changeMetric(event.target.value as AlertMetric)}>
              {options.map((option) => (
                <option key={option.metric} value={option.metric}>{option.label}</option>
              ))}
            </select>
          </label>
          {selected.needsProcess && (
            <label className="machine-field">
              <span>Process name</span>
              <input
                type="text"
                maxLength={256}
                placeholder="e.g. chrome"
                value={form.processName}
                onChange={(event) => updateForm({ processName: event.target.value })}
                required
              />
            </label>
          )}
          <label className="machine-field">
            <span>Threshold {selected.unit === '%' ? '(%)' : '(processes)'}</span>
            <input
              type="number"
              min={selected.unit === '%' ? '0.1' : '1'}
              max={selected.maxThreshold}
              step={selected.unit === '%' ? '0.1' : '1'}
              value={form.threshold}
              onChange={(event) => updateForm({ threshold: event.target.value })}
              required
            />
          </label>
          <label className="machine-field">
            <span>Sustained (minutes)</span>
            <input
              type="number"
              min="1"
              max="1440"
              step="1"
              value={form.sustainedMinutes}
              onChange={(event) => updateForm({ sustainedMinutes: event.target.value })}
              required
            />
          </label>
          <div className="alert-builder-footer">
            <label className="machine-switch">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(event) => updateForm({ enabled: event.target.checked })}
              />
              <span>Enable this rule</span>
            </label>
            <div className="alert-rule-actions">
              {editingId !== null && (
                <button type="button" className="btn btn-ghost" onClick={cancelEditing} disabled={saving}>
                  Cancel
                </button>
              )}
              <button type="submit" className="btn btn-primary" disabled={saving}>
                {saving ? 'Saving…' : editingId === null ? 'Create alert rule' : 'Save changes'}
              </button>
            </div>
          </div>
        </form>
      </div>

      <div className="alert-rules-list-section">
        <div className="alert-subsection-heading">
          <div>
            <h4>Configured rules</h4>
            <p>Owners receive a bell notification when a rule fires or resolves.</p>
          </div>
          <span>{rules.length}</span>
        </div>
        <ul className="alert-rule-list">
          {rules.length === 0 && (
            <li className="alert-list-empty">
              <span className="alert-empty-mark" aria-hidden="true">!</span>
              <div>
                <strong>No rules configured</strong>
                <p>Create a rule above to start watching this machine.</p>
              </div>
            </li>
          )}
        {rules.map((rule) => {
          const busy = busyRuleId === rule.id
          return (
            <li
              key={rule.id}
              className={`alert-rule-row${editingId === rule.id ? ' alert-rule-editing' : ''}${rule.firing ? ' alert-rule-row-firing' : rule.enabled ? ' alert-rule-row-enabled' : ''}`}
            >
              <div className="alert-rule-indicator" aria-hidden="true" />
              <div className="alert-rule-content">
                <div className="alert-rule-title">
                  <span>{rule.name}</span>
                  <span className={`alert-rule-status${rule.firing ? ' alert-rule-status-firing' : rule.enabled ? ' alert-rule-status-enabled' : ' alert-rule-status-paused'}`}>
                    {rule.firing ? 'Firing' : rule.enabled ? 'Enabled' : 'Paused'}
                  </span>
                </div>
                <p className="alert-rule-summary">{describeAlertRule(rule)}</p>
              </div>
              <div className="alert-rule-actions">
                <label className="machine-switch">
                  <input type="checkbox" checked={rule.enabled} disabled={busy} onChange={() => void toggleRule(rule)} />
                  <span>{rule.enabled ? 'On' : 'Off'}</span>
                </label>
                <button type="button" className="btn btn-ghost alert-rule-action" onClick={() => startEditing(rule)} disabled={busy}>
                  Edit
                </button>
                <button type="button" className="btn btn-ghost alert-rule-action" onClick={() => void removeRule(rule)} disabled={busy}>
                  Delete
                </button>
              </div>
            </li>
          )
        })}
        </ul>
      </div>

      <div className="alert-history">
        <div className="alert-subsection-heading">
          <div>
            <h4>Recent activity</h4>
            <p>The latest alerts raised by this machine.</p>
          </div>
          <span>{alerts.length > 8 ? '8+' : alerts.length}</span>
        </div>
        {alerts.length === 0 ? (
          <div className="alert-history-empty">
            <span aria-hidden="true">✓</span>
            <p>All clear. No alerts have fired for this machine.</p>
          </div>
        ) : (
          <ul className="alert-history-list">
            {alerts.slice(0, 8).map((alert) => {
              const rule = rules.find((item) => item.id === alert.rule_id)
              const option = optionFor(alert.metric)
              return (
                <li key={alert.id} className={`alert-history-item alert-history-${alert.status === 'open' ? 'firing' : 'resolved'}`}>
                  <span className="alert-history-marker" aria-hidden="true" />
                  <div className="alert-history-content">
                    <span className="alert-history-title">{rule?.name ?? option.label}</span>
                    <span className="alert-history-detail">
                      Reached {formatAlertValue(alert.value, option.unit)}
                      {' '}(threshold {formatAlertValue(alert.threshold, option.unit)})
                    </span>
                  </div>
                  <span className="alert-history-status">{alert.status === 'open' ? 'Firing' : 'Resolved'}</span>
                  <time dateTime={alert.triggered_at}>{formatTime(alert.triggered_at)}</time>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </section>
  )
}

const COLLECTOR_COMMAND = `uv run collect-host --url http://127.0.0.1:8000 --state-file collector-state.json --logs`

type DetailTab = 'overview' | 'services' | 'logs' | 'processes' | 'settings'

const DETAIL_TABS: { id: DetailTab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'services', label: 'Services' },
  { id: 'logs', label: 'Logs' },
  { id: 'processes', label: 'Processes' },
  { id: 'settings', label: 'Settings' },
]

function CollectorSetupGuide() {
  return (
    <>
      <ol className="machine-setup-steps">
        <li>
          <strong>Install the backend on the machine.</strong> From the Backend directory, run <code>uv sync</code>.
          Linux and WSL also need Python.
        </li>
        <li>
          <strong>Set the collector token.</strong> Keep it out of shell history and source control:
          <code>set SERVERPULSE_COLLECTOR_TOKEN=&lt;token&gt;</code> on Windows, or
          <code>export SERVERPULSE_COLLECTOR_TOKEN=&lt;token&gt;</code> on Linux. Do not use a user JWT.
        </li>
        <li>
          <strong>Start the collector.</strong> <code>--logs</code> also ships Windows System and Application event logs,
          or systemd journal entries on Linux.
          <pre><code>{COLLECTOR_COMMAND}</code></pre>
        </li>
      </ol>
      <p>Use an HTTPS URL for remote machines. Security-channel events need an elevated collector and are not collected.
        On Linux, the collector user may need the <code>systemd-journal</code> group to read all journal entries.
        Logs are kept for 2 days.</p>
    </>
  )
}

function MachineGrid({
  hosts,
  loading,
  error,
  onSelect,
  onRefresh,
  onCreated,
  onInstalled,
}: {
  hosts: Host[]
  loading: boolean
  error: string | null
  onSelect: (hostId: number) => void
  onRefresh: () => void
  onCreated: (host: Host, token: string) => void
  onInstalled: (host: Host) => void
}) {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<'all' | Connectivity>('all')
  const normalizedQuery = query.trim().toLowerCase()
  const visible = hosts.filter((host) =>
    (status === 'all' || host.connectivity === status) &&
    (normalizedQuery === '' ||
      host.name.toLowerCase().includes(normalizedQuery) ||
      host.platform.includes(normalizedQuery) ||
      host.deployment_type.toLowerCase().includes(normalizedQuery)),
  )
  const onlineCount = hosts.filter((host) => host.connectivity === 'online').length
  const offlineCount = hosts.filter((host) => host.connectivity === 'offline').length

  return (
    <section className="machine-grid-view" aria-labelledby="machine-grid-title">
      <div className="machine-section-heading">
        <div>
          <p className="machine-eyebrow">Host directory</p>
          <h2 id="machine-grid-title">Machines <span>{hosts.length}</span></h2>
          <p className="machine-last-seen">{onlineCount} online · {offlineCount} offline</p>
        </div>
        <button
          type="button"
          className="machine-icon-button"
          aria-label="Refresh machine directory"
          title="Refresh machine directory"
          onClick={onRefresh}
        >↻</button>
      </div>

      {error && <p className="machine-alert machine-alert-error" role="alert">{error}</p>}

      <div className="machine-grid-toolbar">
        <label className="machine-search-field">
          <span className="sr-only">Search machines</span>
          <input
            type="search"
            placeholder="Search by name, platform, or deployment…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <label className="machine-status-filter">
          <span className="sr-only">Filter by status</span>
          <select value={status} onChange={(event) => setStatus(event.target.value as 'all' | Connectivity)}>
            <option value="all">All statuses</option>
            <option value="online">Online</option>
            <option value="offline">Offline</option>
            <option value="never_seen">Never seen</option>
            <option value="disabled">Disabled</option>
          </select>
        </label>
      </div>

      {loading && hosts.length === 0 ? (
        <p className="machine-empty-note"><span className="spinner" aria-hidden="true" /> Loading machines…</p>
      ) : hosts.length === 0 ? (
        !error && <p className="machine-empty-note">No machines are registered yet. Use Add a machine below to register one.</p>
      ) : visible.length === 0 ? (
        <p className="machine-empty-note">No machines match the current search or status filter.</p>
      ) : (
        <ul className="machine-card-grid">
          {visible.map((host) => (
            <li key={host.id}>
              <button type="button" className="machine-card" onClick={() => onSelect(host.id)}>
                <span className="machine-card-top">
                  <strong>{host.name}</strong>
                  <span className={`machine-connectivity ${connectivityClass(host.connectivity)}`}>
                    {connectivityLabel(host.connectivity)}
                  </span>
                </span>
                <span className="machine-card-meta">
                  {host.platform === 'windows' ? 'Windows' : 'Linux'} · {host.deployment_type}
                  {host.wsl_distro ? ` · ${host.wsl_distro}` : ''}
                </span>
                <span className="machine-card-meta">
                  {host.last_heartbeat_at ? `Last heartbeat ${formatTime(host.last_heartbeat_at)}` : 'Never reported'}
                </span>
                {host.metrics_sampled_at ? (
                  <>
                    <MeterRow label="CPU" value={host.cpu_percent} />
                    <MeterRow label="Memory" value={host.memory_percent} />
                  </>
                ) : (
                  <span className="machine-card-meta">No metrics yet</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}

      <details className="machine-collector-help machine-add-panel">
        <summary>Add a machine</summary>
        <HostRegistration onCreated={onCreated} />
        <SSHRegistration onInstalled={onInstalled} />
      </details>
      <details className="machine-collector-help">
        <summary>Collector setup</summary>
        <CollectorSetupGuide />
      </details>
    </section>
  )
}

const LOG_PAGE_SIZE = 50
const LOG_POLL_INTERVAL_MS = 30_000
const LOG_SEVERITY_OPTIONS: { value: LogSeverity | ''; label: string }[] = [
  { value: '', label: 'All severities' },
  { value: 'debug', label: 'Debug and above' },
  { value: 'info', label: 'Info and above' },
  { value: 'warning', label: 'Warning and above' },
  { value: 'error', label: 'Error and above' },
  { value: 'critical', label: 'Critical only' },
]

interface LogFilters {
  sourceId: number | null
  minSeverity: LogSeverity | ''
  keyword: string
  since: string
  until: string
}

function sourceLabel(source: LogSource): string {
  const kind = source.source_type === 'windows_eventlog' ? 'Windows event log' : 'systemd journal'
  return `${kind} · ${source.channel}`
}

function sourceStatus(source: LogSource): string {
  if (source.last_status === 'ok') return 'Collecting'
  if (source.last_status === 'unavailable') return 'Unavailable'
  if (source.last_status === 'error') return 'Error'
  return 'Not collected yet'
}

function localDateTimeToIso(value: string): string | null {
  if (!value) return null
  const time = new Date(value)
  return Number.isNaN(time.getTime()) ? null : time.toISOString()
}

const SERVICE_STATE_TITLES: Record<HostService['current_state'], string> = {
  running: 'Running',
  stopped: 'Stopped',
  failed: 'Failed',
  paused: 'Paused',
  transitional: 'Transitioning',
  unknown: 'Not reported',
}

const SERVICE_SUMMARY_ORDER: HostService['current_state'][] = ['running', 'stopped', 'failed', 'paused', 'transitional', 'unknown']

const SERVICE_PAGE_SIZE = 25

type ServiceSort = 'name' | 'state' | 'checked' | 'logs'

const SERVICE_SORT_TITLES: Record<ServiceSort, string> = {
  name: 'Name (A–Z)',
  state: 'State',
  checked: 'Last checked (newest first)',
  logs: 'Logs (most first)',
}

function serviceLabel(service: HostService): string {
  return service.display_name ?? service.service_name
}

function compareServices(sort: ServiceSort, a: HostService, b: HostService): number {
  const byName = serviceLabel(a).localeCompare(serviceLabel(b), undefined, { sensitivity: 'base' })
  if (sort === 'state') {
    return SERVICE_SUMMARY_ORDER.indexOf(a.current_state) - SERVICE_SUMMARY_ORDER.indexOf(b.current_state) || byName
  }
  if (sort === 'checked') {
    const checkedA = a.last_checked_at ? Date.parse(a.last_checked_at) : 0
    const checkedB = b.last_checked_at ? Date.parse(b.last_checked_at) : 0
    return checkedB - checkedA || byName
  }
  if (sort === 'logs') return b.log_count - a.log_count || byName
  return byName
}


function ServicesPanel({ host }: { host: Host }) {
  const [services, setServices] = useState<HostService[] | null>(null)
  const [servicesError, setServicesError] = useState<string | null>(null)
  const [stateFilter, setStateFilter] = useState<HostService['current_state'] | null>(null)
  const [sort, setSort] = useState<ServiceSort>('name')
  const [page, setPage] = useState(1)

  const visibleServices = useMemo(() => {
    if (!services) return []
    const filtered = stateFilter ? services.filter((service) => service.current_state === stateFilter) : services
    return [...filtered].sort((a, b) => compareServices(sort, a, b))
  }, [services, stateFilter, sort])
  const pageCount = Math.max(1, Math.ceil(visibleServices.length / SERVICE_PAGE_SIZE))
  const pageNumber = Math.min(page, pageCount)
  const pageServices = visibleServices.slice((pageNumber - 1) * SERVICE_PAGE_SIZE, pageNumber * SERVICE_PAGE_SIZE)

  useEffect(() => {
    const controller = new AbortController()
    getHostServices(host.id, controller.signal)
      .then((items) => {
        setServices(items)
        setServicesError(null)
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setServicesError(requestFailure(error, 'Could not load services.'))
      })
    return () => controller.abort()
  }, [host.id])

  return (
    <section className="machine-panel machine-services" aria-labelledby="services-title">
      <div className="machine-section-heading">
        <div>
          <p className="machine-eyebrow">Windows Services and systemd units</p>
          <h3 id="services-title">Services</h3>
        </div>
        <span className="machine-process-total">{services ? `${services.length} found` : 'Loading…'}</span>
      </div>
      {servicesError && <p className="machine-error" role="alert">{servicesError}</p>}
      {services && services.length === 0 && (
        <p className="machine-empty">No services found yet. Services appear after the collector reports its service inventory.</p>
      )}
      {services && services.length > 0 && (
        <>
          <div className="machine-service-toolbar">
            <div className="machine-service-summary" role="group" aria-label="Filter services by state">
              {SERVICE_SUMMARY_ORDER.map((state) => {
                const count = services.filter((service) => service.current_state === state).length
                const active = stateFilter === state
                return (
                  <button
                    key={state}
                    type="button"
                    aria-pressed={active}
                    disabled={count === 0 && !active}
                    onClick={() => {
                      setStateFilter(active ? null : state)
                      setPage(1)
                    }}
                    className={`machine-service-count machine-service-pill-${state}${active ? ' is-active' : ''}`}
                  >
                    <strong>{count}</strong>
                    {SERVICE_STATE_TITLES[state]}
                  </button>
                )
              })}
            </div>
            <label className="machine-service-sort">
              <span>Sort by</span>
              <select value={sort} onChange={(event) => {
                setSort(event.target.value as ServiceSort)
                setPage(1)
              }}>
                {(Object.keys(SERVICE_SORT_TITLES) as ServiceSort[]).map((key) => (
                  <option key={key} value={key}>{SERVICE_SORT_TITLES[key]}</option>
                ))}
              </select>
            </label>
          </div>
          {stateFilter && (
            <p className="machine-service-filter-note">
              Showing {visibleServices.length} {SERVICE_STATE_TITLES[stateFilter].toLowerCase()} of {services.length} services.{' '}
              <button type="button" className="machine-service-clear" onClick={() => {
                setStateFilter(null)
                setPage(1)
              }}>Show all</button>
            </p>
          )}
          <div className="machine-table-wrap" role="region" aria-label="Service table" tabIndex={0}>
            <table className="machine-table machine-service-table">
              <thead>
                <tr>
                  <th scope="col">Service</th>
                  <th scope="col">State</th>
                  <th scope="col">Native state</th>
                  <th scope="col">Last checked</th>
                  <th scope="col" className="machine-table-number">Logs</th>
                </tr>
              </thead>
              <tbody>
                {visibleServices.length === 0 && (
                  <tr><td colSpan={5} className="machine-table-empty">No services match this filter.</td></tr>
                )}
                {pageServices.map((service) => (
                  <tr key={service.id}>
                    <td>
                      <span className="machine-service-title">{service.display_name ?? service.service_name}</span>
                      {service.display_name && <span className="machine-service-subtitle">{service.service_name}</span>}
                    </td>
                    <td>
                      <span className={`machine-service-pill machine-service-pill-${service.current_state}`}>
                        {SERVICE_STATE_TITLES[service.current_state]}
                      </span>
                    </td>
                    <td className="machine-service-muted">{service.native_state ?? '—'}</td>
                    <td className="machine-service-muted">
                      {service.last_checked_at ? formatTime(service.last_checked_at) : 'Never'}
                      {service.last_error && <span className="machine-service-error" title={service.last_error}>Error</span>}
                    </td>
                    <td className="machine-table-number">
                      {host.platform === 'windows' && service.log_count === 0 ? (
                        <span
                          className="machine-service-muted"
                          title="Windows log events link only through Service Control Manager events. None are linked to this service yet."
                        >
                          n/a
                        </span>
                      ) : (
                        service.log_count.toLocaleString()
                      )}
                      {service.last_log_at && <span className="machine-service-subtitle">last {formatTime(service.last_log_at)}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <footer className="machine-pagination">
            <span>
              {visibleServices.length > 0
                ? `${(pageNumber - 1) * SERVICE_PAGE_SIZE + 1}–${Math.min(pageNumber * SERVICE_PAGE_SIZE, visibleServices.length)} of ${visibleServices.length}`
                : '0 services'}
            </span>
            <div>
              <button type="button" className="btn btn-ghost" disabled={pageNumber <= 1} onClick={() => setPage(pageNumber - 1)}>
                Previous
              </button>
              <span aria-live="polite">Page {pageNumber} of {pageCount}</span>
              <button type="button" className="btn btn-ghost" disabled={pageNumber >= pageCount} onClick={() => setPage(pageNumber + 1)}>
                Next
              </button>
            </div>
          </footer>
        </>
      )}

    </section>
  )
}

const LOG_PREVIEW_CHARS = 160

function LogRow({ event }: { event: LogPage['items'][number] }) {
  const [expanded, setExpanded] = useState(false)
  const firstLine = event.message.split('\n')[0]
  const isLong = event.message.length > LOG_PREVIEW_CHARS || firstLine.length < event.message.length
  const preview = isLong
    ? `${firstLine.slice(0, LOG_PREVIEW_CHARS).trimEnd()}…`
    : event.message

  return (
    <li className={`log-row log-row-${event.severity}`}>
      <div className="log-meta">
        <time dateTime={event.occurred_at}>
          {formatTime(event.occurred_at)}
          {event.timestamp_quality === 'fallback' ? ' (collector time)' : ''}
        </time>
        <span className={`log-severity log-severity-${event.severity}`}>{event.severity}</span>
      </div>
      <div className="log-body">
        <span className="log-source">
          {event.channel}
          {event.service_name ? ` · ${event.service_name}` : ''}
          {event.provider ? ` · ${event.provider}` : ''}
          {event.event_id !== null ? ` · event ${event.event_id}` : ''}
        </span>
        {expanded ? (
          <pre className="log-message-full">{event.message}</pre>
        ) : (
          <span className="log-message">{preview}</span>
        )}
        {isLong && (
          <button
            type="button"
            className="log-toggle"
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? 'Show less' : 'Show full message'}
          </button>
        )}
      </div>
    </li>
  )
}

function LogViewer({ host }: { host: Host }) {
  const [sources, setSources] = useState<LogSource[]>([])
  const [sourcesError, setSourcesError] = useState<string | null>(null)
  const [filters, setFilters] = useState<LogFilters>({ sourceId: null, minSeverity: '', keyword: '', since: '', until: '' })
  const [keywordDraft, setKeywordDraft] = useState('')
  const [offset, setOffset] = useState(0)
  const [page, setPage] = useState<{ key: string; data: LogPage } | null>(null)
  const [logError, setLogError] = useState<string | null>(null)
  const [refresh, setRefresh] = useState(0)

  const sinceIso = localDateTimeToIso(filters.since)
  const untilIso = localDateTimeToIso(filters.until)
  const query = useMemo<LogQuery>(() => ({
    sourceId: filters.sourceId,
    minSeverity: filters.minSeverity,
    since: sinceIso,
    until: untilIso,
    keyword: filters.keyword,
    offset,
    limit: LOG_PAGE_SIZE,
  }), [filters, sinceIso, untilIso, offset])
  const queryKey = JSON.stringify(query)
  const currentPage = page?.key === queryKey ? page.data : null
  const pageCount = Math.max(1, Math.ceil((currentPage?.total ?? 0) / LOG_PAGE_SIZE))
  const pageNumber = Math.floor(offset / LOG_PAGE_SIZE) + 1

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    let timer: ReturnType<typeof setTimeout> | undefined

    const load = async () => {
      const [sourceResult, logResult] = await Promise.allSettled([
        getLogSources(host.id, controller.signal),
        getLogs(host.id, query, controller.signal),
      ])
      if (!active) return
      if (sourceResult.status === 'fulfilled') {
        setSources(sourceResult.value)
        setSourcesError(null)
      } else if (!controller.signal.aborted) {
        setSourcesError(requestFailure(sourceResult.reason, 'Could not load log sources.'))
      }
      if (logResult.status === 'fulfilled') {
        setPage({ key: queryKey, data: logResult.value })
        setLogError(null)
      } else if (!controller.signal.aborted) {
        setLogError(requestFailure(logResult.reason, 'Could not load logs; showing the last successful result.'))
      }
      if (active) timer = setTimeout(load, LOG_POLL_INTERVAL_MS)
    }

    void load()
    return () => {
      active = false
      controller.abort()
      if (timer) clearTimeout(timer)
    }
  }, [host.id, query, queryKey, refresh])

  function updateFilters(patch: Partial<LogFilters>) {
    setFilters((current) => ({ ...current, ...patch }))
    setOffset(0)
  }

  function submitKeyword(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    updateFilters({ keyword: keywordDraft.trim() })
  }

  return (
    <section className="machine-panel log-viewer" aria-labelledby="logs-title">
      <div className="machine-section-heading">
        <div>
          <p className="machine-eyebrow">Collected logs · 2-day retention</p>
          <h3 id="logs-title">Logs</h3>
        </div>
        <button
          type="button"
          className="machine-icon-button"
          aria-label="Refresh logs"
          title="Refresh logs"
          onClick={() => setRefresh((value) => value + 1)}
        >↻</button>
      </div>

      {sources.length > 0 && (
        <ul className="log-source-status" aria-label="Log source status">
          {sources.map((source) => (
            <li key={source.id} title={source.last_error ?? undefined}>
              <span className={`log-status-dot log-status-${source.last_status ?? 'none'}`} aria-hidden="true" />
              {sourceLabel(source)} · {sourceStatus(source)}
            </li>
          ))}
        </ul>
      )}
      {sourcesError && <p className="machine-alert machine-alert-error" role="alert">{sourcesError}</p>}
      {logError && <p className="machine-alert machine-alert-warning" role="status">{logError}</p>}

      <div className="log-filters">
        <label>
          <span>Source</span>
          <select value={filters.sourceId ?? ''} onChange={(event) => updateFilters({ sourceId: event.target.value ? Number(event.target.value) : null })}>
            <option value="">All sources</option>
            {sources.map((source) => (
              <option key={source.id} value={source.id}>{sourceLabel(source)}</option>
            ))}
          </select>
        </label>
        <label>
          <span>Minimum severity</span>
          <select value={filters.minSeverity} onChange={(event) => updateFilters({ minSeverity: event.target.value as LogSeverity | '' })}>
            {LOG_SEVERITY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        <label>
          <span>From</span>
          <input type="datetime-local" value={filters.since} onChange={(event) => updateFilters({ since: event.target.value })} />
        </label>
        <label>
          <span>To</span>
          <input type="datetime-local" value={filters.until} onChange={(event) => updateFilters({ until: event.target.value })} />
        </label>
        <form className="log-keyword" onSubmit={submitKeyword}>
          <label>
            <span>Keyword</span>
            <input type="search" value={keywordDraft} onChange={(event) => setKeywordDraft(event.target.value)} placeholder="Search messages" />
          </label>
          <button type="submit" className="btn btn-ghost">Search</button>
        </form>
      </div>

      {!currentPage ? (
        <p className="machine-empty-note"><span className="spinner" aria-hidden="true" /> Loading logs…</p>
      ) : currentPage.items.length === 0 ? (
        <p className="machine-empty-note">
          {sources.length === 0
            ? 'No log sources have reported yet. Start the collector with --logs to collect event logs.'
            : 'No log events match these filters.'}
        </p>
      ) : (
        <ol className="log-list" aria-label="Log events">
          {currentPage.items.map((event) => (
            <LogRow key={event.id} event={event} />
          ))}
        </ol>
      )}

      <div className="machine-pagination">
        <span>Page {pageNumber} of {pageCount} · {(currentPage?.total ?? 0).toLocaleString()} events</span>
        <div>
          <button type="button" className="btn btn-ghost" disabled={offset === 0} onClick={() => setOffset((value) => Math.max(0, value - LOG_PAGE_SIZE))}>
            Previous
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={pageNumber >= pageCount}
            onClick={() => setOffset((value) => value + LOG_PAGE_SIZE)}
          >
            Next
          </button>
        </div>
      </div>
    </section>
  )
}

export function MachinesMonitoring() {
  const [hosts, setHosts] = useState<HostCollection>({ items: [], loading: true, error: null })
  const [selectedHostId, setSelectedHostId] = useState<number | null>(null)
  const [detailTab, setDetailTab] = useState<DetailTab>('overview')
  const [hostRefresh, setHostRefresh] = useState(0)
  const [monitoring, setMonitoring] = useState<MonitoringCollection | null>(null)
  const [metrics, setMetrics] = useState<MetricsCollection | null>(null)
  const [processes, setProcesses] = useState<ProcessCollection | null>(null)
  const [monitorError, setMonitorError] = useState<string | null>(null)
  const [metricsError, setMetricsError] = useState<string | null>(null)
  const [processError, setProcessError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [longRunningOnly, setLongRunningOnly] = useState(false)
  const [zombiesOnly, setZombiesOnly] = useState(false)
  const [sort, setSort] = useState<'cpu' | 'memory' | 'runtime' | 'name'>('cpu')
  const [offset, setOffset] = useState(0)
  const [selectedProcess, setSelectedProcess] = useState<SelectedProcess | null>(null)
  const [collectorToken, setCollectorToken] = useState<CollectorToken | null>(null)
  const [hostActionError, setHostActionError] = useState<string | null>(null)
  const [hostActionPending, setHostActionPending] = useState(false)
  const [thresholdValue, setThresholdValue] = useState<{ hostId: number; value: string } | null>(null)
  const [thresholdSaving, setThresholdSaving] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    let timer: ReturnType<typeof setTimeout> | undefined

    const loadHosts = async () => {
      try {
        const items = await listHosts(controller.signal)
        if (!active) return
        setHosts({ items, loading: false, error: null })
        setSelectedHostId((current) =>
          current !== null && items.some((host) => host.id === current) ? current : null,
        )
      } catch (error) {
        if (!active || controller.signal.aborted) return
        setHosts((current) => ({
          ...current,
          loading: false,
          error: requestFailure(error, current.items.length > 0
            ? 'Could not refresh the machine directory; showing the last successful result.'
            : 'Could not load the machine directory. Check the API connection and try again.'),
        }))
      } finally {
        if (active) timer = setTimeout(loadHosts, POLL_INTERVAL_MS)
      }
    }

    void loadHosts()
    return () => {
      active = false
      controller.abort()
      if (timer) clearTimeout(timer)
    }
  }, [hostRefresh])

  const selectedHost = hosts.items.find((host) => host.id === selectedHostId) ?? null
  const selectedPlatform = selectedHost?.platform ?? null
  const thresholdDraft =
    selectedHost && thresholdValue?.hostId === selectedHost.id
      ? thresholdValue.value
      : selectedHost
        ? String(selectedHost.long_running_seconds)
        : ''
  const processKey = `${selectedHostId ?? ''}|${search}|${longRunningOnly}|${zombiesOnly}|${sort}|${offset}`
  const currentMonitoring = monitoring?.hostId === selectedHostId ? monitoring.latest : null
  const hasMonitoring = monitoring?.hostId === selectedHostId
  const hasMetrics = metrics?.hostId === selectedHostId
  const currentMetrics = metrics?.hostId === selectedHostId ? metrics.items : []
  const currentProcesses = processes?.key === processKey ? processes.data : null

  useEffect(() => {
    if (selectedHostId === null) {
      setMonitoring(null)
      setMetrics(null)
      setProcesses(null)
      setMonitorError(null)
      setMetricsError(null)
      setProcessError(null)
      return
    }
    const controller = new AbortController()
    let active = true
    let timer: ReturnType<typeof setTimeout> | undefined

    const loadSnapshot = async () => {
      const processOptions = {
        offset,
        limit: PROCESS_PAGE_SIZE,
        search,
        longRunning: longRunningOnly,
        zombie: zombiesOnly && selectedPlatform === 'linux',
        sort,
      }
      const results = await Promise.allSettled([
        getMonitoring(selectedHostId, controller.signal),
        getMetrics(selectedHostId, controller.signal),
        getProcesses(selectedHostId, processOptions, controller.signal),
      ])
      if (!active) return
      const [monitorResult, metricResult, processResult] = results

      if (monitorResult.status === 'fulfilled') {
        setMonitoring({ hostId: selectedHostId, latest: monitorResult.value.latest })
        setMonitorError(null)
        setHosts((current) => ({
          ...current,
          items: current.items.map((host) => host.id === monitorResult.value.host.id ? monitorResult.value.host : host),
        }))
      } else if (!controller.signal.aborted) {
        setMonitorError(requestFailure(monitorResult.reason, 'Could not refresh the latest snapshot; showing the last successful result.'))
      }

      if (metricResult.status === 'fulfilled') {
        setMetrics({ hostId: selectedHostId, items: metricResult.value })
        setMetricsError(null)
      } else if (!controller.signal.aborted) {
        setMetricsError(requestFailure(metricResult.reason, 'Could not refresh metric history; showing the last successful result.'))
      }

      if (processResult.status === 'fulfilled') {
        setProcesses({ key: processKey, data: processResult.value })
        setProcessError(null)
      } else if (!controller.signal.aborted) {
        setProcessError(requestFailure(processResult.reason, 'Could not refresh the process list; showing the last successful result.'))
      }
      if (active) timer = setTimeout(loadSnapshot, POLL_INTERVAL_MS)
    }

    void loadSnapshot()
    return () => {
      active = false
      controller.abort()
      if (timer) clearTimeout(timer)
    }
  }, [selectedHostId, selectedPlatform, processKey, offset, search, longRunningOnly, zombiesOnly, sort])

  const sampleTime = currentMonitoring ? new Date(currentMonitoring.sampled_at).getTime() : null
  const snapshotIsStale =
    sampleTime !== null &&
    (Number.isNaN(sampleTime) || Date.now() - sampleTime > POLL_INTERVAL_MS * 3)
  const hasRefreshError = !!(monitorError || metricsError || processError)
  const visibleProcesses = currentProcesses?.items ?? []
  const totalProcesses = currentProcesses?.total ?? 0
  const pageNumber = Math.floor(offset / PROCESS_PAGE_SIZE) + 1
  const pageCount = Math.max(1, Math.ceil(totalProcesses / PROCESS_PAGE_SIZE))
  const partialVisibility =
    (currentMonitoring?.denied_count ?? 0) > 0 ||
    (currentMonitoring?.vanished_count ?? 0) > 0 ||
    visibleProcesses.some((process) => process.access_denied)

  const processHistorySelection =
    selectedProcess?.hostId === selectedHostId &&
    visibleProcesses.some(
      (process) => process.pid === selectedProcess.pid && process.create_time === selectedProcess.createTime,
    )
      ? selectedProcess
      : null

  function handleCreated(host: Host, token: string) {
    setCollectorToken({ hostName: host.name, value: token, action: 'registration' })
    handleInstalled(host)
  }

  function handleInstalled(host: Host) {
    setHosts((current) => ({
      ...current,
      items: [...current.items.filter((item) => item.id !== host.id), host],
      error: null,
    }))
    setSelectedHostId(host.id)
    setOffset(0)
    setSelectedProcess(null)
    setHostRefresh((value) => value + 1)
  }

  async function saveThreshold(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedHost) return
    const value = Number(thresholdDraft)
    if (!Number.isInteger(value) || value < 1) {
      setHostActionError('Enter a whole number of seconds greater than zero.')
      return
    }
    setThresholdSaving(true)
    setHostActionError(null)
    try {
      const updated = await updateHost(selectedHost.id, { long_running_seconds: value })
      setHosts((current) => ({ ...current, items: current.items.map((host) => host.id === updated.id ? updated : host) }))
    } catch (error) {
      setHostActionError(requestFailure(error, 'Could not update the machine settings. Try again.'))
    } finally {
      setThresholdSaving(false)
    }
  }

  async function changeEnabled(enabled: boolean) {
    if (!selectedHost) return
    setHostActionPending(true)
    setHostActionError(null)
    try {
      const updated = await updateHost(selectedHost.id, { enabled })
      setHosts((current) => ({ ...current, items: current.items.map((host) => host.id === updated.id ? updated : host) }))
    } catch (error) {
      setHostActionError(requestFailure(error, 'Could not update the machine settings. Try again.'))
    } finally {
      setHostActionPending(false)
    }
  }

  async function rotateToken() {
    if (!selectedHost) return
    setHostActionPending(true)
    setHostActionError(null)
    try {
      const response = await rotateCollectorToken(selectedHost.id)
      setHosts((current) => ({
        ...current,
        items: current.items.map((host) => host.id === response.host.id ? response.host : host),
      }))
      setCollectorToken({ hostName: response.host.name, value: response.collector_token, action: 'rotation' })
    } catch (error) {
      setHostActionError(requestFailure(error, 'Could not rotate the collector token. Try again.'))
    } finally {
      setHostActionPending(false)
    }
  }

  function updateProcessFilters(change: () => void) {
    change()
    setOffset(0)
    setSelectedProcess(null)
  }

  function openHost(hostId: number | null) {
    setSelectedHostId(hostId)
    setDetailTab('overview')
    setOffset(0)
    setSelectedProcess(null)
  }

  return (
    <div className="machines-view">
      <section className="machine-detail">
        {!selectedHost ? (
          <MachineGrid
            hosts={hosts.items}
            loading={hosts.loading}
            error={hosts.error}
            onSelect={openHost}
            onRefresh={() => setHostRefresh((value) => value + 1)}
            onCreated={handleCreated}
            onInstalled={handleInstalled}
          />
        ) : (
          <>
            <button type="button" className="btn btn-ghost machine-back" onClick={() => openHost(null)}>
              ← All machines
            </button>
            <header className="machine-detail-header">
              <div>
                <p className="machine-eyebrow">{selectedHost.platform} / {selectedHost.deployment_type}{selectedHost.wsl_distro ? ` / ${selectedHost.wsl_distro}` : ''}</p>
                <h2>{selectedHost.name}</h2>
                <p className="machine-last-seen">
                  Snapshot {currentMonitoring ? formatTime(currentMonitoring.sampled_at) : 'not collected'}
                  <span aria-hidden="true"> · </span>
                  {formatRelativeTime(currentMonitoring?.sampled_at)}
                </p>
              </div>
              <div className="machine-detail-status">
                <span className={`machine-connectivity ${connectivityClass(selectedHost.connectivity)}`}>
                  {connectivityLabel(selectedHost.connectivity)}
                </span>
                {snapshotIsStale && <span className="machine-connectivity machine-status-stale">Snapshot stale</span>}
                {hasRefreshError && <span className="machine-connectivity machine-status-stale">Refresh issue</span>}
              </div>
            </header>

            {monitorError && <p className="machine-alert machine-alert-error" role="status">{monitorError}</p>}
            {metricsError && <p className="machine-alert machine-alert-warning" role="status">{metricsError}</p>}
            {processError && <p className="machine-alert machine-alert-warning" role="status">{processError}</p>}
            {hosts.error && <p className="machine-alert machine-alert-warning" role="status">{hosts.error}</p>}

            <div className="machine-tabs" role="tablist" aria-label="Machine details">
              {DETAIL_TABS.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  id={`machine-tab-${tab.id}`}
                  aria-selected={detailTab === tab.id}
                  aria-controls="machine-tabpanel"
                  className={`machine-tab${detailTab === tab.id ? ' machine-tab-active' : ''}`}
                  onClick={() => setDetailTab(tab.id)}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            <div className="machine-tabpanel" role="tabpanel" id="machine-tabpanel" aria-labelledby={`machine-tab-${detailTab}`}>
            {detailTab === 'overview' && (<>
            <section className="machine-resource-grid" aria-label="Latest resources">
              <article className="machine-resource">
                <span className="machine-resource-label">CPU utilization</span>
                <strong>{currentMonitoring ? formatPercent(currentMonitoring.cpu_percent) : '—'}</strong>
                <span className="machine-resource-detail">Latest collected sample</span>
              </article>
              <article className="machine-resource">
                <span className="machine-resource-label">Memory utilization</span>
                <strong>{currentMonitoring ? formatPercent(currentMonitoring.memory_percent) : '—'}</strong>
                <span className="machine-resource-detail">
                  {currentMonitoring ? `${formatBytes(currentMonitoring.memory_used_bytes)} used of ${formatBytes(currentMonitoring.memory_total_bytes)}` : 'No sample collected'}
                </span>
              </article>
              <article className="machine-resource">
                <span className="machine-resource-label">Memory available</span>
                <strong>{currentMonitoring ? formatBytes(currentMonitoring.memory_available_bytes) : '—'}</strong>
                <span className="machine-resource-detail">Reported by host collector</span>
              </article>
              <article className="machine-resource">
                <span className="machine-resource-label">Processes</span>
                <strong>{currentMonitoring ? currentMonitoring.process_count.toLocaleString() : '—'}</strong>
                <span className="machine-resource-detail">
                  {currentMonitoring
                    ? `${currentMonitoring.long_running_count} long-running · ${selectedHost.platform === 'linux' ? `${currentMonitoring.zombie_count ?? '—'} zombies` : 'zombies not applicable'}`
                    : 'No sample collected'}
                </span>
              </article>
            </section>

            {!hasMonitoring ? (
              <div className="machine-empty-panel machine-no-sample">
                {monitorError ? (
                  <><strong>Snapshot unavailable</strong><span>{monitorError}</span></>
                ) : (
                  <><span className="spinner" aria-hidden="true" /><span>Loading the latest snapshot…</span></>
                )}
              </div>
            ) : currentMonitoring === null ? (
              <div className="machine-empty-panel machine-no-sample">
                <strong>{monitorError ? 'Snapshot unavailable' : 'No sample collected yet'}</strong>
                <span>This machine has not reported resource or process data. Values are unknown, not zero.</span>
              </div>
            ) : null}

            <section className="machine-panel" aria-labelledby="resource-history-title">
              <div className="machine-section-heading">
                <div>
                  <p className="machine-eyebrow">Collected history</p>
                  <h3 id="resource-history-title">Resource trend</h3>
                </div>
                <span className="machine-retention">10-second refresh · up to 24 hours retained</span>
              </div>
              {hasMetrics ? (
                <MetricChart samples={currentMetrics} />
              ) : metricsError ? (
                <p className="machine-empty-note">{metricsError}</p>
              ) : (
                <p className="machine-empty-note"><span className="spinner" aria-hidden="true" /> Loading metric history…</p>
              )}
            </section>

            </>)}

            {detailTab === 'services' && <ServicesPanel key={`services-${selectedHost.id}`} host={selectedHost} />}

            {detailTab === 'settings' && (<>
            <LocalCollectorControl key={selectedHost.id} host={selectedHost} />
            <SSHCollectorControl key={`ssh-${selectedHost.id}`} host={selectedHost} />

            <AlertRulesPanel key={`alerts-${selectedHost.id}`} host={selectedHost} />

            <section className="machine-panel machine-settings" aria-labelledby="machine-settings-title">
                <div className="machine-section-heading">
                  <div>
                    <p className="machine-eyebrow">Owner controls</p>
                    <h3 id="machine-settings-title">Machine settings</h3>
                  </div>
                </div>
                {hostActionError && <p className="machine-alert machine-alert-error" role="alert">{hostActionError}</p>}
                <div className="machine-settings-row">
                  <label className="machine-switch">
                    <input
                      type="checkbox"
                      checked={selectedHost.enabled}
                      disabled={hostActionPending}
                      onChange={(event) => void changeEnabled(event.target.checked)}
                    />
                    <span>Monitoring enabled</span>
                  </label>
                  <span className="machine-settings-note">Threshold edits take effect on the next snapshot.</span>
                </div>
                <form className="machine-threshold-form" onSubmit={(event) => void saveThreshold(event)}>
                  <label className="machine-field">
                    <span>Long-running threshold (seconds)</span>
                    <input
                      type="number"
                      min="1"
                      step="1"
                      value={thresholdDraft}
                      onChange={(event) => setThresholdValue({ hostId: selectedHost.id, value: event.target.value })}
                      required
                    />
                  </label>
                  <button type="submit" className="btn btn-ghost" disabled={thresholdSaving}>
                    {thresholdSaving ? 'Saving…' : 'Save threshold'}
                  </button>
                </form>
                <div className="machine-rotate-row">
                  <p>Rotate the collector credential if it has been exposed or lost.</p>
                  <button type="button" className="btn btn-ghost" onClick={() => void rotateToken()} disabled={hostActionPending}>
                    {hostActionPending ? 'Working…' : 'Rotate collector token'}
                  </button>
                </div>
              </section>
            </>)}

            {detailTab === 'logs' && <LogViewer key={`logs-${selectedHost.id}`} host={selectedHost} />}

            {detailTab === 'processes' && (<>
            {partialVisibility && (
              <p className="machine-alert machine-alert-warning" role="status">
                Partial process visibility: {currentMonitoring?.denied_count ?? '—'} permission-denied and {currentMonitoring?.vanished_count ?? '—'} vanished during collection. Some processes may be missing.
              </p>
            )}

            <section className="machine-panel machine-processes" aria-labelledby="processes-title">
              <div className="machine-section-heading">
                <div>
                  <p className="machine-eyebrow">Snapshot {currentProcesses?.sampled_at ? `· ${formatTime(currentProcesses.sampled_at)}` : ''}</p>
                  <h3 id="processes-title">Processes</h3>
                </div>
                <span className="machine-process-total">{currentProcesses ? `${totalProcesses.toLocaleString()} matching` : 'Loading…'}</span>
              </div>
              <p className="machine-process-visibility">
                Collection visibility · <strong>{currentMonitoring?.denied_count ?? '—'}</strong> permission-denied
                <span aria-hidden="true"> · </span>
                <strong>{currentMonitoring?.vanished_count ?? '—'}</strong> vanished
              </p>
              <div className="machine-process-filters">
                <label className="machine-search-field">
                  <span className="sr-only">Filter processes by keyword</span>
                  <input
                    type="search"
                    placeholder="Filter processes…"
                    value={search}
                    onChange={(event) => updateProcessFilters(() => setSearch(event.target.value))}
                  />
                </label>
                <label className="machine-check-filter">
                  <input
                    type="checkbox"
                    checked={longRunningOnly}
                    onChange={(event) => updateProcessFilters(() => setLongRunningOnly(event.target.checked))}
                  />
                  Long-running
                </label>
                {selectedHost.platform === 'linux' && (
                  <label className="machine-check-filter">
                    <input
                      type="checkbox"
                      checked={zombiesOnly}
                      onChange={(event) => updateProcessFilters(() => setZombiesOnly(event.target.checked))}
                    />
                    Zombies
                  </label>
                )}
                <label className="machine-sort-field">
                  <span>Sort by</span>
                  <select
                    value={sort}
                    onChange={(event) => updateProcessFilters(() => setSort(event.target.value as typeof sort))}
                  >
                    <option value="cpu">CPU</option>
                    <option value="memory">Memory</option>
                    <option value="runtime">Runtime</option>
                    <option value="name">Name</option>
                  </select>
                </label>
              </div>
              <p className="machine-scroll-cue" id="process-scroll-cue">Scroll horizontally to see all process columns <span aria-hidden="true">↔</span></p>
              <div className="machine-table-wrap" role="region" aria-label="Process table" aria-describedby="process-scroll-cue" tabIndex={0}>
                <table className="machine-table">
                  <thead>
                    <tr>
                      <th scope="col">PID</th>
                      <th scope="col">Process</th>
                      <th scope="col">Status</th>
                      <th scope="col">CPU</th>
                      <th scope="col">RSS memory</th>
                      <th scope="col">Memory</th>
                      <th scope="col">Runtime</th>
                      <th scope="col">Long-running</th>
                      {selectedHost.platform === 'linux' && <th scope="col">Zombie</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {visibleProcesses.map((process: ProcessObservation) => {
                      const hasIdentity = process.create_time !== null
                      const isSelected =
                        selectedProcess?.hostId === selectedHost.id &&
                        selectedProcess.pid === process.pid &&
                        selectedProcess.createTime === process.create_time
                      return (
                        <tr
                          key={`${process.pid}-${process.create_time ?? 'unknown'}`}
                          className={isSelected ? 'machine-process-selected' : ''}
                        >
                          <td>
                            {hasIdentity ? (
                              <button
                                type="button"
                                className="machine-pid-link"
                                aria-label={`View history for process ${process.name ?? process.pid}, PID ${process.pid}`}
                                aria-pressed={isSelected}
                                onClick={() => setSelectedProcess(isSelected ? null : {
                                  hostId: selectedHost.id,
                                  pid: process.pid,
                                  createTime: process.create_time as string,
                                })}
                              >
                                {process.pid}
                              </button>
                            ) : process.pid}
                          </td>
                          <td className="machine-process-name">{process.name ?? '—'}</td>
                          <td>{process.status ?? (process.access_denied ? 'Access denied' : '—')}</td>
                          <td>{formatPercent(process.cpu_percent)}</td>
                          <td>{formatBytes(process.rss_bytes)}</td>
                          <td>{formatPercent(process.memory_percent)}</td>
                          <td>{formatRuntime(process.runtime_seconds)}</td>
                          <td>{displayBoolean(process.long_running)}</td>
                          {selectedHost.platform === 'linux' && <td>{displayBoolean(process.zombie)}</td>}
                        </tr>
                      )
                    })}
                    {currentProcesses && visibleProcesses.length === 0 && (
                      <tr>
                        <td colSpan={selectedHost.platform === 'linux' ? 9 : 8} className="machine-table-empty">
                          {currentMonitoring === null && hasMonitoring
                            ? 'No process snapshot has been collected.'
                            : search || longRunningOnly || zombiesOnly
                              ? 'No processes match these filters.'
                              : 'No process data is available for this snapshot.'}
                        </td>
                      </tr>
                    )}
                    {!currentProcesses && (
                      <tr><td colSpan={selectedHost.platform === 'linux' ? 9 : 8} className="machine-table-empty">
                        {processError ? 'Could not load processes. Previous data remains visible when available.' : 'Loading process data…'}
                      </td></tr>
                    )}
                  </tbody>
                </table>
              </div>
              <footer className="machine-pagination">
                <span>{totalProcesses > 0 ? `${offset + 1}–${Math.min(offset + PROCESS_PAGE_SIZE, totalProcesses)} of ${totalProcesses}` : '0 processes'}</span>
                <div>
                  <button type="button" className="btn btn-ghost" disabled={offset === 0} onClick={() => {
                    setOffset((value) => Math.max(0, value - PROCESS_PAGE_SIZE))
                    setSelectedProcess(null)
                  }}>Previous</button>
                  <span aria-live="polite">Page {pageNumber} of {pageCount}</span>
                  <button type="button" className="btn btn-ghost" disabled={offset + PROCESS_PAGE_SIZE >= totalProcesses} onClick={() => {
                    setOffset((value) => value + PROCESS_PAGE_SIZE)
                    setSelectedProcess(null)
                  }}>Next</button>
                </div>
              </footer>
              {processHistorySelection && selectedHostId !== null && (
                <ProcessHistoryPanel hostId={selectedHostId} process={processHistorySelection} />
              )}
            </section>
            </>)}
            </div>

            {collectorToken && (
              <CollectorTokenDialog token={collectorToken} onClose={() => setCollectorToken(null)} />
            )}
          </>
        )}
        {collectorToken && !selectedHost && (
          <CollectorTokenDialog token={collectorToken} onClose={() => setCollectorToken(null)} />
        )}
        </section>
    </div>
  )
}
