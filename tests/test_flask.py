import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask_app import create_app


class FlaskTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "SIGNALDESK_DB": str(Path(self.directory.name) / "flask.sqlite"),
            "SIGNALDESK_USERNAME": "reviewer", "SIGNALDESK_PASSWORD": "test-password-long-enough",
            "OPENAI_API_KEY": "",
        })
        self.env.start()
        self.app = create_app()
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Basic " + base64.b64encode(
            b"reviewer:test-password-long-enough").decode()}

    def tearDown(self):
        self.env.stop()
        self.directory.cleanup()

    def test_flask_login_and_static_assets(self):
        for path in ("/", "/styles.css", "/app.js", "/api/accounts", "/api/activity", "/unknown"):
            self.assertEqual(self.client.get(path).status_code, 401)
        for path in ("/", "/styles.css", "/app.js"):
            result = self.client.get(path, headers=self.headers)
            self.assertEqual(result.status_code, 200)
            self.assertIn("Content-Security-Policy", result.headers)
        self.assertEqual(self.client.get("/healthz").json, {"status": "ok"})
        self.assertEqual(self.client.head("/", headers=self.headers).data, b"")

    def test_flask_research_workflow_persists(self):
        account = next(item for item in self.client.get("/api/accounts", headers=self.headers).json["accounts"]
                       if item["eligible"])
        path = f"/api/accounts/{account['id']}"
        result = self.client.post(path + "/state", json={"status": "Shortlisted", "notes": "Flask note"},
                                  headers=self.headers)
        self.assertEqual(result.status_code, 200)
        another_worker = create_app().test_client()
        activity = another_worker.get("/api/activity", headers=self.headers).json
        self.assertEqual(activity["activity"][0]["notes"], "Flask note")
        brief = self.client.post(path + "/brief", json={"version": "v2"}, headers=self.headers)
        self.assertEqual(brief.status_code, 200)
        self.assertEqual(brief.json["mode"], "offline")
        export = self.client.post("/api/export", json={"ids": [account["id"]]}, headers=self.headers)
        self.assertEqual(export.status_code, 200)
        self.assertIn(b"Flask note", export.data)

    def test_flask_preserves_validation_and_errors(self):
        self.assertEqual(self.client.post("/api/export", json=[],
                                          headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post("/api/export", json={"ids": []},
                                          headers={**self.headers, "Origin": "https://wrong.example"}).status_code, 403)
        self.assertEqual(self.client.post("/api/export", data="x" * 20000,
                                          content_type="application/json",
                                          headers=self.headers).status_code, 400)
        self.assertEqual(self.client.get("/missing", headers=self.headers).status_code, 404)
        result = self.client.delete("/api/accounts", headers=self.headers)
        self.assertEqual(result.status_code, 405)
        self.assertEqual(result.json["error"], "Method not allowed")


if __name__ == "__main__":
    unittest.main()
