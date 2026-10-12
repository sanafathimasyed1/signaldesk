"""Copy into PythonAnywhere's Web-tab WSGI file; edit ACCOUNT_USERNAME."""

import json
import os
import sys
from pathlib import Path

ACCOUNT_USERNAME = "YOUR_PYTHONANYWHERE_USERNAME"
home = Path("/home") / ACCOUNT_USERNAME
project = home / "signaldesk"

# Keep this configuration OUTSIDE the repository, restricted to your own account.
config = json.loads((home / ".signaldesk-config.json").read_text(encoding="utf-8"))
os.environ["SIGNALDESK_USERNAME"] = "reviewer"
os.environ["SIGNALDESK_PASSWORD"] = config["password"]
os.environ["SIGNALDESK_DB"] = str(home / ".signaldesk" / "signaldesk.sqlite")
os.environ.pop("OPENAI_API_KEY", None)

sys.path.insert(0, str(project))
from wsgi import create_application

application = create_application()
