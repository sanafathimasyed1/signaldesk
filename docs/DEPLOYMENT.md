# Hosting SignalDesk on PythonAnywhere

## Prepared, not deployed

The application supports PythonAnywhere through a standard WSGI adapter that reuses the existing HTTP/API behavior without additional dependencies. The hosted runtime needs Python **3.10 or later** and the checked-in sanitized sample. Python 3.14 is required only for the optional compressed-source importer, which should not run during deployment.

`pythonanywhere_wsgi.py` is a configuration template, not a running public app. Free-tier availability, CPU/storage quotas, web-app renewal and outbound internet restrictions depend on your current account. Confirm the available offer before signup. No paid disk or container is required. SQLite is kept in your home directory, survives ordinary web-app reloads and uses account storage quota.

## 1. Publish the latest code

In your Windows PowerShell terminal:

```powershell
cd C:\Users\ssana\IdeaProjects\PythonProject1
git add main.py wsgi.py pythonanywhere_wsgi.py tests .gitignore .env.example README.md docs
git add -u
git commit -m "Replace hosting configuration with PythonAnywhere WSGI support" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push -u origin main
```

Skip `git commit` if these changes are already committed. Sign in to GitHub when prompted. Confirm that your repository contains `wsgi.py`, `pythonanywhere_wsgi.py`, and these instructions. Never upload private config, passwords, keys, `.env`, SQLite files or virtual environments.

## 2. Create an account and upload

Create a PythonAnywhere account at <https://www.pythonanywhere.com/> (or its regional site). Note your **PythonAnywhere username**; it may differ from GitHub's. In **Consoles**, open a **Bash** console and run:

```bash
git clone https://github.com/sanafathimasyed1/signaldesk.git
cd ~/signaldesk
```

These commands run on PythonAnywhere's Linux host, not your local PowerShell. If already cloned, use `git pull --ff-only`. A private GitHub repository requires authentication; never embed a personal token in the URL. Alternatively upload a GitHub source ZIP through PythonAnywhere's Files tab, extract it and ensure the project directory is named `signaldesk`.

Do not run `python main.py` or keep a console web server alive to publish the app. PythonAnywhere serves it through the Web tab's WSGI worker.

## 3. Create private reviewer configuration

In that Bash console, use an available Python 3 executable (e.g. `python3.13`) to generate a private password configuration:

```bash
python3 -c 'import json,secrets,pathlib; p=pathlib.Path.home()/".signaldesk-config.json"; assert not p.exists(), "Config already exists; do not overwrite credentials"; p.write_text(json.dumps({"password":secrets.token_urlsafe(24)})); p.chmod(0o600); print("Private reviewer configuration created")'
```

This file is **outside the repository**, restricted to your account, and never committed. To retrieve the generated password privately, view the file through your own Files tab; don't paste it in chat, screenshots or source. Reviewer username is `reviewer`. Share credentials with the assessor separately from the app URL.

## 4. Configure Web / WSGI

1. Open **Web → Add a new web app**.
2. Choose **Manual configuration** and an available Python **3.10+** version. No Flask installation, virtualenv or pip requirements are needed because this app is standard-library WSGI.
3. Set source code and working directory, if shown, to `/home/YOUR_USERNAME/signaldesk`.
4. Open the **WSGI configuration file** linked in the Web tab.
5. Replace its example contents with the contents of the repository's `pythonanywhere_wsgi.py`.
6. Change `ACCOUNT_USERNAME = "YOUR_PYTHONANYWHERE_USERNAME"` to your actual PythonAnywhere account name.
7. Save and click **Reload**.

Do **not** configure PythonAnywhere static-file mappings for `/`, `/app.js` or `/styles.css`: the application serves and password-protects these routes. The template loads the private JSON password, initializes the database at `/home/YOUR_USERNAME/.signaldesk/signaldesk.sqlite`, loads the checked-in sample and exports the WSGI `application` callable.

Use the HTTPS site address shown in the Web tab; its hostname depends on the account/region. Don't invent a URL or share localhost. Enable/force HTTPS using the platform settings where available; reviewer Basic authentication must never be used over plain HTTP.

## 5. Confirm the hosted demo

Open the site in a private browser window. Root and API routes should ask for the reviewer login. `/healthz` is intentionally public and returns only `{"status":"ok"}`. After login, confirm search, filters, evidence details, shortlist export, saved notes, and offline briefings work. Save a harmless note, reload the web app, and confirm it remains.

If you see an error, use the Web tab's error/server logs:

- Missing password config: create it at your account home path, not inside the project.
- Import error for `main` or `wsgi`: confirm username, project path and that latest code is uploaded.
- Unsupported Python syntax: select Python 3.10+ in the Web tab.
- Source file missing: make sure `data/observations.jsonl` and `data/provenance.json` were uploaded.
- SQLite error: confirm your home directory is writable and account disk quota is not exhausted.

Each credential holder can see/edit the same workspace. This is shared assessor access, not per-person authorization. Closing the private browser session ends normal browser credential caching. Protect backups, avoid confidential prospect notes, and remove/revoke assessor credentials when the demonstration ends. Free sites may require renewal; follow the account dashboard notices.

## 6. Live AI and remaining evaluation

The template deliberately removes `OPENAI_API_KEY` from the web worker environment: this free-hosted demo runs **offline rules, not a live model**. PythonAnywhere free accounts restrict outbound access, and successful calls to a model provider are not assumed. If you later upgrade/use approved connectivity, explicitly configure secrets outside Git, confirm provider access/pricing, keep a durable daily spending limit and record real call results before presenting it as live AI.

Independent human-labelled evaluation remains pending. Read `evals/human-review/blind-packet.json`, fill `labels.csv` yourself using `evals/HUMAN_REVIEW.md`, then run locally:

```powershell
python evals\human_review.py import
python evals\run.py --dataset evals\human-review\human-labeled.jsonl --mode offline
# With your provider API key privately configured on your own computer:
python evals\run.py --dataset evals\human-review\human-labeled.jsonl --mode live --output evals\results\human-live.json
```

A free hosted offline demo and a separately measured local LLM workflow must be described as such; do not imply the public app uses the model if it does not. Hosting preparation is not deployment, and a blank review packet is not human-labelled ground truth.

References: [PythonAnywhere WSGI setup](https://help.pythonanywhere.com/pages/WSGI/), [Python versions](https://help.pythonanywhere.com/pages/PythonVersions/), [free-account outbound restrictions](https://help.pythonanywhere.com/pages/403ForbiddenError/).
