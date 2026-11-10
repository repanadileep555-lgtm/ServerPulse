import asyncio
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.db.db_pool import DatabasePool


class DatabasePoolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.pool = await self.enterAsyncContext(
            DatabasePool(
                Path(self.directory.name) / "test.db",
                pool_size=1,
                timeout=0.1,
            )
        )
        await self.pool.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")

    async def test_queries_and_autocommit(self) -> None:
        count = await self.pool.execute("INSERT INTO items (name) VALUES (?)", ("first",))
        self.assertEqual(count, 1)
        row = await self.pool.fetch_one("SELECT name FROM items WHERE id = ?", (1,))
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "first")
        rows = await self.pool.fetch_all("SELECT name FROM items ORDER BY id")
        self.assertEqual([item["name"] for item in rows], ["first"])
        self.assertIsNone(await self.pool.fetch_one("SELECT * FROM items WHERE id = 2"))

    async def test_transaction_commit_and_rollback(self) -> None:
        async with self.pool.transaction() as connection:
            async with connection.execute("INSERT INTO items (name) VALUES ('committed')"):
                pass

        with self.assertRaisesRegex(ValueError, "abort"):
            async with self.pool.transaction() as connection:
                async with connection.execute("INSERT INTO items (name) VALUES ('discarded')"):
                    pass
                raise ValueError("abort")

        rows = await self.pool.fetch_all("SELECT name FROM items")
        self.assertEqual([row["name"] for row in rows], ["committed"])

    async def test_unfinished_transaction_is_rolled_back_on_return(self) -> None:
        async with self.pool.connection() as connection:
            async with connection.execute("BEGIN"):
                pass
            async with connection.execute("INSERT INTO items (name) VALUES ('discarded')"):
                pass
        self.assertEqual(await self.pool.fetch_all("SELECT * FROM items"), [])

    async def test_waiting_for_connection_yields_and_times_out(self) -> None:
        async with self.pool.connection():
            waiting = asyncio.create_task(self.pool.fetch_one("SELECT 1"))
            await asyncio.sleep(0)
            self.assertFalse(waiting.done())
            with self.assertRaisesRegex(TimeoutError, "No database connection"):
                await waiting
        self.assertIsNotNone(await self.pool.fetch_one("SELECT 1"))

    async def test_cancellation_rolls_back_and_releases_connection(self) -> None:
        inserted = asyncio.Event()

        async def write_until_cancelled() -> None:
            async with self.pool.transaction() as connection:
                async with connection.execute("INSERT INTO items (name) VALUES ('discarded')"):
                    pass
                inserted.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(write_until_cancelled())
        try:
            await asyncio.wait_for(inserted.wait(), timeout=2)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertEqual(await self.pool.fetch_all("SELECT * FROM items"), [])

    async def test_query_error_releases_connection(self) -> None:
        with self.assertRaises(sqlite3.OperationalError):
            await self.pool.fetch_one("SELECT * FROM missing_table")
        self.assertIsNotNone(await self.pool.fetch_one("SELECT 1"))
