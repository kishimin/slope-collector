"""Collection failure notification tests."""

from types import SimpleNamespace
from typing import TYPE_CHECKING, Self, cast

import pytest

from app.services.collection import CollectionResult
from app.services.notifications import notify_failures

if TYPE_CHECKING:
    from app.config import Settings


@pytest.mark.small
def test_failure_summary_is_sent_only_when_mail_configuration_is_complete() -> None:
    """Operators receive one summary instead of one email per failed record."""
    sent: list[object] = []

    class FakeSmtp:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *arguments: object) -> None:
            return None

        def starttls(self) -> None:
            return None

        def login(self, _username: str, _password: str) -> None:
            return None

        def send_message(self, message: object) -> None:
            sent.append(message)

    settings = cast(
        "Settings",
        SimpleNamespace(
            mail_host="mail.example",
            mail_port=587,
            mail_username=SimpleNamespace(get_secret_value=lambda: "operator"),
            mail_password=SimpleNamespace(get_secret_value=lambda: "secret"),
            mail_from="from@example",
            mail_to="to@example",
        ),
    )

    def smtp_factory(*_arguments: object, **_keywords: object) -> FakeSmtp:
        return FakeSmtp()

    notify_failures(
        settings,
        CollectionResult(saved_records=1, failed_records=2),
        smtp_factory=smtp_factory,
    )

    assert len(sent) == 1
