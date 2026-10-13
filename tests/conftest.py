"""Shared pytest setup.

Runs before any test module imports `src`, so a developer's local `.env`
(real API keys, a custom DB path, a private resume dir) never leaks into the
test run.
"""

import os

os.environ["APPLY_AGENT_NO_DOTENV"] = "1"
# Don't persist the Gemini usage counter to the real data/ dir.
os.environ["GEMINI_USAGE_FILE"] = ""
