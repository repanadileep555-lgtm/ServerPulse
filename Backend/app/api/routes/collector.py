from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError

from app.api.routes.hosts import Service
from app.middleware.auth_middleware import bearer_scheme
from app.schemas.monitoring import LogBatch, MonitoringBatch, ServiceBatch

router = APIRouter(prefix="/collector", tags=["collector"])
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_LOG_BATCH_BYTES = 4 * 1024 * 1024
MAX_SERVICE_BATCH_BYTES = 4 * 1024 * 1024


async def get_collector_host(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    service: Service,
) -> dict[str, Any]:
    if credentials is None:
        raise HTTPException(401, "Collector credential required", headers={"WWW-Authenticate": "Bearer"})
    return await service.collector_host(credentials.credentials)


CollectorHost = Annotated[dict[str, Any], Depends(get_collector_host)]


async def read_bounded_body(request: Request, limit: int, label: str) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit:
            raise HTTPException(413, f"{label} exceeds {limit // (1024 * 1024)} MiB")
        body.extend(chunk)
    return bytes(body)


@router.get("/configuration")
async def configuration(host: CollectorHost) -> dict[str, Any]:
    return host


@router.post("/snapshots")
async def ingest(request: Request, host: CollectorHost, service: Service) -> dict[str, Any]:
    body = await read_bounded_body(request, MAX_SNAPSHOT_BYTES, "Snapshot")
    try:
        batch = MonitoringBatch.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(422, "Invalid monitoring snapshot") from exc
    return await service.ingest(host, batch)


@router.post("/logs")
async def ingest_logs(request: Request, host: CollectorHost, service: Service) -> dict[str, Any]:
    body = await read_bounded_body(request, MAX_LOG_BATCH_BYTES, "Log batch")
    try:
        batch = LogBatch.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(422, "Invalid log batch") from exc
    return await service.ingest_logs(host, batch)


@router.post("/services")
async def ingest_services(request: Request, host: CollectorHost, service: Service) -> dict[str, Any]:
    body = await read_bounded_body(request, MAX_SERVICE_BATCH_BYTES, "Service inventory")
    try:
        batch = ServiceBatch.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(422, "Invalid service inventory") from exc
    return await service.ingest_services(host, batch)
