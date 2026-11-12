from typing import Any

from fastapi import APIRouter

from app.api.routes.hosts import Service, Viewer

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(actor: Viewer, service: Service) -> list[dict[str, Any]]:
    return await service.list_notifications(actor.user_id)


@router.post("/read-all")
async def mark_all_notifications_read(actor: Viewer, service: Service) -> dict[str, Any]:
    return await service.mark_all_notifications_read(actor.user_id)


@router.post("/{notification_id}/read")
async def mark_notification_read(notification_id: int, actor: Viewer, service: Service) -> dict[str, Any]:
    return await service.mark_notification_read(notification_id, actor.user_id)
