import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pwdlib import PasswordHash

from app.cli.create_admin import main
from db.migrate import migrate

PASSWORD = "a-long-test-password"


class CreateAdminCliTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = self.enterContext(TemporaryDirectory())
        self.db_path = Path(directory) / "admin.db"
        migrate(self.db_path)

    def _run(self, username: str, passwords: list[str]) -> None:
        with patch("app.cli.create_admin.getpass.getpass", side_effect=passwords):
            main(["--username", username, "--db", str(self.db_path)])

    def _user_row(self, username: str) -> tuple[str, int, int] | None:
        with closing(sqlite3.connect(self.db_path)) as connection:
            return connection.execute(
                "SELECT password_hash, is_admin, enabled FROM users WHERE username = ?",
                (username,),
            ).fetchone()

    def test_creates_enabled_admin_with_hashed_password(self) -> None:
        self._run("root", [PASSWORD, PASSWORD])

        password_hash, is_admin, enabled = self._user_row("root")
        self.assertEqual((is_admin, enabled), (1, 1))
        self.assertTrue(PasswordHash.recommended().verify(PASSWORD, password_hash))

    def test_prompts_for_username_when_not_given(self) -> None:
        with patch("builtins.input", return_value="root"), patch(
            "app.cli.create_admin.getpass.getpass", side_effect=[PASSWORD, PASSWORD]
        ):
            main(["--db", str(self.db_path)])

        self.assertEqual(self._user_row("root")[1], 1)

    def test_mismatched_passwords_create_nothing(self) -> None:
        with self.assertRaises(SystemExit):
            self._run("root", [PASSWORD, "a-different-password"])

        self.assertIsNone(self._user_row("root"))

    def test_duplicate_username_exits_with_error(self) -> None:
        self._run("root", [PASSWORD, PASSWORD])

        with self.assertRaises(SystemExit) as raised:
            self._run("root", [PASSWORD, PASSWORD])
        self.assertEqual(raised.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
