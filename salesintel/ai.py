"""Versioned evidence triage. Offline mode is explicitly NOT an LLM."""

import hashlib
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from salesintel.storage import connect

ROOT = Path(__file__).resolve().parents[1]
DECISIONS = {"review", "research", "monitor"}
MODEL = "gpt-4.1-mini"


def context_for(account):
    # Only derived evidence goes to the model, never raw banners or sales notes.
    return {
        "eligible": account["eligible"], "age_days": account["age_days"],
        "ownership_verified": False,
        "signals": [{"id": signal["id"], "kind": signal["kind"],
                     "weight": signal["weight"], "evidence_ids": signal["evidence_ids"][:8]}
                    for signal in account["signals"]],
    }


def offline_classify(context, version="v2"):
    signals = context.get("signals", [])
    ids = list(dict.fromkeys(key for signal in signals for key in signal.get("evidence_ids", [])))[:8]
    age = context.get("age_days")
    fresh = age is not None and 0 <= age <= 30
    if version == "v1":
        decision = "review" if signals else "monitor"
        rationale = "Potential exposure signal present; review attribution and current relevance." if signals else \
                    "No supported exposure signal; monitor for additional evidence."
    elif not context.get("eligible"):
        decision = "research" if signals else "monitor"
        rationale = "Customer attribution is uncertain. Identify the service owner before any outreach."
    elif not fresh or not signals or not any(signal.get("weight", 0) > 0 for signal in signals):
        decision = "monitor"
        rationale = "Evidence is missing, stale, future-dated or has no current actionable signal."
    elif any(signal.get("weight", 0) >= 25 for signal in signals):
        decision = "review"
        rationale = "Recent higher-value evidence merits human review. Verify ownership and controls first."
    else:
        decision = "research"
        rationale = "A weaker observation warrants corroboration, not a vulnerability or purchase-intent claim."
    return {"decision": decision, "rationale": rationale, "evidence_ids": ids if signals else []}


def validate_result(result, context):
    if not isinstance(result, dict) or set(result) != {"decision", "rationale", "evidence_ids"}:
        raise ValueError("AI output does not match the required schema")
    if result["decision"] not in DECISIONS:
        raise ValueError("AI returned an unknown decision")
    rationale = result["rationale"]
    if not isinstance(rationale, str) or not 10 <= len(rationale) <= 600:
        raise ValueError("AI rationale must be between 10 and 600 characters")
    ids = result["evidence_ids"]
    allowed = {key for signal in context["signals"] for key in signal["evidence_ids"]}
    if not isinstance(ids, list) or len(ids) > 8 or any(not isinstance(key, str) or key not in allowed for key in ids):
        raise ValueError("AI cited evidence that was not provided")
    if context["signals"] and not ids:
        raise ValueError("AI must cite the provided evidence when signals exist")
    if re.search(r"\b(?:confirmed breach|has been breached|is vulnerable|unauthenticated|"
                 r"actively exploited|ready to buy|buying intent confirmed)\b", rationale, re.I):
        raise ValueError("AI made an unsupported security or purchase-intent claim")
    if result["decision"] == "review" and offline_classify(context, "v2")["decision"] != "review":
        raise ValueError("AI cannot escalate stale, weak or unattributed evidence to review")
    return result


def dollars_setting(name, default):
    value = float(os.getenv(name, default))
    if not math.isfinite(value) or value < 0:
        raise RuntimeError(f"{name} must be a finite non-negative number")
    return value


def reserve_budget(trace_id, amount, budget):
    today = datetime.now(timezone.utc).date().isoformat()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        spent = db.execute("SELECT COALESCE(SUM(cost_usd),0) FROM traces "
                           "WHERE substr(created_at,1,10)=?", (today,)).fetchone()[0]
        # All outstanding reservations count, including those left by a crash.
        reserved = db.execute("SELECT COALESCE(SUM(amount),0) FROM reservations").fetchone()[0]
        if spent + reserved + amount > budget:
            raise RuntimeError("Daily AI cost ceiling reached; no request was sent")
        db.execute("INSERT INTO reservations VALUES (?,?,?)", (trace_id, today, amount))


def draft_for(account, result):
    if not account["eligible"] or result["decision"] == "monitor":
        return {
            "subject": "Research before outreach",
            "body": "Do not send yet. Confirm customer ownership and collect current corroborating evidence. "
                    "This dataset does not contain verified contacts or buying intent.",
        }
    return {
        "subject": f"An external exposure review for {account['name']}",
        "body": f"Hi team,\n\nWe work with teams on understanding their external attack surface. "
                f"A passive dataset includes observations associated with {account['domain']}; "
                "we have not verified service ownership, security controls, or whether anything is vulnerable.\n\n"
                "Would the person responsible for infrastructure security be open to a short conversation "
                "about validating your external inventory and reviewing access controls?\n\n"
                "If this is not your service, please let us know and we will correct our records.\n\n"
                "[Your name]\n\n"
                "INTERNAL: Confirm ownership, find an appropriate contact lawfully, and review this draft before sending.",
    }


