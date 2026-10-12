"""SignalDesk: a dependency-free sales workbench for passive service observations."""

import argparse
import csv
import io
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from salesintel.accounts import build_accounts
from salesintel.ai import brief_account
from salesintel.storage import connect, initialize

ROOT = Path(__file__).resolve().parent


def load_accounts():
    source = ROOT / "data" / "observations.jsonl"
    if not source.exists():
        raise SystemExit("Dataset missing. Run: python scripts\\import_dataset.py")
    with source.open(encoding="utf-8") as handle:
        accounts = build_accounts(json.loads(line) for line in handle if line.strip())
    metadata = json.loads((ROOT / "data" / "provenance.json").read_text(encoding="utf-8"))
    return {account["id"]: account for account in accounts}, metadata


class Handler(BaseHTTPRequestHandler):
    accounts = {}
    metadata = {}
    loaded_at = 0
    refresh_lock = threading.Lock()

    def refresh_accounts(self):
        if time.monotonic() - type(self).loaded_at < 60:
            return
        with type(self).refresh_lock:
            if time.monotonic() - type(self).loaded_at >= 60:
                type(self).accounts, type(self).metadata = load_accounts()
                type(self).loaded_at = time.monotonic()

    def log_message(self, fmt, *args):
        # Do not put account identifiers or request bodies in console logs.
        path = urlparse(self.path).path
        if path.startswith("/api/accounts/"):
            parts = path.split("/")
            path = "/api/accounts/{id}/" + (parts[-1] if len(parts) == 5 else "{operation}")
        print(f"{self.command} {path} {fmt % args}")

    def respond(self, status, payload, content_type="application/json"):
        if content_type == "application/json":
            payload = json.dumps(payload, ensure_ascii=True).encode()
        elif isinstance(payload, str):
            payload = payload.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
                         "base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(payload)

    def state_accounts(self):
        with connect() as db:
            states = {row["account_id"]: dict(row) for row in db.execute("SELECT * FROM account_state")}
        return [dict(account, status=states.get(key, {}).get("status", "New"),
                     notes=states.get(key, {}).get("notes", ""))
                for key, account in self.accounts.items()]

    def do_GET(self):
        self.refresh_accounts()
        path = urlparse(self.path).path
        if path == "/api/accounts":
            with connect() as db:
                spend = db.execute(
                    "SELECT COALESCE(SUM(cost_usd),0) FROM traces WHERE substr(created_at,1,10)=?",
                    (datetime.now(timezone.utc).date().isoformat(),)).fetchone()[0]
                reserved = db.execute("SELECT COALESCE(SUM(amount),0) FROM reservations WHERE day=?",
                                      (datetime.now(timezone.utc).date().isoformat(),)).fetchone()[0]
            self.respond(200, {
                "accounts": self.state_accounts(),
                "meta": dict(self.metadata, accounts_count=len(self.accounts)),
                "ai": {"mode": "live" if os.environ.get("OPENAI_API_KEY") else "offline",
                       "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                       "prompt_version": "v2", "budget_usd": float(os.getenv("AI_DAILY_BUDGET_USD", ".50")),
                       "spent_usd": round(spend, 6), "reserved_usd": round(reserved, 6)},
            })
        elif path == "/api/activity":
            with connect() as db:
                activity = [dict(row) for row in db.execute(
                    "SELECT * FROM account_state ORDER BY updated_at DESC LIMIT 100")]
                traces = [dict(row) for row in db.execute(
                    "SELECT id,created_at,mode,model,prompt_version,latency_ms,cost_usd,"
                    "decision,status FROM traces ORDER BY created_at DESC LIMIT 100")]
            for row in activity:
                row["name"] = self.accounts.get(row["account_id"], {}).get("name", "Unknown")
            self.respond(200, {"activity": activity, "traces": traces})
        elif path.startswith("/api/"):
            self.respond(404, {"error": "API route not found"})
        else:
            files = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/styles.css": ("styles.css", "text/css; charset=utf-8"),
                     "/app.js": ("app.js", "text/javascript; charset=utf-8")}
            if path not in files:
                self.respond(404, {"error": "Not found"})
                return
            filename, content_type = files[path]
            self.respond(200, (ROOT / "static" / filename).read_bytes(), content_type)

    def do_POST(self):
        self.refresh_accounts()
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            self.respond(403, {"error": "Cross-origin writes are not permitted"})
            return
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.respond(415, {"error": "Expected application/json"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16384:
                raise ValueError("Request must be between 1 and 16384 bytes")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object")
            path = urlparse(self.path).path
            parts = path.strip("/").split("/")
            if path == "/api/export":
                ids = body.get("ids", [])
                if not isinstance(ids, list) or any(not isinstance(key, str) or key not in self.accounts for key in ids):
                    raise ValueError("Export contains unknown account IDs")
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(["Account", "Domain", "Observed country", "Segment", "Score",
                                 "Priority", "Status", "Next step", "Notes"])
                for account in self.state_accounts():
                    if account["id"] not in ids:
                        continue
                    values = [account["name"], account["domain"], account["country"],
                              account["segment"], account["score"], account["priority"],
                              account["status"], account["attribution"], account["notes"]]
                    writer.writerow([("'" + str(v)) if str(v).lstrip().startswith(("=", "+", "-", "@"))
                                     else v for v in values])
                self.respond(200, output.getvalue(), "text/csv; charset=utf-8")
            elif len(parts) == 4 and parts[:2] == ["api", "accounts"] and parts[2] in self.accounts:
                account_id, operation = parts[2:]
                if operation == "state":
                    status, notes = body.get("status"), body.get("notes", "")
                    if status not in ("New", "Shortlisted", "Contacted", "Disqualified"):
                        raise ValueError("Invalid account status")
                    if not isinstance(notes, str) or len(notes) > 4000:
                        raise ValueError("Notes must be text of at most 4000 characters")
                    with connect() as db:
                        db.execute("INSERT INTO account_state VALUES (?,?,?,?) "
                                   "ON CONFLICT(account_id) DO UPDATE SET status=excluded.status,"
                                   "notes=excluded.notes,updated_at=excluded.updated_at",
                                   (account_id, status, notes, datetime.now(timezone.utc).isoformat()))
                    self.respond(200, {"status": status, "notes": notes})
                elif operation == "brief":
                    version = body.get("version", "v2")
                    if version != "v2":
                        raise ValueError("The workbench uses v2; v1 is available only in the eval harness")
                    result = brief_account(self.accounts[account_id], version)
                    self.respond(200, result)
                else:
                    self.respond(404, {"error": "Account operation not found"})
            else:
                self.respond(404, {"error": "Account or route not found"})
        except (ValueError, json.JSONDecodeError) as exc:
            self.respond(400, {"error": str(exc)})
        except (RuntimeError, TimeoutError) as exc:
            self.respond(503, {"error": str(exc)})
        except sqlite3.Error:
            self.respond(503, {"error": "Local storage is unavailable"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    args = parser.parse_args()
    initialize()
    Handler.accounts, Handler.metadata = load_accounts()
    Handler.loaded_at = time.monotonic()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"SignalDesk: http://{args.host}:{args.port} ({len(Handler.accounts)} account candidates)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
