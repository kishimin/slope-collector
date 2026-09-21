"""Summary email notification for unresolved collection failures."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.config import Settings
    from app.services.collection import CollectionResult


def notify_failures(
    settings: Settings,
    result: CollectionResult,
    *,
    smtp_factory: Callable[..., Any] = smtplib.SMTP,
) -> None:
    """Send one sanitized failure summary when mail settings are complete."""
    if result.failed_records == 0:
        return
    if not all((settings.mail_host, settings.mail_from, settings.mail_to)):
        return

    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = settings.mail_to
    message["Subject"] = "Slope Collector failures"
    message.set_content(
        "Collection completed with unresolved failures.\n"
        f"saved={result.saved_records}\n"
        f"skipped={result.skipped_records}\n"
        f"failed={result.failed_records}\n"
        + "\n".join(
            f" - {failure.occurred_at.isoformat()} stage={failure.stage} "
            f"context={failure.context} exception={failure.exception_type}: "
            f"{failure.message}"
            for failure in result.failures
        )
        + "\n"
    )
    with smtp_factory(settings.mail_host, settings.mail_port, timeout=30) as smtp:
        smtp.starttls()
        username = settings.mail_username.get_secret_value()
        if username:
            smtp.login(username, settings.mail_password.get_secret_value())
        smtp.send_message(message)
