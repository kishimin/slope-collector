"""Acceptance coverage for Issue #7 daily scheduling."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
SYSTEMD = ROOT / "deploy" / "systemd"
SERVICE = SYSTEMD / "slope-collector.service"
TIMER = SYSTEMD / "slope-collector.timer"
OPERATIONS = ROOT / "docs" / "operations" / "daily-collection.md"


def test_daily_and_backfill_commands_are_distinct() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "app.collector", "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "collect-daily" in result.stdout
    assert "collect-backfill" in result.stdout


def test_service_defines_daily_process_boundary_and_hardening() -> None:
    content = SERVICE.read_text(encoding="utf-8")

    assert "Type=oneshot" in content
    assert "User=slope-collector" in content
    assert "WorkingDirectory=/opt/slope-collector" in content
    assert "EnvironmentFile=/etc/slope-collector/collector.env" in content
    assert (
        "ExecStart=/opt/slope-collector/.venv/bin/python -m app.collector collect-daily"
        in content
    )
    assert "Restart=no" in content
    assert "After=network-online.target" in content
    assert "Wants=network-online.target" in content
    assert "NoNewPrivileges=true" in content
    assert "PrivateTmp=true" in content
    assert "ProtectSystem=strict" in content
    assert "TimeoutStartSec=infinity" in content


def test_timer_defines_tokyo_schedule_without_catch_up_or_jitter() -> None:
    content = TIMER.read_text(encoding="utf-8")

    assert "OnCalendar=*-*-* 03:00:00 Asia/Tokyo" in content
    assert "Persistent=false" in content
    assert "AccuracySec=1min" in content
    assert "RandomizedDelaySec=0" in content
    assert "Unit=slope-collector.service" in content


def test_operations_documentation_covers_lifecycle_and_observability() -> None:
    content = OPERATIONS.read_text(encoding="utf-8")

    for phrase in (
        "systemctl daemon-reload",
        "systemctl enable --now slope-collector.timer",
        "systemctl status slope-collector.timer",
        "journalctl -u slope-collector.service",
        "systemctl start slope-collector.service",
        "collect-backfill",
    ):
        assert phrase in content
