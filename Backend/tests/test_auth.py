import unittest
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth.jwt_service import (
    ACCESS_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
    JWTService,
    TokenError,
    get_jwt_service,
)
from app.middleware.auth_middleware import AuthenticatedUser, get_current_user

SECRET = "test-secret-with-enough-length-0123456789"


def make_service(
    expire_minutes: int = 30,
    secret: str = SECRET,
    refresh_days: int = 1,
) -> JWTService:
    return JWTService(secret, "HS256", expire_minutes, refresh_days)


class JWTServiceTests(unittest.TestCase):
    def test_refresh_token_round_trip_returns_subject_with_one_day_lifetime(self) -> None:
        service = make_service()
        token = service.create_refresh_token("alice")

        claims = service.validate_refresh_token(token)

        self.assertEqual(claims["sub"], "alice")
        self.assertEqual(claims["type"], REFRESH_TOKEN_TYPE)
        self.assertEqual(claims["exp"] - claims["iat"], 24 * 60 * 60)

    def test_expired_refresh_token_is_rejected(self) -> None:
        token = make_service(refresh_days=-1).create_refresh_token("alice")

        with self.assertRaises(TokenError):
            make_service().validate_refresh_token(token)

    def test_refresh_token_is_rejected_as_access_token(self) -> None:
        token = make_service().create_refresh_token("alice")

        with self.assertRaisesRegex(TokenError, "must be 'access'"):
            make_service().validate_access_token(token)

    def test_access_token_is_rejected_as_refresh_token(self) -> None:
        token = make_service().create_access_token("alice")

        with self.assertRaisesRegex(TokenError, "must be 'refresh'"):
            make_service().validate_refresh_token(token)

    def test_access_token_round_trip_returns_subject(self) -> None:
        service = make_service()
        token = service.create_access_token("alice", {"role": "admin"})

        claims = service.validate_access_token(token)

        self.assertEqual(claims["sub"], "alice")
        self.assertEqual(claims["role"], "admin")
        self.assertEqual(claims["type"], ACCESS_TOKEN_TYPE)

    def test_extra_claims_cannot_override_reserved_claims(self) -> None:
        service = make_service()
        token = service.create_access_token("alice", {"sub": "mallory", "type": "refresh"})

        self.assertEqual(service.validate_access_token(token)["sub"], "alice")

    def test_expired_token_is_rejected(self) -> None:
        token = make_service(expire_minutes=-1).create_access_token("alice")

        with self.assertRaises(TokenError):
            make_service().validate_access_token(token)

    def test_token_signed_with_other_secret_is_rejected(self) -> None:
        token = make_service(secret="another-secret-with-enough-length-0123456").create_access_token("alice")

        with self.assertRaises(TokenError):
            make_service().validate_access_token(token)

    def test_token_of_other_type_is_rejected(self) -> None:
        now = datetime.now(UTC)
        token = jwt.encode(
            {"sub": "alice", "type": "refresh", "iat": now, "exp": now + timedelta(minutes=5)},
            SECRET,
            algorithm="HS256",
        )

        with self.assertRaisesRegex(TokenError, "must be 'access'"):
            make_service().validate_access_token(token)

    def test_token_missing_required_claims_is_rejected(self) -> None:
        token = jwt.encode({"sub": "alice"}, SECRET, algorithm="HS256")

        with self.assertRaises(TokenError):
            make_service().validate_access_token(token)

    def test_malformed_token_is_rejected(self) -> None:
        with self.assertRaises(TokenError):
            make_service().validate_access_token("not-a-jwt")


class AuthMiddlewareTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()

        @app.get("/protected")
        async def protected(user: AuthenticatedUser = Depends(get_current_user)) -> dict[str, str]:
            return {"subject": user.subject}

        app.dependency_overrides[get_jwt_service] = make_service
        self.client = TestClient(app)

    def test_missing_credentials_returns_401_with_challenge(self) -> None:
        response = self.client.get("/protected")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")

    def test_invalid_token_returns_401(self) -> None:
        response = self.client.get("/protected", headers={"Authorization": "Bearer garbage"})

        self.assertEqual(response.status_code, 401)

    def test_valid_token_grants_access(self) -> None:
        token = make_service().create_access_token("alice")

        response = self.client.get("/protected", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"subject": "alice"})


if __name__ == "__main__":
    unittest.main()
