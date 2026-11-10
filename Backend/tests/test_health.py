import asyncio
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.db.db_pool import DatabasePool
from app.main import app


class HealthTests(unittest.TestCase):
    def test_health_reuses_startup_pool_and_closes_it_on_shutdown(self) -> None:
        with TemporaryDirectory() as directory:
            pool = DatabasePool(Path(directory) / "health.db", pool_size=1)
            with patch("app.main.DatabasePool", return_value=pool) as pool_class:
                with TestClient(app) as client:
                    self.assertIs(app.state.db_pool, pool)
                    for _ in range(2):
                        response = client.get("/health")
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json(), {"database": "ok"})
                    pool_class.assert_called_once_with()

            self.assertFalse(hasattr(app.state, "db_pool"))
            with self.assertRaisesRegex(RuntimeError, "Open the database pool"):
                asyncio.run(pool.fetch_one("SELECT 1"))

    def test_pool_initialization_failure_prevents_startup(self) -> None:
        with patch("app.main.DatabasePool") as pool_class:
            pool_class.return_value.__aenter__.side_effect = sqlite3.OperationalError(
                "unable to open database file"
            )
            with self.assertRaisesRegex(sqlite3.OperationalError, "unable to open"):
                with TestClient(app):
                    self.fail("Startup must fail when the database pool cannot open")
            self.assertFalse(hasattr(app.state, "db_pool"))
