import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from main import Handler
from salesintel.accounts import build_accounts
from salesintel.storage import initialize


class APITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {
            "SIGNALDESK_DB": str(Path(self.directory.name) / "api.sqlite"), "OPENAI_API_KEY": "",
        })
        self.environment.start()
        initialize()
        accounts = build_accounts([{
            "port": 6379, "domains": ["example.org"], "org": "Host",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "location": {"country_code": "AU"},
        }])
        class TestHandler(Handler):
            def log_message(self, *args):
                pass
        TestHandler.accounts = {item["id"]: item for item in accounts}
        TestHandler.metadata = {"records_imported": 1}
        TestHandler.loaded_at = time.monotonic()
        self.account_id = accounts[0]["id"]
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.environment.stop()
        self.directory.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        extra = {"Content-Type": "application/json"}
        extra.update(headers or {})
        connection.request(method, path, json.dumps(body) if body is not None else None, extra)
        response = connection.getresponse()
        data = response.read().decode()
        status = response.status
        connection.close()
        return status, data

    def test_accounts_and_state_persist(self):
        status, body = self.request("GET", "/api/accounts")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["ai"]["mode"], "offline")
        status, body = self.request("POST", f"/api/accounts/{self.account_id}/state",
                                    {"status": "Shortlisted", "notes": "Validate ownership"})
        self.assertEqual(status, 200)
        _, body = self.request("GET", "/api/accounts")
        self.assertEqual(json.loads(body)["accounts"][0]["notes"], "Validate ownership")
        _, body = self.request("GET", "/api/activity")
        self.assertEqual(json.loads(body)["activity"][0]["status"], "Shortlisted")

    def test_brief_cites_real_evidence(self):
        status, body = self.request("POST", f"/api/accounts/{self.account_id}/brief", {"version": "v2"})
        self.assertEqual(status, 200)
        brief = json.loads(body)
        self.assertEqual(brief["decision"], "review")
        self.assertEqual(brief["mode"], "offline")
        self.assertIn("not verified", brief["draft"]["body"])
        self.assertTrue(brief["evidence_ids"])

    def test_workbench_rejects_unsafe_baseline(self):
        status, _ = self.request("POST", f"/api/accounts/{self.account_id}/brief", {"version": "v1"})
        self.assertEqual(status, 400)

    def test_unknown_account_and_invalid_status(self):
        status, _ = self.request("POST", "/api/accounts/unknown/state", {"status": "New"})
        self.assertEqual(status, 404)
        status, _ = self.request("POST", f"/api/accounts/{self.account_id}/state", {"status": "Invalid"})
        self.assertEqual(status, 400)

    def test_cross_origin_write_blocked(self):
        status, _ = self.request("POST", f"/api/accounts/{self.account_id}/state", {"status": "New"},
                                 {"Origin": "https://example.net"})
        self.assertEqual(status, 403)

    def test_export_formula_injection_neutralized(self):
        self.request("POST", f"/api/accounts/{self.account_id}/state",
                     {"status": "Shortlisted", "notes": " =HYPERLINK(\"https://bad.example\")"})
        status, body = self.request("POST", "/api/export", {"ids": [self.account_id]})
        self.assertEqual(status, 200)
        self.assertIn("' =HYPERLINK", body)
        self.assertIn("example.org", body)


if __name__ == "__main__":
    unittest.main()
