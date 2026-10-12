import base64
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

from wsgi import create_application


class WSGITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "SIGNALDESK_DB": str(Path(self.directory.name) / "wsgi.sqlite"),
            "SIGNALDESK_USERNAME": "reviewer", "SIGNALDESK_PASSWORD": "test-password-long-enough",
            "OPENAI_API_KEY": "",
        })
        self.env.start()
        self.application = create_application()

    def tearDown(self):
        self.env.stop()
        self.directory.cleanup()

    def request(self, path, method="GET", data=None, authenticated=True, **headers):
        environ = {}
        setup_testing_defaults(environ)
        environ.update(PATH_INFO=path, REQUEST_METHOD=method, HTTP_HOST="localhost")
        if authenticated:
            environ["HTTP_AUTHORIZATION"] = "Basic " + base64.b64encode(
                b"reviewer:test-password-long-enough").decode()
        if data is not None:
            body = json.dumps(data).encode()
            environ.update(CONTENT_TYPE="application/json", CONTENT_LENGTH=str(len(body)),
                           **{"wsgi.input": io.BytesIO(body)})
        environ.update(headers)
        result = {}
        def start_response(status, response_headers):
            result["status"] = int(status.split()[0])
            result["headers"] = dict(response_headers)
        result["body"] = b"".join(self.application(environ, start_response))
        return result

    def test_missing_hosting_password_fails_closed(self):
        with patch.dict(os.environ, {"SIGNALDESK_PASSWORD": ""}):
            with self.assertRaises(RuntimeError):
                create_application()

    def test_health_and_auth_gate(self):
        self.assertEqual(self.request("/healthz", authenticated=False)["status"], 200)
        for path in ("/", "/styles.css", "/app.js", "/api/accounts", "/api/activity"):
            result = self.request(path, authenticated=False)
            self.assertEqual(result["status"], 401)
            self.assertIn("WWW-Authenticate", result["headers"])

    def test_static_files_and_head(self):
        for path in ("/", "/styles.css", "/app.js"):
            self.assertEqual(self.request(path)["status"], 200)
        result = self.request("/", method="HEAD")
        self.assertEqual(result["body"], b"")
        self.assertGreater(int(result["headers"]["Content-Length"]), 0)

    def test_real_accounts_and_state_persistence(self):
        response = self.request("/api/accounts")
        self.assertEqual(response["status"], 200)
        payload = json.loads(response["body"])
        self.assertEqual(payload["ai"]["mode"], "offline")
        account = next(item for item in payload["accounts"] if item["eligible"])
        path = f"/api/accounts/{account['id']}/state"
        result = self.request(path, "POST", {"status": "Shortlisted", "notes": "WSGI test note"})
        self.assertEqual(result["status"], 200)
        # A new hosted worker sees SQLite state, not only in-memory state.
        self.application = create_application()
        activity = json.loads(self.request("/api/activity")["body"])
        self.assertEqual(activity["activity"][0]["notes"], "WSGI test note")
        export = self.request("/api/export", "POST", {"ids": [account["id"]]})
        self.assertEqual(export["status"], 200)
        self.assertIn(b"WSGI test note", export["body"])
        brief = self.request(f"/api/accounts/{account['id']}/brief", "POST", {"version": "v2"})
        self.assertEqual(brief["status"], 200)
        self.assertEqual(json.loads(brief["body"])["mode"], "offline")

    def test_bad_requests_are_not_accepted(self):
        self.assertEqual(self.request("/api/export", "POST", [], HTTP_ORIGIN="https://wrong.example")["status"], 403)
        self.assertEqual(self.request("/api/export", "POST", [])["status"], 400)
        self.assertEqual(self.request("/api/accounts", "DELETE")["status"], 405)
        self.assertEqual(self.request("/unknown")["status"], 404)


if __name__ == "__main__":
    unittest.main()
