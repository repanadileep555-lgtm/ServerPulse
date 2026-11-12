import { api } from './client'

export type HostPlatform = 'windows' | 'linux'
export type DeploymentType = 'localhost' | 'wsl' | 'external'
export type Connectivity = 'online' | 'offline' | 'never_seen' | 'disabled'

export interface Host {
  id: number
  name: string
  platform: HostPlatform
  deployment_type: DeploymentType
  wsl_distro: string | null
  enabled: boolean
  long_running_seconds: number
  created_at: string
  last_heartbeat_at: string | null
  connectivity: Connectivity
  metrics_sampled_at: string | null
  cpu_percent: number | null
  memory_percent: number | null
}

export interface Sample {
  id: number
  sampled_at: string
  received_at: string
  cpu_percent: number
  memory_total_bytes: number
  memory_available_bytes: number
  memory_used_bytes: number
  memory_percent: number
  process_count: number
  denied_count: number
  vanished_count: number
  long_running_count: number
  zombie_count: number | null
}

export interface ProcessObservation {
  pid: number
  create_time: string | null
  name: string | null
  status: string | null
  cpu_percent: number | null
  rss_bytes: number | null
  memory_percent: number | null
  runtime_seconds: number | null
  long_running: boolean | null
  zombie: boolean | null
  access_denied: boolean
}

export interface ProcessHistoryObservation extends ProcessObservation {
  sampled_at: string
}

export interface ProcessPage {
  sample_id: number | null
  sampled_at: string | null
  total: number
  items: ProcessObservation[]
}

export interface CollectorTokenResponse {
  host: Host
  collector_token: string
}

export interface CreateHostRequest {
  name: string
  platform: HostPlatform
  deployment_type: DeploymentType
  wsl_distro: string | null
  long_running_seconds: number
}

export async function listHosts(signal?: AbortSignal): Promise<Host[]> {
  const { data } = await api.get<Host[]>('/hosts', { signal })
  return data
}

export async function createHost(body: CreateHostRequest): Promise<CollectorTokenResponse> {
  const { data } = await api.post<CollectorTokenResponse>('/hosts', body)
  return data
}

export async function updateHost(
  hostId: number,
  body: { enabled?: boolean; long_running_seconds?: number },
): Promise<Host> {
  const { data } = await api.patch<Host>(`/hosts/${hostId}`, body)
  return data
}

export async function rotateCollectorToken(hostId: number): Promise<CollectorTokenResponse> {
  const { data } = await api.post<CollectorTokenResponse>(`/hosts/${hostId}/credentials/rotate`)
  return data
}

export interface HostNotification {
  id: number
  host_id: number
  message: string
  created_at: string
  read_at: string | null
}

export async function listNotifications(signal?: AbortSignal): Promise<HostNotification[]> {
  const { data } = await api.get<HostNotification[]>('/notifications', { signal })
  return data
}

export async function markNotificationRead(notificationId: number): Promise<void> {
  await api.post(`/notifications/${notificationId}/read`)
}

export async function markAllNotificationsRead(): Promise<void> {
  await api.post('/notifications/read-all')
}

export type AlertMetric =
  | 'cpu_percent'
  | 'memory_percent'
  | 'long_running_count'
  | 'zombie_count'
  | 'process_cpu_percent'
  | 'process_memory_percent'
  | 'process_count'

export interface AlertRule {
  id: number
  host_id: number
  name: string
  metric: AlertMetric
  process_name: string | null
  threshold: number
  sustained_minutes: number
  enabled: boolean
  updated_at: string
  firing: boolean
}

export interface AlertRuleUpsert {
  name: string
  metric: AlertMetric
  process_name: string | null
  threshold: number
  sustained_minutes: number
  enabled: boolean
}

export interface MachineAlert {
  id: number
  rule_id: number
  host_id: number
  metric: AlertMetric
  status: 'open' | 'resolved'
  value: number
  threshold: number
  triggered_at: string
  resolved_at: string | null
}

export async function listAlertRules(hostId: number, signal?: AbortSignal): Promise<AlertRule[]> {
  const { data } = await api.get<AlertRule[]>(`/hosts/${hostId}/alert-rules`, { signal })
  return data
}

export async function createAlertRule(hostId: number, body: AlertRuleUpsert): Promise<AlertRule> {
  const { data } = await api.post<AlertRule>(`/hosts/${hostId}/alert-rules`, body)
  return data
}

export async function updateAlertRule(hostId: number, ruleId: number, body: AlertRuleUpsert): Promise<AlertRule> {
  const { data } = await api.put<AlertRule>(`/hosts/${hostId}/alert-rules/${ruleId}`, body)
  return data
}

export async function deleteAlertRule(hostId: number, ruleId: number): Promise<void> {
  await api.delete(`/hosts/${hostId}/alert-rules/${ruleId}`)
}

export async function listMachineAlerts(hostId: number, limit = 20, signal?: AbortSignal): Promise<MachineAlert[]> {
  const { data } = await api.get<MachineAlert[]>(`/hosts/${hostId}/alerts`, { params: { limit }, signal })
  return data
}

export interface LocalCollectorState {
  running: boolean
  pid: number | null
  source: 'server' | 'external' | null
}

export async function getLocalCollector(hostId: number, signal?: AbortSignal): Promise<LocalCollectorState> {
  const { data } = await api.get<LocalCollectorState>(`/hosts/${hostId}/local-collector`, { signal })
  return data
}

export async function startLocalCollector(hostId: number): Promise<LocalCollectorState> {
  const { data } = await api.post<LocalCollectorState>(`/hosts/${hostId}/local-collector/start`)
  return data
}

export async function stopLocalCollector(hostId: number): Promise<LocalCollectorState> {
  const { data } = await api.post<LocalCollectorState>(`/hosts/${hostId}/local-collector/stop`)
  return data
}

