from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi_offline import FastAPIOffline

from app.api.routes import router
from app.db.db_pool import DatabasePool
from app.conf.config import settings
from app.middleware.mw_client import add_middleware
from app.services.ssh_collector import ssh_supervisors


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    async with DatabasePool() as pool:
        app.state.db_pool = pool
        await ssh_supervisors.restore(pool)
        try:
            yield
        finally:
            await ssh_supervisors.shutdown()
            del app.state.db_pool


app = FastAPIOffline(
    title="ServerPulse API",
    description="Centralized Windows & Linux Servers Log Collection and Monitoring System",
    version="1.0.0",
    lifespan=lifespan,
)

add_middleware(app)
app.include_router(router)


def main() -> None:
    uvicorn.run(app, host=settings.host, port=settings.port)
