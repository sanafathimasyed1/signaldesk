import unittest
from datetime import datetime, timezone

from salesintel.accounts import build_accounts, clean_domain, normalize

NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)


def observation(port=443, **changes):
    record = {"port": port, "ip_str": "192.0.2.1", "timestamp": "2026-10-08T12:00:00",
              "org": "Hosting Provider", "domains": ["example.org"],
              "location": {"country_code": "AU"}, "transport": "tcp"}
    record.update(changes)
    return record


class AccountTests(unittest.TestCase):
    def account(self, *records):
        return build_accounts(records or [observation()], now=NOW)[0]

    def test_real_candidate_is_domain_not_provider(self):
        account = self.account()
        self.assertEqual(account["name"], "example.org")
        self.assertEqual(account["provider"], "Hosting Provider")
        self.assertTrue(account["eligible"])
        self.assertIn("ownership unverified", account["attribution"])

    def test_provider_only_is_hold(self):
        account = self.account(observation(6379, domains=["amazonaws.com"]))
        self.assertFalse(account["eligible"])
        self.assertEqual(account["priority"], "Hold")

    def test_ambiguous_domains_are_not_fabricated_accounts(self):
        account = self.account(observation(6379, domains=["one.org", "two.org"]))
        self.assertFalse(account["eligible"])
        self.assertEqual(account["domain"], "")

    def test_hosted_customer_domain_is_kept(self):
        account = self.account(observation(domains=["amazonaws.com", "customer.org"]))
        self.assertEqual(account["domain"], "customer.org")

    def test_open_port_does_not_mean_unauthenticated(self):
        account = self.account(observation(6379))
        self.assertEqual(account["score"], 70)
        self.assertEqual(account["priority"], "Review now")
        self.assertIn("authentication unknown", account["signals"][0]["label"])

    def test_negative_tls_versions_are_not_supported(self):
        account = self.account(observation(ssl={"versions": ["-TLSv1", "-TLSv1.1", "TLSv1.3"]}))
        self.assertEqual(account["signals"], [])

    def test_positive_legacy_tls_is_weaker_research(self):
        account = self.account(observation(ssl={"versions": ["TLSv1.1"]}))
        self.assertEqual(account["priority"], "Research")
        self.assertEqual(account["signal_score"], 15)

    def test_expired_cert_only_research(self):
        account = self.account(observation(ssl={"cert": {"expired": True}}))
        self.assertEqual(account["priority"], "Research")

    def test_weak_signals_do_not_stack_into_review(self):
        account = self.account(observation(
            ssl={"versions": ["TLSv1"], "cert": {"expired": True}},
            vulns={"CVE-2026-0001": {"verified": False}}))
        self.assertEqual(account["score"], 75)
        self.assertEqual(account["priority"], "Research")

    def test_provider_reverse_hostname_not_customer(self):
        account = self.account(observation(6379, domains=["ip-51-210-239.eu"]))
        self.assertFalse(account["eligible"])

    def test_provider_rules_apply_to_previously_normalized_data(self):
        record = normalize(observation(6379))
        record["candidate_domains"] = ["arvixe.com"]
        account = self.account(record)
        self.assertFalse(account["eligible"])

    def test_unverified_cve_is_not_review(self):
        account = self.account(observation(vulns={"CVE-2026-0001": {"verified": False}}))
        self.assertEqual(account["signal_score"], 5)
        self.assertEqual(account["priority"], "Research")

    def test_verified_cve_requires_literal_boolean(self):
        account = self.account(observation(vulns={"CVE-2026-0001": {"verified": "true"}}))
        self.assertEqual(account["signal_score"], 5)

    def test_verified_cve_is_source_only(self):
        account = self.account(observation(vulns={"CVE-2026-0001": {"verified": True}}))
        self.assertIn("independently validate", account["signals"][0]["label"])

    def test_stale_signal_not_rejuvenated_by_fresh_web(self):
        account = self.account(observation(6379, timestamp="2026-08-01T00:00:00"),
                               observation(443))
        self.assertEqual(account["signal_score"], 0)
        self.assertEqual(account["priority"], "Monitor")

    def test_future_observations_not_fresh(self):
        account = self.account(observation(6379, timestamp="2027-01-01T00:00:00"))
        self.assertIsNone(account["age_days"])
        self.assertEqual(account["signal_score"], 0)
        self.assertEqual(account["freshness_score"], 0)

    def test_missing_timestamp_never_fresh(self):
        account = self.account(observation(6379, timestamp=None))
        self.assertEqual(account["freshness_score"], 0)

    def test_duplicate_records_and_signal_types_not_inflated(self):
        record = observation(6379)
        account = self.account(record, record, observation(3306))
        self.assertEqual(len(account["evidence"]), 2)
        self.assertEqual(account["signal_score"], 30)

    def test_score_cap(self):
        account = self.account(observation(6379), observation(3389),
                               observation(443, ssl={"versions": ["TLSv1"], "cert": {"expired": True}}))
        self.assertEqual(account["score"], 100)

    def test_private_banners_ips_and_certificates_discarded(self):
        record = normalize(observation(data="password=secret", ssl={"chain": ["cert"]}))
        for key in ("data", "ip_str", "ssl", "ip"):
            self.assertNotIn(key, record)

    def test_domains_reject_payloads(self):
        for value in ("<script>.com", "https://example.com", "-bad.com", "bad..com", "192.0.2.1"):
            self.assertIsNone(clean_domain(value))

    def test_invalid_ports(self):
        for port in (0, 65536, "443", True, None):
            self.assertIsNone(normalize(observation(port)))


if __name__ == "__main__":
    unittest.main()
