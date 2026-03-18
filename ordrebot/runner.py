import os
import shutil
import time
from pathlib import Path

from ordrebot.gmail_client import (
    GmailConfig,
    apply_label,
    build_credentials_from_env,
    build_gmail_service,
    download_pdf_attachments,
    ensure_label,
    search_messages,
)
from ordrebot.orchestrator import run_all
from ordrebot.pdf_parser import parse_order_pdf


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def process_one_message(service, config: GmailConfig, label_id: str, message_id: str, work_dir: Path) -> None:
    msg_dir = work_dir / message_id
    msg_dir.mkdir(parents=True, exist_ok=True)

    pdf_paths = download_pdf_attachments(service, config, message_id, msg_dir)
    print(f"Gmail {message_id}: {len(pdf_paths)} pdf-vedlegg funnet.")

    all_lines = []
    for pdf_path in pdf_paths:
        lines = parse_order_pdf(pdf_path)
        print(f"PDF {pdf_path.name}: {len(lines)} ordrelinjer.")
        all_lines.extend(lines)

    if all_lines:
        print(f"Totalt {len(all_lines)} linjer -> ruter til leverandører.")
        run_all(all_lines)
    else:
        print("Ingen ordrelinjer funnet – hopper over vendor-kjøring.")

    apply_label(service, config, message_id, label_id)
    print(f"Gmail {message_id}: label'et som {config.processed_label}.")

    # cleanup
    shutil.rmtree(msg_dir, ignore_errors=True)


def main() -> None:
    poll_interval_s = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
    max_per_poll = int(os.getenv("MAX_MESSAGES_PER_POLL", "10"))
    once = _bool_env("RUN_ONCE", default=False)

    # For headless in containers; vendor scripts read HEADLESS env
    os.environ.setdefault("HEADLESS", os.getenv("HEADLESS", "1"))

    config = GmailConfig(
        user_id=os.getenv("GMAIL_USER_ID", "me"),
        query=os.getenv("GMAIL_QUERY", "has:attachment filename:pdf"),
        processed_label=os.getenv("GMAIL_PROCESSED_LABEL", "processed-afki"),
    )

    creds = build_credentials_from_env()
    service = build_gmail_service(creds)
    label_id = ensure_label(service, config)

    work_dir = Path(os.getenv("WORK_DIR", "/tmp/ordrebot"))
    work_dir.mkdir(parents=True, exist_ok=True)

    while True:
        message_ids = search_messages(service, config, max_results=max_per_poll)
        if not message_ids:
            print("Ingen nye e-poster å prosessere.")
        for mid in message_ids:
            try:
                process_one_message(service, config, label_id, mid, work_dir)
            except Exception as exc:  # noqa: BLE001
                # Ikke label som prosessert ved feil
                print(f"Feil ved prosessering av Gmail {mid}: {exc}")

        if once:
            return
        time.sleep(poll_interval_s)


if __name__ == "__main__":
    main()

