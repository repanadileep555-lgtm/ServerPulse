import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from pwdlib import PasswordHash

from app.auth.jwt_service import JWTService, get_jwt_service
from app.db.db_pool import DatabasePool
from app.main import app
from db.migrate import migrate


class UserTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = self.enterContext(TemporaryDirectory())
        self.db_path = Path(directory) / "users.db"
        migrate(self.db_path)
        self.jwt_service = JWTService("test-user-secret-at-least-32-characters", "HS256", 30)
        app.dependency_overrides[get_jwt_service] = lambda: self.jwt_service
        self.addCleanup(app.dependency_overrides.pop, get_jwt_service)
        self.enterContext(
            patch("app.main.DatabasePool", return_value=DatabasePool(self.db_path))
        )
        self.client = self.enterContext(TestClient(app))
        self.credentials = {"username": "student", "password": "a-long-test-password"}

    def test_registration_hashes_password_and_login_issues_usable_jwt(self) -> None:
        created = self.client.post("/users/create", json=self.credentials)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(
            set(created.json()), {"id", "username", "is_admin", "enabled", "created_at"}
        )
        self.assertFalse(created.json()["is_admin"])
        self.assertTrue(created.json()["enabled"])
        with closing(sqlite3.connect(self.db_path)) as connection:
            stored_hash = connection.execute(
                "SELECT password_hash FROM users WHERE username = ?", ("student",)
            ).fetchone()[0]
        self.assertNotEqual(stored_hash, self.credentials["password"])
        self.assertTrue(PasswordHash.recommended().verify(self.credentials["password"], stored_hash))

        logged_in = self.client.post("/users/login", json=self.credentials)
        self.assertEqual(logged_in.status_code, 200)
        self.assertEqual(set(logged_in.json()), {"access_token", "refresh_token", "token_type"})
        self.assertEqual(logged_in.json()["token_type"], "bearer")
        claims = self.jwt_service.validate_access_token(logged_in.json()["access_token"])
        self.assertEqual(claims["sub"], str(created.json()["id"]))
        refresh_claims = self.jwt_service.validate_refresh_token(logged_in.json()["refresh_token"])
        self.assertEqual(refresh_claims["sub"], str(created.json()["id"]))
        with closing(sqlite3.connect(self.db_path)) as connection:
            last_login = connection.execute("SELECT last_login_at FROM users").fetchone()[0]
        self.assertIsNotNone(last_login)

    def test_me_reports_role_for_bearer_token(self) -> None:
        self.client.post("/users/create", json=self.credentials)
        token = self.client.post("/users/login", json=self.credentials).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        me = self.client.get("/users/me", headers=headers)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["username"], "student")
        self.assertFalse(me.json()["is_admin"])
        self.assertEqual(self.client.get("/users/me").status_code, 401)

        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute("UPDATE users SET is_admin = 1 WHERE username = 'student'")
            connection.commit()
        self.assertTrue(self.client.get("/users/me", headers=headers).json()["is_admin"])

    def test_duplicate_registration_does_not_replace_password(self) -> None:
        self.assertEqual(self.client.post("/users/create", json=self.credentials).status_code, 201)
        duplicate = self.client.post(
            "/users/create", json={**self.credentials, "password": "a-different-password"}
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(self.client.post("/users/login", json=self.credentials).status_code, 200)

    def test_invalid_and_disabled_accounts_have_same_login_error(self) -> None:
        self.client.post("/users/create", json=self.credentials)
        attempts = [
            {**self.credentials, "password": "wrong-password"},
            {**self.credentials, "username": "missing"},
            {**self.credentials, "username": "' OR 1=1 --"},
        ]
        for credentials in attempts:
            with self.subTest(username=credentials["username"]):
                response = self.client.post("/users/login", json=credentials)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json(), {"detail": "Invalid username or password"})
                self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")
        with closing(sqlite3.connect(self.db_path)) as connection:
            self.assertIsNone(connection.execute("SELECT last_login_at FROM users").fetchone()[0])
            connection.execute("UPDATE users SET enabled = 0")
            connection.commit()
        disabled = self.client.post("/users/login", json=self.credentials)
        self.assertEqual(disabled.status_code, 401)
        self.assertEqual(disabled.json(), {"detail": "Invalid username or password"})

    def test_registration_rejects_invalid_input_and_privilege_flags(self) -> None:
        invalid_requests = [
            {**self.credentials, "password": "short"},
            {**self.credentials, "password": "x" * 129},
            {**self.credentials, "username": "contains spaces"},
            {**self.credentials, "is_admin": True},
            {**self.credentials, "enabled": False},
            {"username": "student"},
        ]
        for payload in invalid_requests:
            with self.subTest(fields=list(payload)):
                self.assertEqual(self.client.post("/users/create", json=payload).status_code, 422)
        with closing(sqlite3.connect(self.db_path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)

    def test_refresh_token_issues_new_access_token_until_account_is_disabled(self) -> None:
        created = self.client.post("/users/create", json=self.credentials)
        logged_in = self.client.post("/users/login", json=self.credentials).json()

        refreshed = self.client.post("/users/refresh", json={"refresh_token": logged_in["refresh_token"]})
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(set(refreshed.json()), {"access_token", "token_type"})
        claims = self.jwt_service.validate_access_token(refreshed.json()["access_token"])
        self.assertEqual(claims["sub"], str(created.json()["id"]))

        access_as_refresh = self.client.post(
            "/users/refresh", json={"refresh_token": logged_in["access_token"]}
        )
        self.assertEqual(access_as_refresh.status_code, 401)

        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute("UPDATE users SET enabled = 0")
            connection.commit()
        disabled = self.client.post("/users/refresh", json={"refresh_token": logged_in["refresh_token"]})
        self.assertEqual(disabled.status_code, 401)
        self.assertEqual(disabled.json(), {"detail": "Invalid refresh token"})

    def test_admin_endpoint_requires_enabled_admin_token(self) -> None:
        self.client.post("/users/create", json=self.credentials)
        regular_token = self.client.post("/users/login", json=self.credentials).json()["access_token"]
        new_admin = {"username": "second-admin", "password": "another-long-password"}
        regular_headers = {"Authorization": f"Bearer {regular_token}"}

        self.assertEqual(self.client.post("/users/admins", json=new_admin).status_code, 401)
        forbidden = self.client.post("/users/admins", json=new_admin, headers=regular_headers)
        self.assertEqual(forbidden.status_code, 403)

        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute("UPDATE users SET is_admin = 1")
            connection.commit()
        admin_token = self.client.post("/users/login", json=self.credentials).json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        created = self.client.post("/users/admins", json=new_admin, headers=admin_headers)
        self.assertEqual(created.status_code, 201)
        self.assertTrue(created.json()["is_admin"])
        duplicate = self.client.post("/users/admins", json=new_admin, headers=admin_headers)
        self.assertEqual(duplicate.status_code, 409)

    def test_user_directory_is_admin_only(self) -> None:
        self.client.post("/users/create", json=self.credentials)
        regular_token = self.client.post("/users/login", json=self.credentials).json()["access_token"]
        regular_headers = {"Authorization": f"Bearer {regular_token}"}
        self.assertEqual(self.client.get("/users", headers=regular_headers).status_code, 403)

        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute("UPDATE users SET is_admin = 1")
            connection.commit()
        admin_token = self.client.post("/users/login", json=self.credentials).json()["access_token"]
        listed = self.client.get("/users", headers={"Authorization": f"Bearer {admin_token}"})
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([user["username"] for user in listed.json()], ["student"])
