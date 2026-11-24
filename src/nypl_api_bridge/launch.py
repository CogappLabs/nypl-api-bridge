"""`uv run nypl-chat`: load .env, check credentials, start the Streamlit app and open the browser."""

import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from dotenv import load_dotenv

PORT = 8501


def main() -> None:
    load_dotenv(Path.cwd() / ".env")  # existing environment variables win over .env

    if not os.environ.get("NYPL_API_TOKEN"):
        print("NYPL_API_TOKEN is missing. Add it to .env (see .env.example).", file=sys.stderr)
        raise SystemExit(1)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Note: ANTHROPIC_API_KEY not set; relying on an `ant auth login` profile.", file=sys.stderr)

    url = f"http://localhost:{PORT}"
    print(f"Starting NYPL chat at {url}  (Ctrl+C to stop)")
    threading.Timer(2.0, webbrowser.open, args=[url]).start()

    app = Path(__file__).with_name("app.py")
    command = [
        sys.executable, "-m", "streamlit", "run", str(app),
        "--server.port", str(PORT),
        "--server.headless", "true",  # no first-run prompt; we open the browser ourselves
        "--browser.gatherUsageStats", "false",
    ]  # fmt: skip
    try:
        subprocess.run(command, check=False)
    except KeyboardInterrupt:
        print("\nStopped.")
