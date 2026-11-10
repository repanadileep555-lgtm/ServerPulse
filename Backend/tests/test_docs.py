import re
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class DocumentationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(patch("app.main.DatabasePool"))

    def test_documentation_assets_are_served_locally(self) -> None:
        with TestClient(app) as client:
            for path in ("/docs", "/redoc"):
                with self.subTest(path=path):
                    response = client.get(path)
                    self.assertEqual(response.status_code, 200)
                    assets = re.findall(
                        r'<(?:script|link)\b[^>]*(?:src|href)="([^"]+)"',
                        response.text,
                    )
                    self.assertTrue(assets)
                    for asset in assets:
                        self.assertTrue(asset.startswith("/static-offline-docs/"))
                        resource = client.get(asset, follow_redirects=False)
                        self.assertEqual(resource.status_code, 200, asset)
                        self.assertTrue(resource.content, asset)
                        if asset.endswith(".js"):
                            self.assertIn("javascript", resource.headers["content-type"])
                        elif asset.endswith(".css"):
                            self.assertIn("text/css", resource.headers["content-type"])

    def test_documentation_keeps_api_schema_and_oauth_redirect(self) -> None:
        with TestClient(app) as client:
            schema = client.get("/openapi.json")
            self.assertEqual(schema.status_code, 200)
            self.assertIn("/", schema.json()["paths"])
            self.assertIn("/health", schema.json()["paths"])
            self.assertNotIn("/docs", schema.json()["paths"])
            self.assertEqual(client.get("/docs/oauth2-redirect").status_code, 200)
            self.assertEqual(
                client.get("/").json(),
                {"message": "Welcome to ServerPulse API", "status": "Running"},
            )
