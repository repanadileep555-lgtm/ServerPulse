from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.routes.users import get_user_service
from app.db.db_client import get_database_pool
from app.db.db_pool import DatabasePool
from app.middleware.auth_middleware import AuthenticatedUser, get_current_user
from app.schemas.monitoring import AlertRuleUpsert, HostCreate, HostUpdate
from app.schemas.ssh_collector import SSHInstallRequest, SSHScanRequest
from app.services.monitoring_service import HostActor, MonitoringService
from app.services.ssh_collector import SSHCollectorService
from app.services.user_service import UserService

router = APIRouter(prefix="/hosts", tags=["hosts"])


async def require_viewer(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> HostActor:
    account = await service.get_enabled_user(user.subject)
    if account is None:
        raise HTTPException(401, "Account is not available", headers={"WWW-Authenticate": "Bearer"})
    return HostActor(user_id=account.id, is_admin=account.is_admin)


async def require_owner(actor: Annotated[HostActor, Depends(require_viewer)]) -> HostActor:
    if actor.is_admin:
        raise HTTPException(403, "Admins cannot register machines. Ask the owner to set up the collector.")
    return actor


async def get_monitoring_service(
    pool: Annotated[DatabasePool, Depends(get_database_pool)],
) -> MonitoringService:
    return MonitoringService(pool)


Service = Annotated[MonitoringService, Depends(get_monitoring_service)]
Viewer = Annotated[HostActor, Depends(require_viewer)]
Owner = Annotated[HostActor, Depends(require_owner)]


@router.get("")
async def list_hosts(actor: Viewer, service: Service) -> list[dict[str, Any]]:
    return await service.list_hosts(actor)


@router.post("", status_code=201)
async def register_host(request: HostCreate, actor: Viewer, service: Service) -> dict[str, Any]:
    return await service.register(request, actor)


@router.patch("/{host_id}")
async def update_host(host_id: int, request: HostUpdate, actor: Viewer, service: Service) -> dict[str, Any]:
    return await service.update(host_id, request, actor)


@router.post("/{host_id}/credentials/rotate")
async def rotate_token(host_id: int, actor: Viewer, service: Service) -> dict[str, Any]:
    return await service.rotate_token(host_id, actor)


@router.get("/{host_id}/local-collector")
async def local_collector_status(host_id: int, actor: Viewer, service: Service) -> dict[str, Any]:
    return await service.local_collector_status(host_id, actor)


@router.post("/{host_id}/local-collector/start")
async def start_local_collector(host_id: int, actor: Viewer, service: Service) -> dict[str, Any]:
    return await service.start_local_collector(host_id, actor)


@router.post("/{host_id}/local-collector/stop")
async def stop_local_collector(host_id: int, actor: Viewer, service: Service) -> dict[str, Any]:
    return await service.stop_local_collector(host_id, actor)


async def get_ssh_service(
    pool: Annotated[DatabasePool, Depends(get_database_pool)],
) -> SSHCollectorService:
    return SSHCollectorService(pool)


SSHService = Annotated[SSHCollectorService, Depends(get_ssh_service)]


@router.post("/ssh/scan")
async def scan_ssh_host(request: SSHScanRequest, actor: Owner, service: SSHService) -> dict[str, Any]:
    return await service.scan(request)


@router.post("/ssh", status_code=201)
async def install_ssh_collector(
    request: SSHInstallRequest, actor: Owner, service: SSHService,
) -> dict[str, Any]:
    return await service.install(request, actor)


@router.get("/{host_id}/ssh-collector")
async def ssh_collector_status(host_id: int, actor: Viewer, service: SSHService) -> dict[str, Any]:
    return await service.status(host_id, actor)


@router.post("/{host_id}/ssh-collector/start")
async def start_ssh_collector(host_id: int, actor: Viewer, service: SSHService) -> dict[str, Any]:
    return await service.start(host_id, actor)


@router.post("/{host_id}/ssh-collector/stop")
async def stop_ssh_collector(host_id: int, actor: Viewer, service: SSHService) -> dict[str, Any]:
    return await service.stop(host_id, actor)


@router.get("/{host_id}/alert-rules")
async def list_alert_rules(host_id: int, actor: Viewer, service: Service) -> list[dict[str, Any]]:
    return await service.list_alert_rules(host_id, actor)


@router.post("/{host_id}/alert-rules", status_code=201)
async def create_alert_rule(
    host_id: int, request: AlertRuleUpsert, actor: Viewer, service: Service
) -> dict[str, Any]:
    return await service.create_alert_rule(host_id, request, actor)


@router.put("/{host_id}/alert-rules/{rule_id}")
async def update_alert_rule(
    host_id: int, rule_id: int, request: AlertRuleUpsert, actor: Viewer, service: Service
) -> dict[str, Any]:
    return await service.update_alert_rule(host_id, rule_id, request, actor)


@router.delete("/{host_id}/alert-rules/{rule_id}")
async def delete_alert_rule(host_id: int, rule_id: int, actor: Viewer, service: Service) -> dict[str, Any]:
    return await service.delete_alert_rule(host_id, rule_id, actor)


@router.get("/{host_id}/alerts")
async def list_machine_alerts(
    host_id: int, actor: Viewer, service: Service, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[dict[str, Any]]:
    return await service.list_machine_alerts(host_id, limit, actor)


@router.get("/{host_id}/monitoring")
async def monitoring(host_id: int, actor: Viewer, service: Service) -> dict[str, Any]:
    return await service.latest(host_id, actor)


@router.get("/{host_id}/metrics")
async def metrics(
    host_id: int, actor: Viewer, service: Service, limit: int = Query(default=120, ge=1, le=500),
) -> list[dict[str, Any]]:
    return await service.metrics(host_id, limit, actor)


@router.get("/{host_id}/processes")
async def processes(
    host_id: int, actor: Viewer, service: Service,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    search: str = Query(default="", max_length=100),
    long_running: bool = False,
    zombie: bool = False,
    sort: Literal["cpu", "memory", "runtime", "name"] = "cpu",
) -> dict[str, Any]:
    return await service.processes(host_id, offset, limit, search, long_running, zombie, sort, actor)


@router.get("/{host_id}/process-history")
async def process_history(
    host_id: int, actor: Viewer, service: Service,
    pid: int = Query(ge=0), create_time: datetime = Query(),
    limit: int = Query(default=120, ge=1, le=500),
) -> dict[str, Any]:
    if create_time.utcoffset() is None:
        raise HTTPException(422, "Process creation time requires a timezone")
    return await service.process_history(host_id, pid, create_time, limit, actor)


@router.get("/{host_id}/log-sources")
async def log_sources(host_id: int, actor: Viewer, service: Service) -> list[dict[str, Any]]:
    return await service.list_log_sources(host_id, actor)


@router.get("/{host_id}/services")
async def services(host_id: int, actor: Viewer, service: Service) -> list[dict[str, Any]]:
    return await service.list_services(host_id, actor)


@router.get("/{host_id}/logs")
async def logs(
    host_id: int, actor: Viewer, service: Service,
    source_id: int | None = Query(default=None, ge=1),
    min_severity: Literal["debug", "info", "warning", "error", "critical"] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    keyword: str = Query(default="", max_length=200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    for value in (since, until):
        if value is not None and value.utcoffset() is None:
            raise HTTPException(422, "Time filters require a timezone")
    return await service.list_logs(
        host_id, source_id, min_severity, since, until, keyword.strip(), offset, limit, actor,
    )
