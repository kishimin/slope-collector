# Maintenance controls

The internal maintenance API is available in development and production after
deployment and `uv run alembic upgrade head`. Like the existing internal API, it
has no application-level authentication. Keep it reachable only by the GUI server
through loopback or a private network. The public GUI server must authenticate
its owner before forwarding management requests. Do not publish the internal API
directly. The GUI application is a separate project.

## API

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/collection-controls` | Return a `controls` array of all states. |
| POST | `/collection-controls/{source}/{site}/pause` | Persist or replace a pause. |
| POST | `/collection-controls/{source}/{site}/resume` | Release a pause without external requests. |

`source` is `source_a`, `source_b`, or `source_c`; `site` is `official` or
`archive`. Controls apply to a source's collection route, across all its members.
If sources share an archive host, pause each affected source's archive route.

Example pause request:

```json
{"resume_mode": "manual", "reason": "Scheduled maintenance"}
```

For automatic recovery use `"resume_mode": "automatic"` and optionally
`"check_interval_minutes": 60`. The interval must be an integer from 1 through
1440, defaults to 60, and is validated for both modes. `reason` is optional,
limited to 255 characters. Unknown fields are rejected. Resume needs no body.

Pause and resume return the resulting state. State fields are `source`, `site`,
`paused`, `resume_mode`, `check_interval_minutes`, `reason`, `next_check_at`,
`last_checked_at`, `last_check_succeeded`, `last_check_error`, and an opaque
`revision`. Timestamps use UTC. A missing database row means running. `paused`
describes the requested state: an in-flight request and its article save may
still finish.

Invalid input returns `422 VALIDATION_ERROR`. Automatic recovery without a valid
private probe returns `409 RECOVERY_PROBE_REQUIRED`, leaving state unchanged.
Unavailable storage returns `503 CONTROL_STORAGE_UNAVAILABLE` without DB details.

## Collection behavior

Daily collection and manual backfills read the same DB controls. A pause prevents
the next request, including retries and same-host redirects. Pacing waits may
finish before a second state check prevents the request. An already started
request and its completely parsed article's save finish normally. Saved articles
remain; other source sites continue. A pause is logged and reported as
`paused_sites` in the collection result, rather than a collection failure.
A paused-only run exits 0. Storage failures stop collection rather than bypassing
the pause. Restarting processes preserves the controls.

An archive route fetching HTML from the official host also honors the official
pause. A separately configured archive HTML host uses its archive pause.
Manual resume performs no external check: the operator confirms maintenance has
ended. Manual and automatic resume only make the next scheduled or manual
collection eligible; neither starts collection. Normal incremental/backfill
rules apply. Automatic retries of previously failed articles are outside scope.

## Private recovery configuration

Set `COLLECTOR_RECOVERY_CONFIG_PATH` in both the API and recovery command's
environment to an ignored local manifest, for example `.env.recovery.json`:

```json
[
  {"source": "source_a", "site": "official"},
  {
    "source": "source_a", "site": "archive", "source_entity_key": "7",
    "archive_config_path": ".env.archive.json"
  }
]
```

Official probes may optionally specify `source_entity_key`. Archive probes
require it and a private contract in the existing backfill format. Choose a
representative member whose list and article are available. Archive contract
paths are relative to the manifest. Duplicate targets, unknown fields, malformed
contracts, and missing targets are rejected. The recovery process also needs the
normal source settings. Keep real URLs, selectors, manifests, and archive
contracts uncommitted; make private files available to both processes.

## Recovery command and schedule

```powershell
uv run python -m app.collector check-recovery
```

Due automatic pauses are checked sequentially; manual pauses and future deadlines
cause no external requests. Each check parses the first list page and its first
article with collection's parsing contracts. HTTP success alone is insufficient.
Checks do not persist articles, change member identities, send notifications,
retry immediately, or start collection. Existing HTTPS host, response-size,
timeout, and request-spacing limits apply.

Failure keeps the pause and schedules the next check from completion. Success
releases it. The API reports the check time, success flag, and sanitized failure
message. Raw external errors and private response contents are not logged.
The command exits 1 for an applied failed check and 0 otherwise.

A DB claim prevents concurrent workers from checking the same deadline. During
a check, `next_check_at` temporarily reflects a reservation for both bounded
responses, pacing, and parsing time. New operator actions invalidate old results.
A crashed worker leaves the pause intact; later invocations retry after the
reservation expires.

For Linux, install the recovery units alongside the daily service:

```sh
sudo install -m 0644 deploy/systemd/slope-collector-recovery.service /etc/systemd/system/
sudo install -m 0644 deploy/systemd/slope-collector-recovery.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now slope-collector-recovery.timer
sudo systemctl status slope-collector-recovery.timer
sudo journalctl -u slope-collector-recovery.service
```

The timer invokes the command every minute; only due sites are probed. Deadlines
have minute-level scheduling precision and may be delayed by earlier checks.
The service loads `/etc/slope-collector/collector.env` and prevents overlapping
instances of itself. Other environments must schedule the same command separately.
Code deployment does not install or enable systemd units. Apply the migration
before starting the updated API and collectors.
