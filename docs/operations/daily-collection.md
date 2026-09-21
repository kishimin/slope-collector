# Daily collection operations

The daily collector runs as a systemd service and is started by a timer at
03:00 in `Asia/Tokyo`. The timer performs incremental collection only. The
initial full-history operation remains a separate manual backfill command.

## Installation

Install the application at `/opt/slope-collector` and create the dedicated
non-root service account:

```sh
sudo useradd --system --home /opt/slope-collector --shell /usr/sbin/nologin slope-collector
sudo install -d -o slope-collector -g slope-collector /opt/slope-collector
sudo install -d -o root -g slope-collector -m 0750 /etc/slope-collector
```

Create `/etc/slope-collector/collector.env` with deployment-specific values.
The file must be owned by `root:slope-collector` and have mode `0640`:

```sh
sudo chown root:slope-collector /etc/slope-collector/collector.env
sudo chmod 0640 /etc/slope-collector/collector.env
```

Copy the unit files from `deploy/systemd/` into `/etc/systemd/system/`:

```sh
sudo install -m 0644 deploy/systemd/slope-collector.service /etc/systemd/system/
sudo install -m 0644 deploy/systemd/slope-collector.timer /etc/systemd/system/
sudo install -m 0644 deploy/systemd/slope-collector-backfill.service /etc/systemd/system/
sudo systemctl daemon-reload
```

## Enable and start

Enable the timer. The service is not enabled independently because the timer
owns its daily start:

```sh
sudo systemctl enable --now slope-collector.timer
```

The timer runs once per day at 03:00 in `Asia/Tokyo`, allows one minute of
systemd scheduling accuracy, does not catch up missed runs, and adds no
randomized delay. The service uses `Type=oneshot`; systemd does not start a
second instance of the same service while one is already running.

## Inspect status and logs

```sh
sudo systemctl status slope-collector.timer
sudo systemctl status slope-collector.service
sudo journalctl -u slope-collector.service
```

The service writes standard output and standard error to journald. Application
retry and failure-summary notifications remain the source of collection-level
failure details; systemd does not send a second `OnFailure` notification.

## Manual execution

Start one incremental run manually when the timer is not already running:

```sh
sudo systemctl start slope-collector.service
```

Run the initial full-history operation through its separate service when it is
explicitly needed. This service loads the same deployment environment file as
the scheduled service and invokes `collect-backfill`:

```sh
sudo systemctl start slope-collector-backfill.service
```

Do not put the initial backfill command in the timer unit. A failed daily run
exits with a failure status and is retried by the application according to its
collection policy; systemd does not automatically restart it. The next timer
run resumes from the database checkpoint.
