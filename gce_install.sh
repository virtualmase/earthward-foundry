#!/usr/bin/env bash
# Deploy Earthward Foundry's two authenticated HTTP services on a Debian GCE VM.
# The services bind only to 127.0.0.1; access is through managed SSH port forwarding.

set -euo pipefail

APP_ROOT="/opt/earthward-foundry"
STATE_ROOT="/var/lib/earthward-foundry"
CONFIG_ROOT="/etc/earthward-foundry"
RUN_USER="$(id -un)"
REPOSITORY="https://github.com/virtualmase/earthward-foundry.git"

sudo apt-get update
sudo apt-get install -y --no-install-recommends ca-certificates curl git openssl python3-venv

sudo rm -rf "$APP_ROOT"
sudo git clone --depth 1 "$REPOSITORY" "$APP_ROOT"
sudo chown -R "$RUN_USER:$RUN_USER" "$APP_ROOT"

python3 -m venv "$APP_ROOT/services/traceability/.venv"
"$APP_ROOT/services/traceability/.venv/bin/pip" install --upgrade pip
"$APP_ROOT/services/traceability/.venv/bin/pip" install -r "$APP_ROOT/services/traceability/requirements.txt"

python3 -m venv "$APP_ROOT/services/rescue/.venv"
"$APP_ROOT/services/rescue/.venv/bin/pip" install --upgrade pip
"$APP_ROOT/services/rescue/.venv/bin/pip" install -r "$APP_ROOT/services/rescue/requirements.txt"

sudo install -d -o "$RUN_USER" -g "$RUN_USER" -m 0750 \
  "$STATE_ROOT/traceability" "$STATE_ROOT/rescue"
sudo install -d -o root -g "$RUN_USER" -m 0750 "$CONFIG_ROOT"

TRACEABILITY_KEY="$(openssl rand -hex 32)"
RESCUE_KEY="$(openssl rand -hex 32)"

sudo tee "$CONFIG_ROOT/traceability.env" >/dev/null <<EOF
TRACEABILITY_API_KEY=$TRACEABILITY_KEY
TRACEABILITY_DB_PATH=$STATE_ROOT/traceability/earthward_traceability.db
RATE_LIMIT_PER_MINUTE=120
EOF
sudo tee "$CONFIG_ROOT/rescue.env" >/dev/null <<EOF
RESCUE_API_KEY=$RESCUE_KEY
RESCUE_DB_PATH=$STATE_ROOT/rescue/earthward_rescue.db
RATE_LIMIT_PER_MINUTE=120
EOF
sudo chmod 0640 "$CONFIG_ROOT/traceability.env" "$CONFIG_ROOT/rescue.env"

sudo tee /etc/systemd/system/earthward-traceability.service >/dev/null <<EOF
[Unit]
Description=Earthward Traceability API
After=network.target

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_USER
WorkingDirectory=$APP_ROOT/services/traceability
EnvironmentFile=$CONFIG_ROOT/traceability.env
ExecStart=$APP_ROOT/services/traceability/.venv/bin/gunicorn --workers 1 --threads 4 --bind 127.0.0.1:5000 wsgi:app
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=$STATE_ROOT/traceability

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/earthward-rescue.service >/dev/null <<EOF
[Unit]
Description=Earthward Rescue Task Force API
After=network.target

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_USER
WorkingDirectory=$APP_ROOT/services/rescue
EnvironmentFile=$CONFIG_ROOT/rescue.env
ExecStart=$APP_ROOT/services/rescue/.venv/bin/gunicorn --workers 1 --threads 4 --bind 127.0.0.1:5001 wsgi:app
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=$STATE_ROOT/rescue

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now earthward-traceability earthward-rescue
sleep 2
curl --fail --silent --show-error http://127.0.0.1:5000/health >/dev/null
curl --fail --silent --show-error http://127.0.0.1:5001/health >/dev/null

cat <<'EOF'
Earthward Foundry services are active on localhost only:
  Traceability: http://127.0.0.1:5000
  Rescue:       http://127.0.0.1:5001

Both APIs require bearer keys stored in /etc/earthward-foundry/*.env.
Use managed SSH port forwarding to reach either API remotely; direct public
access to ports 5000 and 5001 is intentionally disabled.
EOF
