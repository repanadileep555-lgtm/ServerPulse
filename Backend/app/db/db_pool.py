import asyncio
import sqlite3
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

from app.conf.config import DB_PATH, DB_POOL_SIZE, DB_TIMEOUT_SECONDS


class DatabasePool:
    """Asynchronous SQLite pool owned by one event loop."""

    def __init__(
        self,
        db_path: str | Path = DB_PATH,
        pool_size: int = DB_POOL_SIZE,
        timeout: float = DB_TIMEOUT_SECONDS,
    ) -> None:
        if pool_size < 1:
            raise ValueError("pool_size must be at least 1")
        self._db_path = Path(db_path)
        self._pool_size = pool_size
        self._timeout = timeout
        self._pool: asyncio.Queue[aiosqlite.Connection] | None = None

    async def __aenter__(self) -> "DatabasePool":
        if self._pool is not None:
            raise RuntimeError("Database pool is already open")
        await asyncio.to_thread(self._db_path.parent.mkdir, parents=True, exist_ok=True)
        pool: asyncio.Queue[aiosqlite.Connection] = asyncio.Queue(maxsize=self._pool_size)
        try:
            for _ in range(self._pool_size):
                pool.put_nowait(await self._open_connection())
        except BaseException:
            while not pool.empty():
                await pool.get_nowait().close()
            raise
        self._pool = pool
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def _open_connection(self) -> aiosqlite.Connection:
        # Autocommit mode; transactions are opened explicitly in transaction().
        con = await aiosqlite.connect(
            self._db_path,
            timeout=self._timeout,
            isolation_level=None,
        )
        try:
            con.row_factory = sqlite3.Row
            async with con.execute("PRAGMA foreign_keys = ON"):
                pass
            async with con.execute("PRAGMA journal_mode = WAL"):
                pass
        except BaseException:
            await con.close()
            raise
        return con

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[aiosqlite.Connection]:
        pool = self._pool
        if pool is None:
            raise RuntimeError("Open the database pool with 'async with DatabasePool(...)'")
        try:
            con = await asyncio.wait_for(pool.get(), timeout=self._timeout)
        except TimeoutError:
            raise TimeoutError("No database connection available in the pool") from None
        try:
            yield con
        finally:
            try:
                await con.rollback()
            finally:
                pool.put_nowait(con)

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[aiosqlite.Connection]:
        async with self.connection() as con:
            async with con.execute("BEGIN IMMEDIATE"):
                pass
            try:
                yield con
            except BaseException:
                await con.rollback()
                raise
            await con.commit()

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Run a single write statement in autocommit mode and return the affected row count."""
        async with self.connection() as con:
            async with con.execute(sql, params) as cursor:
                return cursor.rowcount

    async def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        async with self.connection() as con:
            async with con.execute(sql, params) as cursor:
                return list(await cursor.fetchall())

    async def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        async with self.connection() as con:
            async with con.execute(sql, params) as cursor:
                return await cursor.fetchone()

    async def close(self) -> None:
        """Close the pool after all tasks using it have finished."""
        pool = self._pool
        if pool is None:
            return
        if pool.qsize() != self._pool_size:
            raise RuntimeError("Cannot close a database pool with borrowed connections")
        self._pool = None
        while not pool.empty():
            await pool.get_nowait().close()
