"""Run once locally to obtain a YouTube refresh token for GitHub Actions secrets."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
SECRETS_FILE = Path("client_secrets.json")


def main() -> int:
    if not SECRETS_FILE.exists():
        print(f"Place your OAuth client JSON at: {SECRETS_FILE.resolve()}")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(SECRETS_FILE), SCOPES)
    creds = flow.run_local_server(port=8081, prompt="consent")

    Path("youtube_token.json").write_text(creds.to_json(), encoding="utf-8")

    secrets = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    client = secrets.get("installed") or secrets.get("web") or {}

    print("\nAdd these GitHub repository secrets:\n")
    print(f"YOUTUBE_CLIENT_ID={client.get('client_id', '')}")
    print(f"YOUTUBE_CLIENT_SECRET={client.get('client_secret', '')}")
    print(f"YOUTUBE_REFRESH_TOKEN={creds.refresh_token}")
    print("\nSaved local token to youtube_token.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
