# Hosting SignalDesk on Render

## Current status

The repository now includes a Render Blueprint, Docker packaging, an authenticated reviewer workspace, and a persistent SQLite disk configuration. **These are deployment preparation, not a deployed app or live URL.** Deployment requires the repository owner to connect GitHub, create a Render account and approve the paid service/disk. This is a small shared take-home demonstration, not enterprise multiuser production software.

## Publish the code

Run in your own PowerShell terminal and sign in to GitHub when asked:

```powershell
cd C:\Users\ssana\IdeaProjects\PythonProject1
git push -u origin main
```

If you previously pushed `main`, the same command publishes the newest commit. Verify that GitHub shows `render.yaml`, `Dockerfile`, and `docs/DEPLOYMENT.md`. Do not upload `.env`, API keys, private database files or the virtual environment.

## Create the hosted app

1. Open <https://dashboard.render.com/>. Create an account or sign in with GitHub.
2. Choose **New → Blueprint** and connect `sanafathimasyed1/signaldesk`, branch `main`. Allow Render access to that repository only if possible.
3. Render reads `render.yaml`. Review the **Starter web service** and **1 GB persistent disk** costs before approving. Pricing is Render's current dashboard pricing, not a figure guaranteed by this repository.
4. Supply the prompted `SIGNALDESK_PASSWORD`: a randomly generated, unique password of at least 16 characters. Set it in Render, not source code or chat. Username is `reviewer`. Keep the password private and share it separately with the assessor.
5. Create the resources. The Docker image uses Python 3.14, serves the checked-in source sample, listens on Render's `PORT`, and writes SQLite to `/var/data/signaldesk.sqlite`. There is no full-source download during deployment.
6. Wait for the deployment to report **Live**. Copy the actual HTTPS service URL from Render; don't invent a URL or use localhost.
7. Open it in a private browser window. Before login, `/` and `/api/accounts` must require authentication. `/healthz` is intentionally public and reveals only `{"status":"ok"}`. Sign in using the reviewer credentials; confirm account search, details, notes, draft creation and CSV export.
8. Save a harmless note, manually restart the service in Render and confirm it remains. SQLite is on the persistent disk so notes, traces and daily spending are not reset by ordinary restarts.

Render terminates HTTPS in front of the container; browser Basic authentication must be used **only through that HTTPS URL**. The server refuses network binding without a sufficiently long configured password. This is a single shared reviewer identity, not personal accounts/roles. Anyone given those credentials can see/edit all workspace data; enter no confidential prospect/customer data. Basic-auth sign-out normally requires closing the private browser session.

The persistent disk limits this SQLite demo to one service instance and can cause deployment downtime. Monitor usage and export backups using SQLite's backup facilities rather than copying an active WAL database. Backups, privacy retention policies, login rate limiting, a hardened application server, individual roles and organization isolation remain necessary for a true production service.

## Optional live AI

The initial deployment deliberately has **no API key** and shows "Offline rules · no LLM." That is an honest working demo, not measured live AI. If you choose to enable the live feature:

1. Create a provider account with billing and an appropriate project-scoped key.
2. Add `OPENAI_API_KEY` as a secret environment variable in Render's service dashboard. Never add it to `render.yaml` or GitHub.
3. Confirm `gpt-4.1-mini` availability, strict-schema compatibility and actual input/output prices. Update `AI_INPUT_USD_PER_MILLION` and `AI_OUTPUT_USD_PER_MILLION`; the defaults are planning assumptions.
4. Keep `AI_DAILY_BUDGET_USD=0.50` or a smaller chosen limit. Enable provider-side spending controls too.
5. Restart, confirm the UI says live mode, request one briefing and inspect trace usage/cost. Do not distribute reviewer credentials beyond the intended assessors.

## Finish the evaluation requirement

The existing synthetic set remains a rule regression suite, **not the requested human-labelled LLM evaluation**. A frozen real-data review packet has been generated:

- Read `evals/human-review/blind-packet.json` (actual source evidence; no score/model prediction).
- Fill `evals/human-review/labels.csv` yourself. Each row needs `label` (`review`, `research`, `monitor`, or `insufficient`), `confidence` (`low`, `medium`, `high`), `reason`, `reviewer`, and an ISO date/time in `reviewed_at`.
- Use the guidance in `evals/HUMAN_REVIEW.md`. A second blind reviewer is useful; record disagreements instead of adjusting labels to match predictions.
- Then run:

```powershell
python evals\human_review.py import
python evals\run.py --dataset evals\human-review\human-labeled.jsonl --mode offline
# Set your API key privately in the shell, then measure the actual model:
python evals\run.py --dataset evals\human-review\human-labeled.jsonl --mode live --output evals\results\human-live.json
```

The harness checks labels and compares results only against the same data hash and mode. Errors count as failed predictions, not successful safe fallbacks. It reports per-class precision/recall/F1, acceptance, token-derived cost including failed-call reservations, mean latency and prompt hashes. The retained v1 baseline can have live outputs rejected by current safety validation; those failures remain visible in results. Freeze a baseline before changing the prompt; don't tune repeatedly against your entire held-out set.

**Do not claim all requirements complete until** the real hosted URL works, you have independently labelled 20–30 evaluable cases, you have measured the live core feature (if enabled), and your submission documents those results and limitations. Hosting alone does not supply the missing human judgments.

References: [Render Blueprints](https://render.com/docs/infrastructure-as-code), [Blueprint specification](https://render.com/docs/blueprint-spec), [persistent disks](https://render.com/docs/disks).
