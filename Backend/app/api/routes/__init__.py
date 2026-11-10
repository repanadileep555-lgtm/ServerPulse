from fastapi import APIRouter

from app.api.routes.system import router as system_router
from app.api.routes.users import router as users_router

router = APIRouter()
router.include_router(system_router)
router.include_router(users_router)
