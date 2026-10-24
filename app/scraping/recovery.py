"""Private recovery targets and bounded, non-persisting source checks."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from app.config import SourceKey, load_source_config
from app.models.control import RecoveryCheckError, SiteKind, Target
from app.scraping.adapter import ParseContractError, SourceAdapter
from app.scraping.http_client import BoundedHttpClient, HttpLimits
from app.services.archive_collection import load_archive_config, probe_archive
from app.services.collection import _initial_list_path, wait_before_request

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx

    from app.config import Settings


class RecoveryConfigError(ValueError):
    """Recovery configuration is absent or invalid, without exposing its contents."""


class RecoveryProbe(BaseModel):
    """Select a locally configured source contract, never a caller-supplied URL."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    source: SourceKey
    site: SiteKind
    source_entity_key: str | None = Field(default=None, pattern=r"^[1-9][0-9]*$")
    archive_config_path: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def require_site_contract(self) -> Self:
        """Require targeted archive checks and reject irrelevant official options."""
        if self.site == "archive":
            if self.source_entity_key is None or self.archive_config_path is None:
                message = "archive recovery requires a member and private contract"
                raise ValueError(message)
        elif self.archive_config_path is not None:
            message = "official recovery cannot use an archive contract"
            raise ValueError(message)
        return self

    @property
    def target(self) -> Target:
        """Resolve the controlled site identity."""
        return Target(self.source, self.site)


def _read_probes(path: str) -> list[RecoveryProbe]:
    if not path:
        raise ValueError
    probes = TypeAdapter(list[RecoveryProbe]).validate_json(
        Path(path).read_text(encoding="utf-8")
    )
    if len({probe.target for probe in probes}) != len(probes):
        raise ValueError
    return probes


def load_recovery_probe(path: str, target: Target) -> RecoveryProbe:
    """Read an ignored manifest and resolve archive paths relative to its file."""
    try:
        manifest = Path(path)
        probes = _read_probes(path)
        for probe in probes:
            if probe.target == target:
                if probe.archive_config_path is not None:
                    archive_path = manifest.parent / probe.archive_config_path
                    load_archive_config(str(archive_path))
                    return probe.model_copy(
                        update={"archive_config_path": str(archive_path)}
                    )
                return probe
    except OSError, ValueError:
        pass
    message = "a valid private recovery probe is required for this site"
    raise RecoveryConfigError(message) from None


class ConfiguredRecoveryChecker:
    """Adapt private source contracts and bounded HTTP to the recovery port."""

    def __init__(
        self,
        settings: Settings,
        *,
        sleep: Callable[[float], None],
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Keep source locations out of the orchestration layer."""
        self._settings = settings
        self._sleep = sleep
        self._transport = transport

    @property
    def lease_seconds(self) -> float:
        """Reserve both response deadlines and pacing waits plus parsing time."""
        return (
            2
            * (
                self._settings.collector_response_timeout_seconds
                + self._settings.collector_request_interval_seconds
                + self._settings.collector_request_jitter_seconds
            )
            + 60
        )

    def check(
        self, target: Target, authorize_request: Callable[[Target], None]
    ) -> None:
        """Normalize private configuration and parser failures at the boundary."""
        try:
            probe = load_recovery_probe(
                self._settings.collector_recovery_config_path.get_secret_value(), target
            )
            probe_site(
                self._settings,
                probe,
                authorize_request=authorize_request,
                sleep=self._sleep,
                transport=self._transport,
            )
        except ValueError, RuntimeError, KeyError:
            message = "recovery list or article could not be validated"
            raise RecoveryCheckError(message) from None


def probe_site(
    settings: Settings,
    probe: RecoveryProbe,
    *,
    authorize_request: Callable[[Target], None],
    sleep: Callable[[float], None],
    transport: httpx.BaseTransport | None = None,
) -> None:
    """Validate a list and its first article, with no retries or persistence."""
    if probe.site == "archive":
        if probe.archive_config_path is None or probe.source_entity_key is None:
            raise RecoveryConfigError
        probe_archive(
            settings=settings,
            source_key=probe.source,
            source_entity_key=probe.source_entity_key,
            config=load_archive_config(probe.archive_config_path),
            authorize_request=authorize_request,
            sleep=sleep,
            transport=transport,
        )
        return
    source = load_source_config(settings, probe.source)
    adapter = SourceAdapter(probe.source, source)
    limits = HttpLimits(
        settings.collector_connect_timeout_seconds,
        settings.collector_response_timeout_seconds,
        settings.collector_max_response_bytes,
    )

    def before_request() -> None:
        authorize_request(probe.target)

    with BoundedHttpClient(
        base_url=str(source.base_url),
        user_agent=settings.collector_user_agent,
        limits=limits,
        transport=transport,
        before_request=before_request,
    ) as client:

        def get_html(path: str) -> str:
            before_request()
            wait_before_request(settings, path, sleep=sleep, random_value=lambda: 0)
            return client.get_html(path)

        page = adapter.parse_list(
            get_html(
                _initial_list_path(
                    source.list_path,
                    entity_id_query_param=source.entity_id_query_param,
                    source_entity_key=probe.source_entity_key,
                )
            )
        )
        reference = page.records[0]
        record = adapter.parse_detail(
            get_html(reference.source_path), source_path=reference.source_path
        )
        if (
            probe.source_entity_key is not None
            and record.entity_external_key != probe.source_entity_key
        ):
            message = "recovery article does not match requested member"
            raise ParseContractError(message)
