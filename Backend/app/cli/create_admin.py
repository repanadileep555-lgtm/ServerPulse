import argparse
import asyncio
import getpass
import sys
from pathlib import Path

from pydantic import ValidationError

from app.auth.jwt_service import get_jwt_service
from app.conf.config import DB_PATH
from app.db.db_pool import DatabasePool
from app.schemas.user import RegisterUserRequest
from app.services.user_service import DuplicateUsernameError, UserService


async def _create_admin(db_path: Path, request: RegisterUserRequest) -> str:
    async with DatabasePool(db_path, pool_size=1) as pool:
        service = UserService(pool, get_jwt_service())
        user = await service.create_admin(request)
    return f"Created admin '{user.username}' (id {user.id}) in {db_path}"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Create an administrator account. Run database migrations first."
    )
    parser.add_argument("--username", help="username for the new admin account (prompted if omitted)")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="path to the SQLite database")
    args = parser.parse_args(argv)

    username = args.username or input("Username: ").strip()
    password = getpass.getpass("Password: ")
    if getpass.getpass("Confirm password: ") != password:
        parser.error("passwords do not match")

    try:
        request = RegisterUserRequest(username=username, password=password)
    except ValidationError as exc:
        parser.error(exc.errors()[0]["msg"])

    try:
        print(asyncio.run(_create_admin(args.db, request)))
    except DuplicateUsernameError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
