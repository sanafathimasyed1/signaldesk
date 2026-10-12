import hashlib
import re
from collections import Counter
from datetime import datetime, timezone

INFRA_DOMAINS = {
    "amazonaws.com", "googleusercontent.com", "cloudfront.net", "incapdns.net",
    "cloudflare.com", "akamaiedge.net", "akamai.net", "azure.com", "windows.net",
    "digitaloceanspaces.com", "compute.amazonaws.com", "spectrum.com", "comcast.net",
    "your-server.de", "vultrusercontent.com", "linodeusercontent.com",
    "ovh.net", "ovhcloud.com", "hetzner.com", "hetzner.de", "arvixe.com",
    "ondigitalocean.com", "flyio.net", "nazwa.pl", "iijmobile.jp", "rima-tde.net",
}
DATABASE_PORTS = {3306, 5432, 6379, 9200, 27017, 9042, 11211}
REMOTE_PORTS = {3389, 5900, 5901}
WEIGHTS = {"data-service": 30, "remote-access": 25, "expired-cert": 15,
           "legacy-tls": 15, "verified-cve": 35, "reported-cve": 5}
LABELS = {
    "data-service": "Public data-service port observed; authentication unknown",
    "remote-access": "Remote-access service observed; controls unknown",
    "expired-cert": "Certificate reported expired at observation",
    "legacy-tls": "Legacy TLS negotiation reported",
    "verified-cve": "Source marks a CVE verified; independently validate",
    "reported-cve": "Unverified CVE association; not proof of vulnerability",
}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()[:20]


def clean_domain(value):
    if not isinstance(value, str):
        return None
    value = value.lower().rstrip(".")
    if len(value) > 253 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", value):
        return None
    labels = value.split(".")
    if len(labels) < 2 or not re.fullmatch(r"[a-z]{2,63}", labels[-1]):
        return None
    if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in labels):
        return None
    return value


def is_infra(domain):
    return (any(domain == suffix or domain.endswith("." + suffix) for suffix in INFRA_DOMAINS)
            or bool(re.fullmatch(r"ip-\d+-\d+-\d+\.eu", domain)))


def parse_time(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (ValueError, AttributeError, TypeError):
        return None


def normalize(record):
    """Retain allowlisted fields only: never persist banners, IPs or certificate blobs."""
    domains = sorted({domain for item in record.get("domains", []) if (domain := clean_domain(item))})
    candidates = [domain for domain in domains if not is_infra(domain)]
    port = record.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        return None
    observed = parse_time(record.get("timestamp"))
    location = record.get("location") or {}
    ssl = record.get("ssl") or {}
    flags = []
    if port in DATABASE_PORTS:
        flags.append("data-service")
    if port in REMOTE_PORTS:
        flags.append("remote-access")
    if (ssl.get("cert") or {}).get("expired") is True:
        flags.append("expired-cert")
    if any(value in {"TLSv1", "TLSv1.0", "TLSv1.1"} for value in ssl.get("versions", [])):
        flags.append("legacy-tls")
    vulns = record.get("vulns") or {}
    if isinstance(vulns, dict):
        verified = any(isinstance(meta, dict) and meta.get("verified") is True for meta in vulns.values())
        if verified:
            flags.append("verified-cve")
        elif vulns:
            flags.append("reported-cve")
    provider = str(record.get("org") or "Unknown provider")[:180]
    country = str(location.get("country_code") or "Unknown")[:10]
    identity = "|".join([str(record.get("ip_str", "")), str(port),
                                       str(record.get("transport", "tcp")), str(record.get("timestamp", ""))])
    return {"id": digest(identity), "port": port, "transport": str(record.get("transport", "tcp"))[:10],
            "observed_at": observed.isoformat() if observed else None, "country": country,
            "product": str(record.get("product") or "")[:100], "flags": flags,
            "candidate_domains": candidates, "provider": provider}


def build_accounts(records, now=None):
    now = now or datetime.now(timezone.utc)
    grouped = {}
    for record in records:
        # Importer has already normalized the privacy-safe, checked-in dataset.
        evidence = record if "candidate_domains" in record else normalize(record)
        if evidence is None:
            continue
        candidates = sorted({domain for value in evidence["candidate_domains"]
                             if (domain := clean_domain(value)) and not is_infra(domain)})
        evidence = dict(evidence, candidate_domains=candidates)
        # Ambiguous multi-domain hosting is NOT expanded into multiple sales targets.
        if len(candidates) == 1:
            key, domain, eligible = candidates[0], candidates[0], True
        else:
            key, domain, eligible = "infra:" + evidence["provider"], "", False
        account = grouped.setdefault(key, {
            "id": digest(key), "name": domain or evidence["provider"],
            "domain": domain, "provider": evidence["provider"], "eligible": eligible, "evidence": [],
        })
        if evidence["id"] not in {item["id"] for item in account["evidence"]}:
            account["evidence"].append(evidence)
    for account in grouped.values():
        observations = account["evidence"]
        countries = sorted({item["country"] for item in observations})
        account["countries"] = countries
        account["country"] = Counter(item["country"] for item in observations).most_common(1)[0][0]
        valid_times = [value for item in observations
                       if (value := parse_time(item["observed_at"])) is not None and value <= now]
        latest = max(valid_times) if valid_times else None
        age = (now - latest).total_seconds() / 86400 if latest else None
        account["latest_seen"] = latest.isoformat() if latest else None
        account["age_days"] = round(age, 1) if age is not None else None
        # Age applies per signal, not just per account (a fresh harmless web record
        # must never rejuvenate an old database observation).
        signals = []
        for flag, weight in WEIGHTS.items():
            matching = [item for item in observations if flag in item["flags"]]
            if not matching:
                continue
            fresh = any((seen := parse_time(item["observed_at"])) is not None
                        and 0 <= (now - seen).total_seconds() <= 30 * 86400 for item in matching)
            signals.append({"id": flag, "kind": flag, "label": LABELS[flag],
                            "weight": weight if fresh else 0,
                            "evidence_ids": [item["id"] for item in matching]})
        signal_score = min(60, sum(signal["weight"] for signal in signals))
        fit = 20 if account["eligible"] else 0
        freshness = 20 if age is not None and age <= 7 else 10 if age is not None and age <= 30 else 0
        score = fit + signal_score + freshness
        if not account["eligible"]:
            priority = "Hold"
        elif any(signal["weight"] >= 25 for signal in signals) and freshness > 0 and score >= 55:
            priority = "Review now"
        elif signal_score > 0:
            priority = "Research"
        else:
            priority = "Monitor"
        ports = {item["port"] for item in observations}
        account.update({
            "signals": signals, "fit_score": fit, "signal_score": signal_score,
            "freshness_score": freshness, "score": score, "priority": priority,
            "segment": "Data services" if ports & DATABASE_PORTS else
                       "Remote access" if ports & REMOTE_PORTS else
                       "Web & TLS" if ports & {80, 443, 8443, 8080} else "Other services",
            "attribution": "Single non-provider domain candidate; ownership unverified. "
                           "Confirm the account and service owner before outreach." if account["eligible"] else
                           "Provider-only or multi-domain observation; cannot identify a customer. "
                           "Hold until ownership is enriched.",
            "status": "New", "notes": "",
        })
    return sorted(grouped.values(), key=lambda item: (-item["score"], item["name"]))
