import json
import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def main() -> None:
    """
    Kjør lokalt for å få refresh token.

    Forutsetter at du har en OAuth Client (Desktop app) og en client secrets JSON.
    Pek til filen med env var GOOGLE_CLIENT_SECRETS_JSON, f.eks.:
      set GOOGLE_CLIENT_SECRETS_JSON=C:\\path\\to\\client_secret.json

    Scriptet starter en lokal browser-flow og skriver ut refresh token.
    """
    secrets_path = os.getenv("GOOGLE_CLIENT_SECRETS_JSON")
    if not secrets_path:
        raise SystemExit("Missing GOOGLE_CLIENT_SECRETS_JSON env var pointing to client secrets .json")

    p = Path(secrets_path)
    if not p.exists():
        raise SystemExit(f"Client secrets file not found: {p}")

    flow = InstalledAppFlow.from_client_secrets_file(str(p), scopes=SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline", include_granted_scopes="true")

    if not creds.refresh_token:
        raise SystemExit("No refresh token received. Ensure prompt='consent' and access_type='offline'.")

    # Print values for Sliplane secrets
    client_config = json.loads(p.read_text(encoding="utf-8"))
    # client_config structure: {"installed": {"client_id":..., "client_secret":...}}
    installed = client_config.get("installed") or client_config.get("web") or {}

    print("Set these env vars in Sliplane:")
    print(f"GOOGLE_CLIENT_ID={installed.get('client_id')}")
    print(f"GOOGLE_CLIENT_SECRET={installed.get('client_secret')}")
    print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
    print("GOOGLE_TOKEN_URI=https://oauth2.googleapis.com/token")


if __name__ == "__main__":
    main()

