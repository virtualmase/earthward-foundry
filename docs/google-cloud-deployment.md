# Earthward Foundry Google Cloud Deployment

Earthward Foundry runs on a single Compute Engine VM named `earthward-foundry` in `us-central1-c`. The server is an `e2-medium` instance with a 10 GB balanced persistent boot disk. The two SQLite-backed services run as separate systemd units, so their append-only ledgers remain on the VM's persistent disk across process restarts.

## Runtime layout

| Component | Local endpoint | Service unit | Persistent ledger |
|---|---|---|---|
| Traceability API | `http://127.0.0.1:5000` | `earthward-traceability.service` | `/var/lib/earthward-foundry/traceability/earthward_traceability.db` |
| Rescue API | `http://127.0.0.1:5001` | `earthward-rescue.service` | `/var/lib/earthward-foundry/rescue/earthward_rescue.db` |

Both services use Gunicorn and bind **only to `127.0.0.1`**. Ports `5000` and `5001` are intentionally not exposed through public Google Cloud firewall rules. Each non-health endpoint requires a bearer API key. The keys remain on the VM in root-owned configuration files under `/etc/earthward-foundry/`; they are not committed to the repository.

## Secure access

Use Google Cloud CLI port forwarding from a trusted computer. Keep the terminal open while using either local URL.

```bash
gcloud compute ssh virtualmase@earthward-foundry \
  --zone us-central1-c \
  -- -L 5000:127.0.0.1:5000 -L 5001:127.0.0.1:5001
```

After connecting, the health endpoints are available locally at `http://127.0.0.1:5000/health` and `http://127.0.0.1:5001/health`. Retrieve a required bearer key only through the managed SSH session, and store it in an approved secret manager before sharing it with an API client.

```bash
sudo cat /etc/earthward-foundry/traceability.env
sudo cat /etc/earthward-foundry/rescue.env
```

> **Security note:** do not set `ALLOW_UNAUTHENTICATED=true`, and do not add public firewall rules for ports `5000` or `5001`. The source-specific enforcement rules remain active behind the bearer-token layer.

## Operations

The systemd units restart automatically on failure and when the VM starts. The following commands use managed SSH and do not expose the service ports publicly.

```bash
# Confirm status and inspect recent logs
gcloud compute ssh virtualmase@earthward-foundry --zone us-central1-c \
  --command='sudo systemctl status earthward-traceability earthward-rescue --no-pager'
gcloud compute ssh virtualmase@earthward-foundry --zone us-central1-c \
  --command='sudo journalctl -u earthward-traceability -u earthward-rescue -n 100 --no-pager'

# Restart after a deliberate configuration change
gcloud compute ssh virtualmase@earthward-foundry --zone us-central1-c \
  --command='sudo systemctl restart earthward-traceability earthward-rescue'
```

The initial VM bootstrap is maintained in [`gce_install.sh`](../gce_install.sh). The script installs the current `main` revision, creates fresh secrets, and rebuilds both Python environments. Do **not** rerun it on a live ledger without first making a disk snapshot or a database backup, because it replaces the API keys.

## Cost safeguards

Google Cloud is configured with a monthly **$50** budget named `Earthward Foundry monthly infrastructure alert`. It has alerts at 50%, 80%, and 100% of the budget. A budget alert is a notification control, not an automatic spending stop.

The instance runs continuously and therefore continues to consume Compute Engine credit while it is running. Stop it whenever the services are not needed; the persistent disk retains the ledgers.

```bash
# Stop to suspend compute charges; persistent-disk charges continue.
gcloud compute instances stop earthward-foundry --zone us-central1-c

# Resume when needed.
gcloud compute instances start earthward-foundry --zone us-central1-c
```

To update the service code safely, create a disk snapshot, test the intended revision in a separate environment, then deploy by replacing `/opt/earthward-foundry`, updating the virtual environments, and restarting both systemd services. Production updates must preserve the ledger directories under `/var/lib/earthward-foundry/`.