def brief_account(account, version="v2", mode=None):
    if version not in {"v1", "v2"}:
        raise ValueError("Unknown prompt version")
    if os.getenv("OPENAI_MODEL", MODEL) != MODEL:
        raise RuntimeError("Only gpt-4.1-mini is configured with a cost schedule; update code and pricing together")
    context = context_for(account)
    return run_triage(context, version, mode=mode, account_id=account["id"], account=account)


def run_triage(context, version="v2", mode=None, account_id="eval", account=None):
    """Shared app/eval entry point: same prompt, validation, budget and traces."""
    if version not in {"v1", "v2"}:
        raise ValueError("Unknown prompt version")
    prompt = (ROOT / "prompts" / "evidence-triage" / f"{version}.txt").read_text(encoding="utf-8")
    mode = mode or ("live" if os.environ.get("OPENAI_API_KEY") else "offline")
    if mode not in {"live", "offline"}:
        raise ValueError("Unknown AI mode")
    if mode == "live" and not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Live mode requires OPENAI_API_KEY; offline is not a substitute LLM result")
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(context, ensure_ascii=True)},
    ]
    request_body = {
        "model": MODEL, "messages": messages, "temperature": 0, "max_tokens": 256,
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "evidence_triage", "strict": True,
            "schema": {"type": "object", "additionalProperties": False,
                       "properties": {
                           "decision": {"type": "string", "enum": sorted(DECISIONS)},
                           "rationale": {"type": "string"},
                           "evidence_ids": {"type": "array", "items": {"type": "string"}},
                       }, "required": ["decision", "rationale", "evidence_ids"]},
        }},
    }
    encoded = json.dumps(request_body).encode()
    if len(encoded) > 24000:
        raise ValueError("AI request exceeds the bounded context limit")
    trace_id = uuid.uuid4().hex
    created = datetime.now(timezone.utc).isoformat()
    input_price = dollars_setting("AI_INPUT_USD_PER_MILLION", ".40")
    output_price = dollars_setting("AI_OUTPUT_USD_PER_MILLION", "1.60")
    # UTF-8 byte count + per-message overhead conservatively bounds input tokens.
    reservation = ((len(encoded) + 2000) * input_price + 256 * output_price) / 1_000_000
    if mode == "live":
        reserve_budget(trace_id, reservation, dollars_setting("AI_DAILY_BUDGET_USD", ".50"))
    started = time.monotonic()
    response_text, result, error = None, None, None
    input_tokens = output_tokens = 0
    cost = 0.0
    status = "ok"
    try:
        if mode == "offline":
            result = offline_classify(context, version)
            # v1 is retained as a deliberately weaker baseline; do not run
            # escalation validation in offline v1 comparisons.
            response_text = json.dumps(result)
            if version == "v2":
                validate_result(result, context)
        else:
            request = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions", data=encoded,
                headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
                         "Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError("Provider response exceeds the response limit")
            payload = json.loads(raw)
            usage = payload.get("usage", {})
            input_tokens = usage.get("prompt_tokens")
            output_tokens = usage.get("completion_tokens")
            if (not isinstance(input_tokens, int) or not isinstance(output_tokens, int)
                    or input_tokens < 0 or output_tokens < 0):
                raise ValueError("Provider did not return valid token usage")
            cost = (input_tokens * input_price + output_tokens * output_price) / 1_000_000
            response_text = payload["choices"][0]["message"]["content"]
            result = validate_result(json.loads(response_text), context)
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError) as exc:
        status = "error"
        # A failed/ambiguous billable request is charged at its reservation
        # estimate rather than silently disappearing from the budget.
        if mode == "live":
            cost = max(cost, reservation)
        error = f"{type(exc).__name__}: AI request failed or returned invalid evidence; no briefing accepted"
        raise RuntimeError(error) from exc
    finally:
        latency = round((time.monotonic() - started) * 1000, 2)
        with connect() as db:
            db.execute("INSERT INTO traces VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                trace_id, created, account_id, mode, MODEL if mode == "live" else "deterministic-policy",
                version, hashlib.sha256(prompt.encode()).hexdigest(),
                json.dumps(request_body), response_text, latency, input_tokens or 0, output_tokens or 0,
                cost, result.get("decision") if result and status == "ok" else None, status, error,
            ))
            db.execute("DELETE FROM reservations WHERE id=?", (trace_id,))
    output = dict(result, mode=mode, trace_id=trace_id, cost_usd=round(cost, 8))
    if account:
        output["draft"] = draft_for(account, result)
    return output
