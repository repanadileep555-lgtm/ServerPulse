from app.db.db_pool import DatabasePool
from fastapi import Request


async def get_database_pool(request: Request) -> DatabasePool:
    pool = getattr(request.app.state, "db_pool", None)
    if not isinstance(pool, DatabasePool):
        raise RuntimeError("Database pool is not initialized")
    return pool
