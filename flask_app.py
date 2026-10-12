"""Flask hosting entry point with the same API implementation as local/WSGI mode."""

from flask import Flask, Response, request

from wsgi import create_application


def create_app():
    app = Flask(__name__, static_folder=None)
    transport = create_application()

    def dispatch(**_parameters):
        # Pass the original stream through without consuming JSON here so the
        # shared handler retains request-size, origin and schema validation.
        return Response.from_app(transport, request.environ)

    routes = [
        ("/", ["GET"]),
        ("/styles.css", ["GET"]),
        ("/app.js", ["GET"]),
        ("/healthz", ["GET"]),
        ("/api/accounts", ["GET"]),
        ("/api/activity", ["GET"]),
        ("/api/export", ["POST"]),
        ("/api/accounts/<account_id>/state", ["POST"]),
        ("/api/accounts/<account_id>/brief", ["POST"]),
    ]
    for index, (path, methods) in enumerate(routes):
        app.add_url_rule(path, endpoint=f"signaldesk_{index}", view_func=dispatch,
                         methods=methods, provide_automatic_options=False)

    # Preserve the shared authenticated JSON responses for unknown routes
    # and unsupported methods instead of Flask's default HTML error pages.
    app.register_error_handler(404, lambda error: dispatch())
    app.register_error_handler(405, lambda error: Response.from_app(
        transport, dict(request.environ, REQUEST_METHOD="UNSUPPORTED")))
    return app
