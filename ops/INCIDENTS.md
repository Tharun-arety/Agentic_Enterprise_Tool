# VM operations and incidents

Provision Ubuntu Server with a non-root `magnotherm` service account, SSH keys only, `PasswordAuthentication no`, UFW denying inbound traffic except Tailscale, and unattended security updates. Store `.env.production` mode `0600`; never add it to Git.

Deploy an explicit version with `docker compose pull`, `docker compose build --pull api`, `alembic upgrade head`, then `docker compose up -d`. Confirm `/api/health`, queue depth, ERP adapter state, and one authenticated read before declaring success. Funnel should forward only `127.0.0.1:8000`; Grafana, Prometheus, Loki, MinIO, and ERPNext remain on the tailnet/private loopback.

For an incident: preserve logs and request/correlation IDs, disable Funnel if authentication or data integrity is uncertain, rotate affected credentials, restore the last verified backup to an empty environment, reconcile outbox/inbox idempotency keys, and document the timeline. Never replay dead-letter events until their payload hash and target state have been checked.

Run `ops/backup.sh` daily from systemd and `ops/restore-test.sh` monthly against the newest archive. Retention is seven daily and four weekly encrypted copies on a separate local disk.
