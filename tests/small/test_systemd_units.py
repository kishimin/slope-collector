"""Tests for the committed systemd unit contract."""

from pathlib import Path

ROOT = Path(__file__).parents[2]
BACKFILL_SERVICE = ROOT / "deploy" / "systemd" / "slope-collector-backfill.service"
OPERATIONS = ROOT / "docs" / "operations" / "daily-collection.md"


def test_backfill_service_loads_the_deployment_environment() -> None:
    """Manual backfills use the same environment boundary as daily runs."""
    content = BACKFILL_SERVICE.read_text(encoding="utf-8")

    assert "Type=oneshot" in content
    assert "EnvironmentFile=/etc/slope-collector/collector.env" in content
    assert (
        "ExecStart=/opt/slope-collector/.venv/bin/python -m app.collector "
        "collect-backfill" in content
    )


def test_operations_run_backfill_through_the_environment_boundary() -> None:
    """The runbook must not bypass the service environment file."""
    content = OPERATIONS.read_text(encoding="utf-8")

    assert "systemctl start slope-collector-backfill.service" in content