export interface SSHScanResult {
  address: string
  port: number
  host_key_algorithm: string
  host_key_fingerprint: string
}

export interface SSHInstallBody {
  name: string
  address: string
  port: number
  username: string
  auth_method: 'password' | 'private_key'
  secret: string
  host_key_fingerprint: string
  long_running_seconds: number
}

export interface SSHCollectorState {
  host: Host
  ssh: {
    address: string
    port: number
    username: string
    auth_method: 'password' | 'private_key'
    remote_port: number
    desired_state: 'running' | 'stopped'
    connected: boolean
  }
  remote_stopped?: boolean
}

export async function scanSSHHost(address: string, port: number): Promise<SSHScanResult> {
  const { data } = await api.post<SSHScanResult>('/hosts/ssh/scan', { address, port })
  return data
}

export async function installSSHCollector(body: SSHInstallBody): Promise<SSHCollectorState> {
  const { data } = await api.post<SSHCollectorState>('/hosts/ssh', body)
  return data
}

export async function getSSHCollector(hostId: number, signal?: AbortSignal): Promise<SSHCollectorState> {
  const { data } = await api.get<SSHCollectorState>(`/hosts/${hostId}/ssh-collector`, { signal })
  return data
}

export async function startSSHCollector(hostId: number): Promise<SSHCollectorState> {
  const { data } = await api.post<SSHCollectorState>(`/hosts/${hostId}/ssh-collector/start`)
  return data
}

export async function stopSSHCollector(hostId: number): Promise<SSHCollectorState> {
  const { data } = await api.post<SSHCollectorState>(`/hosts/${hostId}/ssh-collector/stop`)
  return data
}

export async function getMonitoring(hostId: number, signal?: AbortSignal): Promise<{ host: Host; latest: Sample | null }> {
  const { data } = await api.get<{ host: Host; latest: Sample | null }>(`/hosts/${hostId}/monitoring`, { signal })
  return data
}

export async function getMetrics(hostId: number, signal?: AbortSignal): Promise<Sample[]> {
  const { data } = await api.get<Sample[]>(`/hosts/${hostId}/metrics`, {
    params: { limit: 120 },
    signal,
  })
  return data
}

export async function getProcesses(
  hostId: number,
  options: {
    offset: number
    limit: number
    search: string
    longRunning: boolean
    zombie: boolean
    sort: 'cpu' | 'memory' | 'runtime' | 'name'
  },
  signal?: AbortSignal,
): Promise<ProcessPage> {
  const params: Record<string, string | number | boolean> = {
    offset: options.offset,
    limit: options.limit,
    search: options.search,
    sort: options.sort,
  }
  if (options.longRunning) params.long_running = true
  if (options.zombie) params.zombie = true
  const { data } = await api.get<ProcessPage>(`/hosts/${hostId}/processes`, { params, signal })
  return data
}

export async function getProcessHistory(
  hostId: number,
  process: { pid: number; createTime: string },
  signal?: AbortSignal,
): Promise<ProcessHistoryObservation[]> {
  const { data } = await api.get<{ items: ProcessHistoryObservation[] }>(
    `/hosts/${hostId}/process-history`,
    {
      params: { pid: process.pid, create_time: process.createTime, limit: 120 },
      signal,
    },
  )
  return data.items
}

export type LogSeverity = 'debug' | 'info' | 'warning' | 'error' | 'critical' | 'unknown'
export type LogSourceType = 'windows_eventlog' | 'journald'

export interface LogSource {
  id: number
  source_type: LogSourceType
  category: string
  channel: string
  enabled: boolean
  last_status: 'ok' | 'unavailable' | 'error' | null
  last_error: string | null
  last_attempt_at: string | null
  last_success_at: string | null
}

export interface LogEvent {
  id: number
  source_id: number
  source_type: LogSourceType
  category: string
  channel: string
  source_record_id: string
  occurred_at: string
  collected_at: string
  timestamp_quality: 'native' | 'fallback'
  severity: LogSeverity
  native_severity: string | null
  event_id: number | null
  provider: string | null
  message: string
  service_id: number | null
  service_name: string | null
}

export interface LogPage {
  total: number
  items: LogEvent[]
}

export interface LogQuery {
  sourceId: number | null
  minSeverity: LogSeverity | ''
  since: string | null
  until: string | null
  keyword: string
  offset: number
  limit: number
}

export async function getLogSources(hostId: number, signal?: AbortSignal): Promise<LogSource[]> {
  const { data } = await api.get<LogSource[]>(`/hosts/${hostId}/log-sources`, { signal })
  return data
}

export interface HostService {
  id: number
  service_name: string
  display_name: string | null
  current_state: 'running' | 'stopped' | 'failed' | 'paused' | 'transitional' | 'unknown'
  native_state: string | null
  last_status: 'never_run' | 'ok' | 'unavailable' | 'error'
  last_checked_at: string | null
  last_error: string | null
  log_count: number
  last_log_at: string | null
}

export async function getHostServices(hostId: number, signal?: AbortSignal): Promise<HostService[]> {
  const { data } = await api.get<HostService[]>(`/hosts/${hostId}/services`, { signal })
  return data
}

export async function getLogs(hostId: number, query: LogQuery, signal?: AbortSignal): Promise<LogPage> {
  const params: Record<string, string | number> = { offset: query.offset, limit: query.limit }
  if (query.sourceId !== null) params.source_id = query.sourceId
  if (query.minSeverity) params.min_severity = query.minSeverity
  if (query.since) params.since = query.since
  if (query.until) params.until = query.until
  if (query.keyword) params.keyword = query.keyword
  const { data } = await api.get<LogPage>(`/hosts/${hostId}/logs`, { params, signal })
  return data
}
