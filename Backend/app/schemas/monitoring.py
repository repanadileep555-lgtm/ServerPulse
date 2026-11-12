from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Percent = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
SqliteInteger = Annotated[int, Field(ge=0, le=9223372036854775807)]
Platform = Literal["windows", "linux"]


def utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class HostCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_. -]*$")
    platform: Platform
    deployment_type: Literal["localhost", "wsl", "external"]
    wsl_distro: str | None = Field(default=None, min_length=1, max_length=100)
    long_running_seconds: int = Field(default=3600, ge=60, le=31536000)

    @model_validator(mode="after")
    def check_wsl(self) -> "HostCreate":
        if self.deployment_type == "wsl" and (
            self.platform != "linux" or not self.wsl_distro
        ):
            raise ValueError("WSL hosts require Linux platform and a distribution name")
        if self.deployment_type != "wsl" and self.wsl_distro is not None:
            raise ValueError("Distribution name is only valid for WSL hosts")
        return self


class HostUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    long_running_seconds: int | None = Field(default=None, ge=60, le=31536000)

    @model_validator(mode="after")
    def require_changes(self) -> "HostUpdate":
        if not self.model_fields_set or any(
            getattr(self, field) is None for field in self.model_fields_set
        ):
            raise ValueError("Provide at least one non-null setting")
        return self


AlertMetric = Literal[
    "cpu_percent",
    "memory_percent",
    "long_running_count",
    "zombie_count",
    "process_cpu_percent",
    "process_memory_percent",
    "process_count",
]
PROCESS_ALERT_METRICS = frozenset({"process_cpu_percent", "process_memory_percent", "process_count"})
AlertRuleName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
AlertProcessName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]


class AlertRuleUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: AlertRuleName
    metric: AlertMetric
    process_name: AlertProcessName | None = None
    threshold: float = Field(ge=0, le=9223372036854775807, allow_inf_nan=False)
    sustained_minutes: int = Field(ge=1, le=1440)
    enabled: bool = True

    @model_validator(mode="after")
    def check_process_name(self) -> "AlertRuleUpsert":
        if self.metric in PROCESS_ALERT_METRICS and self.process_name is None:
            raise ValueError("Process alerts need a process name")
        if self.metric not in PROCESS_ALERT_METRICS and self.process_name is not None:
            raise ValueError("Only process alerts can name a process")
        return self


class ProcessObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pid: SqliteInteger
    create_time: datetime | None = None
    name: str | None = Field(default=None, max_length=512)
    status: str | None = Field(default=None, max_length=64)
    cpu_percent: Percent | None = None
    rss_bytes: SqliteInteger | None = None
    memory_percent: Percent | None = None
    access_denied: bool = False


class MonitoringBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    platform: Platform
    sampled_at: datetime
    cpu_percent: Percent
    memory_total_bytes: SqliteInteger = Field(gt=0)
    memory_available_bytes: SqliteInteger
    denied_count: int = Field(ge=0, le=20000)
    vanished_count: SqliteInteger
    processes: list[ProcessObservation] = Field(max_length=20000)

    @model_validator(mode="after")
    def validate_snapshot(self) -> "MonitoringBatch":
        if self.sampled_at.utcoffset() is None:
            raise ValueError("sampled_at requires a timezone")
        if self.sampled_at > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("sampled_at is too far in the future")
        if self.memory_available_bytes > self.memory_total_bytes:
            raise ValueError("Available memory exceeds total memory")
        pids = [process.pid for process in self.processes]
        if len(pids) != len(set(pids)):
            raise ValueError("A snapshot cannot contain duplicate PIDs")
        if self.denied_count != sum(process.access_denied for process in self.processes):
            raise ValueError("denied_count must match process permission failures")
        for process in self.processes:
            if process.create_time is not None:
                if process.create_time.utcoffset() is None:
                    raise ValueError("Process creation time requires a timezone")
                if process.create_time > self.sampled_at:
                    raise ValueError("Process creation time is after the sample")
            if self.platform == "windows" and process.status == "zombie":
                raise ValueError("Zombie processes are not a Windows state")
        return self


LogSeverity = Literal["debug", "info", "warning", "error", "critical", "unknown"]
LogCategory = Literal["system", "application"]
LogSourceType = Literal["windows_eventlog", "journald"]
PLATFORM_SOURCE_TYPES = {"windows": "windows_eventlog", "linux": "journald"}


class LogSourceReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: LogSourceType
    category: LogCategory
    channel: str = Field(min_length=1, max_length=128)
    status: Literal["ok", "unavailable", "error"]
    error: str | None = Field(default=None, max_length=512)
    checkpoint: str | None = Field(default=None, min_length=1, max_length=512)


class LogRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: LogSourceType
    category: LogCategory
    channel: str = Field(min_length=1, max_length=128)
    source_record_id: str = Field(min_length=1, max_length=256)
    occurred_at: datetime
    timestamp_quality: Literal["native", "fallback"]
    severity: LogSeverity
    native_severity: str | None = Field(default=None, max_length=64)
    event_id: SqliteInteger | None = None
    provider: str | None = Field(default=None, max_length=256)
    unit: str | None = Field(default=None, max_length=256)
    service_reference: str | None = Field(default=None, max_length=256)
    message: str = Field(default="", max_length=4096)


class LogBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    platform: Platform
    collected_at: datetime
    sources: list[LogSourceReport] = Field(min_length=1, max_length=16)
    records: list[LogRecord] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def validate_batch(self) -> "LogBatch":
        if self.collected_at.utcoffset() is None:
            raise ValueError("collected_at requires a timezone")
        if self.collected_at > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("collected_at is too far in the future")
        expected_type = PLATFORM_SOURCE_TYPES[self.platform]
        keys = set()
        for source in self.sources:
            if source.source_type != expected_type:
                raise ValueError("Log source type does not match the platform")
            if self.platform == "linux" and source.category != "system":
                raise ValueError("Journald sources only report the system category")
            keys.add((source.source_type, source.category, source.channel))
        if len(keys) != len(self.sources):
            raise ValueError("A batch cannot report the same log source twice")
        for record in self.records:
            if (record.source_type, record.category, record.channel) not in keys:
                raise ValueError("Log record references a source that is not reported in this batch")
            if record.occurred_at.utcoffset() is None:
                raise ValueError("Log record time requires a timezone")
            if record.occurred_at > self.collected_at + timedelta(minutes=5):
                raise ValueError("Log record time is after collection")
        return self


ServiceState = Literal["running", "stopped", "failed", "paused", "transitional", "unknown"]
SERVICE_BATCH_LIMIT = 5000


class ServiceObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_name: str = Field(min_length=1, max_length=256)
    display_name: str | None = Field(default=None, max_length=512)
    current_state: ServiceState
    native_state: str | None = Field(default=None, max_length=64)


class ServiceBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    platform: Platform
    collected_at: datetime
    services: list[ServiceObservation] = Field(max_length=SERVICE_BATCH_LIMIT)

    @model_validator(mode="after")
    def validate_batch(self) -> "ServiceBatch":
        if self.collected_at.utcoffset() is None:
            raise ValueError("collected_at requires a timezone")
        if self.collected_at > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("collected_at is too far in the future")
        names = [service.service_name for service in self.services]
        if len(names) != len(set(names)):
            raise ValueError("A batch cannot contain duplicate service names")
        return self
