import base64
import os
from dataclasses import dataclass
from email.mime.text import MIMEText
from pathlib import Path
from typing import Iterable, List, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request


SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


@dataclass(frozen=True)
class GmailConfig:
    user_id: str = "me"
    query: str = "has:attachment filename:pdf"
    processed_label: str = "processed-afki"
    error_label: str = "ordrebot-feil"


def _env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing environment variable: {name}")
    return v


def build_credentials_from_env() -> Credentials:
    """
    For Sliplane/containers: supply OAuth pieces as env vars.

    Required:
    - GOOGLE_CLIENT_ID
    - GOOGLE_CLIENT_SECRET
    - GOOGLE_REFRESH_TOKEN
    Optional:
    - GOOGLE_TOKEN_URI (default: https://oauth2.googleapis.com/token)
    """
    token_uri = os.getenv("GOOGLE_TOKEN_URI", "https://oauth2.googleapis.com/token")

    creds = Credentials(
        token=None,
        refresh_token=_env("GOOGLE_REFRESH_TOKEN"),
        token_uri=token_uri,
        client_id=_env("GOOGLE_CLIENT_ID"),
        client_secret=_env("GOOGLE_CLIENT_SECRET"),
        scopes=SCOPES,
    )

    # Force refresh now to validate config early
    creds.refresh(Request())
    return creds


def build_gmail_service(creds: Credentials):
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def search_messages(service, config: GmailConfig, *, max_results: int = 20) -> List[str]:
    exclusions = f"-label:{config.processed_label}"
    if config.error_label:
        exclusions += f" -label:{config.error_label}"
    try:
        resp = (
            service.users()
            .messages()
            .list(userId=config.user_id, q=f"{config.query} {exclusions}", maxResults=max_results)
            .execute()
        )
    except HttpError as e:
        raise RuntimeError(f"Gmail list failed: {e}") from e

    msgs = resp.get("messages", []) or []
    return [m["id"] for m in msgs if "id" in m]


def ensure_label(service, config: GmailConfig, name: Optional[str] = None) -> str:
    """Returner labelId for `name` (default: config.processed_label); opprett hvis den mangler."""
    label_name = name or config.processed_label
    try:
        labels_resp = service.users().labels().list(userId=config.user_id).execute()
    except HttpError as e:
        raise RuntimeError(f"Gmail labels list failed: {e}") from e

    for lbl in labels_resp.get("labels", []) or []:
        if lbl.get("name") == label_name:
            return lbl["id"]

    body = {"name": label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
    try:
        created = service.users().labels().create(userId=config.user_id, body=body).execute()
    except HttpError as e:
        raise RuntimeError(f"Gmail create label failed: {e}") from e
    return created["id"]


def apply_label(service, config: GmailConfig, message_id: str, label_id: str) -> None:
    body = {"addLabelIds": [label_id], "removeLabelIds": []}
    try:
        service.users().messages().modify(userId=config.user_id, id=message_id, body=body).execute()
    except HttpError as e:
        raise RuntimeError(f"Gmail modify message failed: {e}") from e


def _get_header(headers: Iterable[dict], name: str) -> str:
    for h in headers:
        if (h.get("name") or "").lower() == name.lower():
            return h.get("value") or ""
    return ""


def reply_to_message(service, config: GmailConfig, message_id: str, body_text: str) -> None:
    """
    Svarer i samme tråd som den opprinnelige meldingen. Avsender blir den
    autentiserte Gmail-brukeren; mottaker settes fra `From`-headeren på
    originalen, og `In-Reply-To`/`References` gjør at svaret threades
    korrekt i Gmail-klienten.
    """
    try:
        msg = (
            service.users()
            .messages()
            .get(
                userId=config.user_id,
                id=message_id,
                format="metadata",
                metadataHeaders=["From", "Subject", "Message-ID", "References"],
            )
            .execute()
        )
    except HttpError as e:
        raise RuntimeError(f"Gmail get message (for reply) failed: {e}") from e

    headers = (msg.get("payload") or {}).get("headers", []) or []
    from_addr = _get_header(headers, "From")
    subject = _get_header(headers, "Subject") or "(uten emne)"
    original_msg_id = _get_header(headers, "Message-ID") or _get_header(headers, "Message-Id")
    references = _get_header(headers, "References")
    thread_id = msg.get("threadId")

    if not from_addr:
        raise RuntimeError(f"Fant ikke From-header på melding {message_id}; kan ikke svare.")

    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    mime = MIMEText(body_text, _charset="utf-8")
    mime["To"] = from_addr
    mime["Subject"] = subject
    if original_msg_id:
        mime["In-Reply-To"] = original_msg_id
        mime["References"] = f"{references} {original_msg_id}".strip() if references else original_msg_id

    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
    send_body = {"raw": raw}
    if thread_id:
        send_body["threadId"] = thread_id

    try:
        service.users().messages().send(userId=config.user_id, body=send_body).execute()
    except HttpError as e:
        raise RuntimeError(f"Gmail send reply failed: {e}") from e


def download_pdf_attachments(service, config: GmailConfig, message_id: str, download_dir: str | Path) -> List[Path]:
    """
    Downloads all PDF attachments from a message to download_dir.
    Returns paths.
    """
    download_dir = Path(download_dir)
    download_dir.mkdir(parents=True, exist_ok=True)

    try:
        msg = service.users().messages().get(userId=config.user_id, id=message_id, format="full").execute()
    except HttpError as e:
        raise RuntimeError(f"Gmail get message failed: {e}") from e

    payload = msg.get("payload", {}) or {}
    parts = payload.get("parts", []) or []

    out: List[Path] = []

    def walk(parts_list: Iterable[dict]):
        for part in parts_list:
            yield part
            for sub in part.get("parts", []) or []:
                yield from walk([sub])

    for part in walk(parts):
        filename = part.get("filename") or ""
        mime = part.get("mimeType") or ""
        body = part.get("body", {}) or {}
        att_id = body.get("attachmentId")

        if not att_id:
            continue
        if not (filename.lower().endswith(".pdf") or mime == "application/pdf"):
            continue

        try:
            att = (
                service.users()
                .messages()
                .attachments()
                .get(userId=config.user_id, messageId=message_id, id=att_id)
                .execute()
            )
        except HttpError as e:
            raise RuntimeError(f"Gmail get attachment failed: {e}") from e

        data = att.get("data")
        if not data:
            continue

        raw = base64.urlsafe_b64decode(data.encode("utf-8"))
        out_path = download_dir / filename
        if out_path.exists():
            out_path = download_dir / f"{message_id}_{filename}"
        out_path.write_bytes(raw)
        out.append(out_path)

    return out

