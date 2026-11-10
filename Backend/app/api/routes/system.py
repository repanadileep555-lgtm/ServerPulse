from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.health import check_health
from app.db.db_client import get_database_pool
from app.db.db_pool import DatabasePool

router = APIRouter(tags=["system"])


@router.get("/")
async def root():
    return {
        "message": "Welcome to ServerPulse API",
        "status": "Running"
    }


@router.get("/health")
async def health_check(pool: Annotated[DatabasePool, Depends(get_database_pool)]):
    return await check_health(pool)
