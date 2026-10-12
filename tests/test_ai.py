import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from salesintel.ai import offline_classify, reserve_budget, run_triage, validate_result
from salesintel.storage import connect, initialize


def context(weight=30, age=3, eligible=True):
    return {"eligible": eligible, "age_days": age, "ownership_verified": False,
            "signals": [{"id": "data-service", "kind": "data-service",
                         "weight": weight, "evidence_ids": ["e1"]}]}


class AITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"SIGNALDESK_DB": str(Path(self.directory.name) / "test.sqlite")})
        self.env.start()
        initialize()

    def tearDown(self):
        self.env.stop()
        self.directory.cleanup()

    def test_policy_review(self):
        self.assertEqual(offline_classify(context())["decision"], "review")

    def test_weak_or_unattributed_are_research(self):
        self.assertEqual(offline_classify(context(weight=5))["decision"], "research")
        self.assertEqual(offline_classify(context(eligible=False))["decision"], "research")

    def test_stale_future_and_absent_dates_monitor(self):
        for age in (31, -1, None):
            self.assertEqual(offline_classify(context(age=age))["decision"], "monitor")

    def test_stale_signal_in_fresh_account_monitor(self):
        self.assertEqual(offline_classify(context(weight=0))["decision"], "monitor")

    def test_unsupported_ids_rejected(self):
        result = {"decision": "review", "rationale": "Please validate the current evidence.", "evidence_ids": ["invented"]}
        with self.assertRaises(ValueError):
            validate_result(result, context())

    def test_unsupported_claim_rejected(self):
        result = {"decision": "review", "rationale": "This company is vulnerable.", "evidence_ids": ["e1"]}
        with self.assertRaises(ValueError):
            validate_result(result, context())

    def test_escalation_guardrail(self):
        result = {"decision": "review", "rationale": "Please validate the current evidence.", "evidence_ids": ["e1"]}
        with self.assertRaises(ValueError):
            validate_result(result, context(eligible=False))

    def test_offline_trace_not_misrepresented_as_llm(self):
        result = run_triage(context(), mode="offline")
        self.assertEqual(result["mode"], "offline")
        with connect() as db:
            trace = dict(db.execute("SELECT * FROM traces").fetchone())
        self.assertEqual(trace["model"], "deterministic-policy")
        self.assertEqual(trace["cost_usd"], 0)
        self.assertEqual(trace["prompt_version"], "v2")
        self.assertEqual(len(trace["prompt_sha256"]), 64)
        self.assertIn("messages", json.loads(trace["request"]))

    def test_cost_cap_counts_outstanding_reservations(self):
        reserve_budget("one", .4, .5)
        with self.assertRaises(RuntimeError):
            reserve_budget("two", .2, .5)

    def test_live_requires_key(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with self.assertRaises(RuntimeError):
                run_triage(context(), mode="live")

    def test_provider_failure_is_traced_and_charged(self):
        import urllib.error
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-not-real"}):
            with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("failure")):
                with self.assertRaises(RuntimeError):
                    run_triage(context(), mode="live")
        with connect() as db:
            trace = dict(db.execute("SELECT * FROM traces").fetchone())
            count = db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]
        self.assertEqual(trace["status"], "error")
        self.assertGreater(trace["cost_usd"], 0)
        self.assertEqual(count, 0)
        self.assertNotIn("test-not-real", trace["request"])

    def test_live_token_math_and_output_validation(self):
        result = {"decision": "review", "rationale": "Validate ownership and access controls.", "evidence_ids": ["e1"]}
        response = {"choices": [{"message": {"content": json.dumps(result)}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self, maximum):
                return json.dumps(response).encode()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-not-real"}):
            with patch("urllib.request.urlopen", return_value=Response()):
                output = run_triage(context(), mode="live")
        self.assertAlmostEqual(output["cost_usd"], .00012)
        self.assertEqual(output["decision"], "review")


if __name__ == "__main__":
    unittest.main()
