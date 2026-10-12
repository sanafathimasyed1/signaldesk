# SignalDesk

A local-first, explainable cybersecurity account-research workbench. It reads a real sample from the provided passive service-observation dataset, ranks *candidate* domain clusters for **human validation**, stores researcher dispositions and local AI traces, and exports selected research candidates. It does **not** infer company size, headquarters, industry, identity ownership, purchase intent, or vulnerability. It does not scan or contact companies.

## Start locally

Python **3.10+** can run the app with the checked-in sample. Install `requirements.txt` for Flask hosting and the complete test suite. The original local server is still standard-library-only. Re-importing the compressed source requires **Python 3.14+** for standard-library `compression.zstd`.

```powershell
python -m pip install -r requirements.txt
python main.py
```

Optional re-import on Python 3.14+: `python scripts\import_dataset.py --records 12000 --max-mb 32`.

Open <http://127.0.0.1:8000>. A sanitized, 12,000-observation snapshot and provenance are already checked in under `data/`. Importer downloads at most the selected compressed-byte cap, reads a sequential—not representative—prefix, and discards IPs, banners and certificate bodies. The request links back to the full Backblaze object and full metadata lives in `data/provenance.json`.

To store researcher notes and traces somewhere other than `var\signaldesk.sqlite`, configure `SIGNALDESK_DB` in your shell before running. To enable an on-demand live OpenAI briefing, explicitly configure `OPENAI_API_KEY` and, optionally, `OPENAI_MODEL=gpt-4.1-mini`, `AI_DAILY_BUDGET_USD=0.50`, `AI_INPUT_USD_PER_MILLION=0.40`, and `AI_OUTPUT_USD_PER_MILLION=1.60`. Never commit a key. The displayed rates are adjustable planning assumptions, not verified pricing quotes; confirm the chosen endpoint's billing before enabling. Without a key, offline briefings use and clearly label the deterministic policy; they are not LLM output. The rule engine builds the outreach *template*, and no message is sent.

## Prospecting

The score is a capped, transparent research heuristic: 20 candidate fit, up to 60 in individually current signal types, and up to 20 account recency. Stale or future-dated evidence does not receive a current weight; one fresh high-weight clue is required for Review now. Provider-owned, infrastructure and multi-domain observations default to Hold. Each detail pane explains score components and source caveats. See [`docs/PLANNING.md`](docs/PLANNING.md) and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Checks and reusable AI workflow

```powershell
python -m unittest discover -s tests -v
python evals\run.py --mode offline
```

Offline evaluation runs both prompt/policy versions on 24 synthetic cases and compares v2 against the preceding run. The measured run: v1 **45.8% accuracy / 0.360 macro-F1**; v2 **100% / 1.000** on these cases. That perfect score reflects labels encoding the same v2 policy; they are AI-authored, not independent human judgments or real customer data. It tests deterministic rules, **not a live language model**. See `skills/evidence-triage/SKILL.md` for inputs, output schema, triggers, limits and examples. Detailed traces are in local SQLite. No host, live LLM benchmark, independent human-labeled customers, or Loom link are represented as completed.

## Hosting and remaining deliverables

PythonAnywhere hosting is prepared with a Flask application factory (`flask_app.create_app`), a shared API adapter (`wsgi.py`), a Web-tab configuration template (`pythonanywhere_wsgi.py`), reviewer password protection, persistent SQLite under your account's home directory, and a public non-sensitive healthcheck. Follow [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) to install Flask in a virtualenv and configure WSGI. **No hosted URL is claimed until you actually deploy.** Hosting requires a 16+ character `SIGNALDESK_PASSWORD` and HTTPS. The free-hosting template deliberately disables live AI; outbound provider access is restricted on free accounts. This is one shared reviewer workspace, not an enterprise multiuser service.

A blind 24-case real-data packet and blank review sheet are in `evals/human-review/`; see [`evals/HUMAN_REVIEW.md`](evals/HUMAN_REVIEW.md). Human labels and live-model measurements are still pending. Import your completed labels using `python evals\human_review.py import`, then run the harness with `--dataset evals\human-review\human-labeled.jsonl --mode live`. Hosting and preparation do not complete those requirements by themselves. `docs/HOW_WE_BUILD.md` explains the development loop and limitations.
