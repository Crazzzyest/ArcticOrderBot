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
    reply_to_message,
    search_messages,
)
from ordrebot.orchestrator import run_all
from ordrebot.pdf_parser import ParseIncompleteError, ParseResult, parse_order_pdf


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def _format_parse_failure_reply(pdf_name: str, result: ParseResult) -> str:
    parsed_block = (
        "\n".join(f"  - {l.varenr}  antall: {l.antall}" for l in result.lines)
        or "  (ingen)"
    )
    unparsed_block = "\n".join(f"  - {ln}" for ln in result.unparsed) or "  (ingen)"
    return (
        "Hei,\n\n"
        f"Ordrebot klarte ikke å tolke alle ordrelinjer i vedlegget '{pdf_name}'.\n"
        "Ingen ordre er lagt inn hos leverandør.\n\n"
        "Linjer som ikke kunne tolkes:\n"
        f"{unparsed_block}\n\n"
        "Linjer som ble tolket (men ikke bestilt, siden hele filen må være korrekt):\n"
        f"{parsed_block}\n\n"
        "Sjekk at varenummer-kolonnen følger vanlig format, og send PDF-en på nytt om nødvendig.\n\n"
        "Hilsen Ordrebot"
    )


def process_one_message(
    service,
    config: GmailConfig,
    label_id: str,
    error_label_id: str,
    message_id: str,
    work_dir: Path,
) -> None:
    msg_dir = work_dir / message_id
    msg_dir.mkdir(parents=True, exist_ok=True)

    try:
        pdf_paths = download_pdf_attachments(service, config, message_id, msg_dir)
        print(f"Gmail {message_id}: {len(pdf_paths)} pdf-vedlegg funnet.")

        all_lines = []
        for pdf_path in pdf_paths:
            result = parse_order_pdf(pdf_path)
            print(
                f"PDF {pdf_path.name}: {len(result.lines)} ordrelinjer parset, "
                f"{len(result.unparsed)} uparset."
            )
            if not result.is_complete:
                # Fail loud: aldri send delvis bestilling til leverandør.
                # Svar til avsender og merk meldingen med feil-label så
                # vi ikke spammer dem ved neste polling.
                body = _format_parse_failure_reply(pdf_path.name, result)
                try:
                    reply_to_message(service, config, message_id, body)
                    print(f"Gmail {message_id}: sendte feilsvar til avsender.")
                except Exception as reply_exc:  # noqa: BLE001
                    print(f"Gmail {message_id}: klarte ikke sende feilsvar: {reply_exc}")
                apply_label(service, config, message_id, error_label_id)
                print(f"Gmail {message_id}: merket som {config.error_label}.")
                raise ParseIncompleteError(pdf_path, result)
            all_lines.extend(result.as_dicts())

        if all_lines:
            print(f"Totalt {len(all_lines)} linjer -> ruter til leverandører.")
            run_all(all_lines)
        else:
            print("Ingen ordrelinjer funnet – hopper over vendor-kjøring.")

        apply_label(service, config, message_id, label_id)
        print(f"Gmail {message_id}: label'et som {config.processed_label}.")
    finally:
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
        error_label=os.getenv("GMAIL_ERROR_LABEL", "ordrebot-feil"),
    )

    creds = build_credentials_from_env()
    service = build_gmail_service(creds)
    label_id = ensure_label(service, config)
    error_label_id = ensure_label(service, config, name=config.error_label)

    work_dir = Path(os.getenv("WORK_DIR", "/tmp/ordrebot"))
    work_dir.mkdir(parents=True, exist_ok=True)

    while True:
        message_ids = search_messages(service, config, max_results=max_per_poll)
        if not message_ids:
            print("Ingen nye e-poster å prosessere.")
        for mid in message_ids:
            try:
                process_one_message(service, config, label_id, error_label_id, mid, work_dir)
            except ParseIncompleteError as exc:
                # Avsender er allerede varslet i process_one_message;
                # her logger vi bare så operatør ser det i containerloggen.
                print(f"PARSE-FEIL Gmail {mid}: {exc}")
            except Exception as exc:  # noqa: BLE001
                # Ikke label som prosessert ved andre feil – retry på neste poll.
                print(f"Feil ved prosessering av Gmail {mid}: {exc}")

        if once:
            return
        time.sleep(poll_interval_s)


if __name__ == "__main__":
    main()
