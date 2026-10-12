# Architecture and decisions

## Components and data path

`scripts/import_dataset.py` streams a strictly bounded compressed prefix over HTTPS, requires complete newline-delimited records, normalizes allowlisted fields, and writes `data/observations.jsonl` plus import provenance atomically. `salesintel/accounts.py` deduplicates observation keys, groups single plausible domains versus provider/ambiguous observations, derives date-qualified clues, assigns transparent scores, and classifies Research / Monitor / Hold / Review. No source addresses, raw banners, certificate chains, credentials or vulnerability descriptions leave the import step.

`main.py` serves vanilla static UI and same-origin JSON routes on loopback by default. Candidate results are rebuilt from the imported sample on a 60-second cache expiration; SQLite stores researcher disposition/notes, requests/traces and live-call budget reservations in `var/signaldesk.sqlite`. Notes and trace requests are local-workspace data: do not deploy publicly without authentication, access controls, approved retention, and a privacy review. The API validates request size, JSON/content type, same-host Origin for writes, account IDs, status and notes length. CSV export escapes spreadsheet-formula-leading values.

`static/` is a dependency-free responsive workbench with search, observed-country / segment / priority filters, pagination, evidence detail, analyst disposition, explicit attribution caveat, CSV shortlist export, and Activity/AI traces. It does not link to or probe observed ports or IPs. PythonAnywhere deployment is prepared but not executed; no hosted link is claimed.

`wsgi.py` provides a standard-library WSGI transport that reuses the existing handler routes and policies. `pythonanywhere_wsgi.py` exports the callable for the host and loads credentials from a private JSON file outside the repository. Hosted workers use Python 3.10+, serve the checked-in sample without the compressed-source importer, and retain SQLite under the account home directory. The free-host configuration explicitly disables live AI because outbound provider access is not assumed.

## Rules versus LLM

**Rules are authoritative** for normalization and provider suppression, whether attribution is ambiguous, signal evidence eligibility, per-observation freshness, score, ranking, review threshold, allowed evidence IDs, budget checks, schema validation and output safety. These are stable, testable decisions and should not be entrusted to a probabilistic text model. A missing or future timestamp produces no recency credit. A higher-level review decision requires at least one current higher-weight signal; multiple weak certificate/TLS/unverified-CVE hints never accumulate into that queue. Organization and observed country do not masquerade as company and territory data.

The optional `v2` LLM call is a narrow, **on-demand, human-reviewed explanatory triage**—not a critical classifier and not an autonomous SDR. It receives a maximum 24 KB payload of derived fields and eight evidence IDs, but no raw banners, IPs, certificates, contact details or user notes. It returns strict-schema JSON with a decision, rationale and cited IDs. Local policy rejects unseen IDs, unsafe claims, stale escalation and attribution escalation. The backend generates the outreach *template* with deterministic code; the model does not generate personalized claims or names. With no configured API key, the app uses the same exact decision rules for a clearly labeled offline explanation, discloses that it did not call an LLM, and costs $0. This local behavior is never described as an LLM result.

## Tracing, prompts, and evaluations

Versioned text under `prompts/evidence-triage/` is SHA-256-hashed on each invocation. SQLite table `traces` records UTC timestamp, account ID, mode/model, prompt version/hash, JSON request and response, measured latency, provider token usage, configured-rate cost, decision and accepted/error outcome. `reservations` holds an atomic pre-call estimate and prevents concurrent calls from exceeding a configurable UTC daily ceiling. Failed ambiguous/billable requests consume their conservative reserved estimate; reservations left by process crashes remain reserved. Account notes are separate from LLM request content. All offline invocations are also traceable, explicitly using `deterministic-policy`.

`evals/labeled-v1.jsonl` contains 24 illustrative synthetic policy cases (not customer examples or independent human judgments). `python evals\run.py` runs the shared application inference path for v1 and v2, saves detailed cases and per-call traces, reports accuracy and per-class precision/recall/F1 plus macro-F1, distinguishes errors from rejected decisions, and compares prompt v2 against a prior saved run. The checked-in deterministic offline run scores v1 at **45.8% accuracy / 0.360 macro-F1** and v2 at **100% / 1.000** (24 cases; v2 per-class precision and recall are 1.0). The apparent perfect v2 result is an explicit weakness, not proof of prospecting quality: its synthetic labels encode the same decision policy and no human has independently labeled customer evidence. Running offline evaluates the deterministic fallback, not an LLM. `python evals\run.py --mode live` requires an explicit API key, calls the live model, writes measured observations, and spends the per-day limit. The case set needs blind review by domain experts and ongoing data drift / precision tracking before sales use.

## Model, cost and operating limit

One configured API model only: `gpt-4.1-mini`, JSON schema, `temperature=0`, `max_tokens=256`, at most 24 KB input, invoked only when a user asks for a briefing. Do not swap model IDs without confirming support for the strict response schema and updating/configuring the rate. No expensive judgement model is justified until independent human scoring establishes benefit over deterministic policy.

The code’s default **planning rates** (editable `AI_INPUT_USD_PER_MILLION` `$0.40` and `AI_OUTPUT_USD_PER_MILLION` `$1.60`) are transparent assumptions, **not a verified provider price quote**; reconcile them with the selected endpoint, region/tier, cache, taxes and actual billing before activation. The estimate from metered usage is:

`daily cost = calls/day × (input tokens × input USD/1M + output tokens × output USD/1M) / 1,000,000`.

Example planning workload: 250 on-demand triages/day × (350 input tokens × $0.40/M + 100 output tokens × $1.60/M) = **$0.075/day** or **$2.25 per 30-day month**, excluding retries and tokenization overhead. (The current estimated maximum reservation uses JSON byte count plus an overhead allowance and up to 256 completion tokens instead.) Configure a hard $0.50 UTC/day ceiling by default; decline requests before sending them once reserved+measured daily spending exceeds that limit. Offline policy calls are zero-cost. Cost ceilings are operational guardrails, not assurances of invoice accuracy.

## Risks and trade-offs

* A first-prefix sample is fast, transparent and cheap, but biased; it will miss observations and cannot estimate TAM or sales lift.
* A provider suppression list will miss resellers and can suppress real account domains; current single-domain eligibility is merely a hypothesis.
* The available data lacks an ICP, firmographics, HQ/territory, buyer, control status, buying signal and outcomes. A richer account score should wait for consented enrichment and label provenance.
* Score weights are a transparent sales-research heuristic, not inferred or calibrated. Synthetic eval accuracy is not evidence of field performance.
* PythonAnywhere preparation includes a shared reviewer Basic-auth gate (HTTPS required), persistent account-home SQLite and a private credentials file. It is still a take-home demo, not a hardened multiuser service. Personal roles, tenant isolation, login rate limiting and formal retention policies remain production requirements. See `DEPLOYMENT.md`; no deployment or human/live evaluation is claimed as completed.
