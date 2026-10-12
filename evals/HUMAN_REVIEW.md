# Independent review of real source cases

Twenty-four cases from the checked-in real source sample are frozen in `human-review/`. They deliberately cover higher-value clues, weaker configuration clues, no current ranked clue, and provider/ownership ambiguity. This stratified convenience sample is **not** a representative market sample; precision measured on it does not estimate market conversion.

Read `blind-packet.json` before any model output or score. Do **not** read `contexts.json`, the synthetic expected labels, or the app's priorities while assigning labels. The contexts file is needed by the harness but contains the derived input/weights, which would bias a blind judgment.

For each case, decide what a sales researcher should do next using the observations and attribution caveat:

| Label | Meaning |
|---|---|
| review | Credible, recent evidence deserves a person's immediate ownership/control validation. Not permission to contact or scan. |
| research | Corroborate weaker evidence or identify the real service owner before treating this as an account lead. |
| monitor | No useful current evidence supports prioritizing this case. |
| insufficient | You cannot make a defensible judgment from these fields; explain what is missing. |

Use your independent judgment rather than recreating the score formula. A reachable data-service port does not prove authentication is absent; a CVE annotation may be wrong; TLS/certificate clues do not prove a breach or purchase intent. Provider org and infrastructure country are not verified company identity or headquarters. Record low confidence when warranted, never invent facts.

Fill every row in `labels.csv`: label, confidence (`low/medium/high`), explanation, reviewer name or pseudonym, and ISO timestamp (e.g. `2026-10-12T22:00:00+05:30`). Keep identity truthful. A spreadsheet can edit the CSV; preserve all IDs and header names. Do not paste an LLM's predicted label into your own review.

Import with `python evals\human_review.py import`. It refuses incomplete or invalid labels. `insufficient` cases are explicitly excluded; if fewer than 20 remain, prepare and independently review an additional packet rather than silently assigning answers.

For another frozen packet, run `python evals\human_review.py prepare --directory evals\human-review-2`. The preparation tool never overwrites the existing packet. Record any second-reviewer disagreements and adjudication separately. Labels are immutable after measuring the held-out set unless a documented factual correction is required.

Run `python evals\run.py --dataset evals\human-review\human-labeled.jsonl --mode live --output evals\results\human-live.json` with an API key privately configured. Share the labelled set, reviewer methodology, results, actual errors and limitations—not just the headline accuracy.
