"""Vercel entrypoint: Vercel serves the ASGI `app` defined here. The server code is in src/nypl_api_bridge/remote.py.

Run locally with: NYPL_API_TOKEN=... uv run uvicorn index:app --port 8000
"""

import sys
from pathlib import Path

# Make the src/ package importable whether or not Vercel installs the project itself.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from nypl_api_bridge.remote import create_app_from_env  # noqa: E402

app = create_app_from_env()
