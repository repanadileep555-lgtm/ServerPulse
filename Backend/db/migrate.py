"""Apply raw SQL migrations from Backend/db/migrations to the SQLite database."""

import argparse
import re
import sqlite3
import sys
from pathlib import Path

# Make the `app` package importable when this file is run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.conf.config import DB_BUSY_TIMEOUT_MS, DB_MIGRATIONS_DIR, DB_PATH  # noqa: E402

VERSION_PATTERN = re.compile(r"\d{4}_[a-z0-9_]+")
DOWN_SUFFIX = ".down.sql"
UP_SUFFIX = ".up.sql"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None so transactions are controlled explicitly in migrate().
    con = sqlite3.connect(db_path, isolation_level=None)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute(f"PRAGMA busy_timeout = {DB_BUSY_TIMEOUT_MS}")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def _run_in_transaction(con: sqlite3.Connection, body: str) -> None:
    try:
        con.executescript("BEGIN IMMEDIATE;\n" + body + "\nCOMMIT;")
    except sqlite3.Error:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise


def _ensure_migrations_table(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )


def _up_files(migrations_dir: Path) -> list[Path]:
    files = []
    for path in sorted(migrations_dir.glob(f"*{UP_SUFFIX}")):
        if not VERSION_PATTERN.fullmatch(_version_of(path)):
            raise ValueError(f"Invalid migration filename: {path.name}")
        files.append(path)
    return files


def _version_of(path: Path) -> str:
    return path.name[: -len(UP_SUFFIX)]


def migrate(db_path: Path = DB_PATH, migrations_dir: Path = DB_MIGRATIONS_DIR) -> list[str]:
    """Apply all pending migrations and return their versions."""
    con = connect(db_path)
    try:
        _ensure_migrations_table(con)
        applied = {row[0] for row in con.execute("SELECT version FROM schema_migrations")}

        newly_applied = []
        for path in _up_files(migrations_dir):
            version = _version_of(path)
            if version in applied:
                continue
            _run_in_transaction(
                con,
                path.read_text(encoding="utf-8")
                + f"\nINSERT INTO schema_migrations (version) VALUES ('{version}');",
            )
            newly_applied.append(version)
        return newly_applied
    finally:
        con.close()


def rollback(db_path: Path = DB_PATH, migrations_dir: Path = DB_MIGRATIONS_DIR) -> str | None:
    """Undo the most recently applied migration using its down script; return its version or None."""
    con = connect(db_path)
    try:
        _ensure_migrations_table(con)
        row = con.execute("SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1").fetchone()
        if row is None:
            return None
        version = row[0]
        down_path = migrations_dir / f"{version}{DOWN_SUFFIX}"
        if not down_path.exists():
            raise FileNotFoundError(f"Missing down script for {version}: {down_path.name}")
        _run_in_transaction(
            con,
            down_path.read_text(encoding="utf-8")
            + f"\nDELETE FROM schema_migrations WHERE version = '{version}';",
        )
        return version
    finally:
        con.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Apply or roll back raw SQL migrations.")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["up", "down"],
        default="up",
        help="up: apply pending migrations; down: roll back the most recent migration (default: up)",
    )
    parser.add_argument("--db", type=Path, default=DB_PATH, help="path to the SQLite database")
    args = parser.parse_args(argv)

    if args.command == "up":
        applied = migrate(args.db)
        if applied:
            print(f"Applied migrations to {args.db}: {', '.join(applied)}")
        else:
            print(f"Database {args.db} is up to date.")
    else:
        version = rollback(args.db)
        if version:
            print(f"Rolled back migration {version} on {args.db}")
        else:
            print(f"No migrations to roll back on {args.db}.")


if __name__ == "__main__":
    main()
