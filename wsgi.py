"""WSGI transport for the existing API; no second router or framework needed."""

import json
import os
import sqlite3
import time
from email.message import Message
from http import HTTPStatus

from main import Handler, load_accounts
from salesintel.storage import initialize


class WSGIHandler(Handler):
    def __init__(self, environ):
        self.command = environ["REQUEST_METHOD"]
        self.path = environ.get("PATH_INFO", "/")
        self.headers = Message()
        for key, value in environ.items():
            if key.startswith("HTTP_"):
                self.headers[key[5:].replace("_", "-")] = value
        for key in ("CONTENT_TYPE", "CONTENT_LENGTH"):
            if environ.get(key):
                self.headers[key.replace("_", "-")] = environ[key]
        self.rfile = environ["wsgi.input"]
        self.result = None

    def respond(self, status, payload, content_type="application/json", extra_headers=None):
        if content_type == "application/json":
            payload = json.dumps(payload, ensure_ascii=True).encode()
        elif isinstance(payload, str):
            payload = payload.encode()
        headers = [
            ("Content-Type", content_type), ("Content-Length", str(len(payload))),
            ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
            ("Content-Security-Policy",
             "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
             "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"),
        ]
        headers.extend((extra_headers or {}).items())
        self.result = (f"{status} {HTTPStatus(status).phrase}", headers, payload)


def create_application():
    """Hosting fails closed if private reviewer credentials haven't been configured."""
    if len(os.getenv("SIGNALDESK_PASSWORD", "")) < 16:
        raise RuntimeError("WSGI hosting requires SIGNALDESK_PASSWORD of at least 16 characters")
    initialize()
    WSGIHandler.accounts, WSGIHandler.metadata = load_accounts()
    WSGIHandler.loaded_at = time.monotonic()

    def application(environ, start_response):
        handler = WSGIHandler(environ)
        try:
            if handler.command in {"GET", "HEAD"}:
                handler.do_GET()
            elif handler.command == "POST":
                handler.do_POST()
            else:
                handler.respond(405, {"error": "Method not allowed"}, extra_headers={"Allow": "GET, HEAD, POST"})
        except sqlite3.Error:
            handler.respond(503, {"error": "Workspace storage is unavailable"})
        status, headers, payload = handler.result
        start_response(status, headers)
        return [b"" if handler.command == "HEAD" else payload]

    return application
