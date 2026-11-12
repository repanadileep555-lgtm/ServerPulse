from fastapi import APIRouter

from app.api.routes.collector import router as collector_router
from app.api.routes.hosts import router as hosts_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.system import router as system_router
from app.api.routes.users import router as users_router

router = APIRouter()
router.include_router(system_router)
router.include_router(users_router)
router.include_router(hosts_router)
router.include_router(notifications_router)
router.include_router(collector_router)
