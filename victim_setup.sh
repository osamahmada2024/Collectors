#!/usr/bin/env bash
# ============================================================================
#  VICTIM MACHINE SETUP — run ONCE on the fresh "victim" EC2 (Ubuntu 24.04).
#
#  Installs Tracee, and registers both Tracee and the SignalR collector as
#  systemd services that survive reboot and log to the journal.
#
#  Usage (run from inside the cloned Collectors folder):
#      sudo SERVER_URL="http://44.204.173.93:5086/logs" bash victim_setup.sh
#
#  After it finishes, test with:   sudo bash benign.sh   then   sudo bash attack.sh
# ============================================================================
set -euo pipefail

SERVER_URL="${SERVER_URL:-http://44.204.173.93:5086/logs}"
HUB_METHOD="${HUB_METHOD:-sendLog}"
LOG_FILE="${LOG_FILE:-/var/lib/soc/tracee-events.json}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo (Tracee needs root for eBPF)." >&2
    exit 1
fi

echo "[1/5] Installing dependencies"
apt-get update -qq
apt-get install -y -qq curl ca-certificates python3 python3-pip > /dev/null

echo "[2/5] Installing Tracee"
if ! command -v tracee > /dev/null; then
    curl -fsSL -o /tmp/tracee.tar.gz \
        "https://github.com/aquasecurity/tracee/releases/download/v0.24.1/tracee-x86_64.v0.24.1.tar.gz"
    rm -rf /tmp/tracee-extract && mkdir -p /tmp/tracee-extract
    tar -xzf /tmp/tracee.tar.gz -C /tmp/tracee-extract
    install -m 0755 /tmp/tracee-extract/dist/tracee /usr/local/bin/tracee
fi
tracee version 2>/dev/null || true

echo "[3/5] Preparing event log directory + collector deps"
mkdir -p "$(dirname "${LOG_FILE}")"
pip3 install -q --break-system-packages signalrcore || pip3 install -q signalrcore

echo "[4/5] Registering systemd services"
cat > /etc/systemd/system/soc-tracee.service << EOF
[Unit]
Description=SOC Tracee sensor (eBPF event stream)
After=network.target

[Service]
ExecStart=/usr/local/bin/tracee --events execve,openat,connect,magic_write,security_file_open --output json
StandardOutput=append:${LOG_FILE}
StandardError=journal
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/soc-collector.service << EOF
[Unit]
Description=SOC SignalR collector (tails ${LOG_FILE})
After=network.target soc-tracee.service

[Service]
Environment=SERVER_URL=${SERVER_URL}
Environment=HUB_METHOD=${HUB_METHOD}
Environment=LOG_FILE=${LOG_FILE}
Environment=AGENT_ID=tracee-victim-01
WorkingDirectory=${REPO_DIR}
ExecStart=/usr/bin/python3 ${REPO_DIR}/Collector_Agent_SignalR.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Point the collector at the configured server instead of the hardcoded
# localhost default (the script reads these from the environment if present).
python3 - << PYEOF
from pathlib import Path
import os
path = Path("${REPO_DIR}/Collector_Agent_SignalR.py")
source = path.read_text()
source = source.replace(
    'SERVER_URL  = "http://localhost:5086/logs"',
    'SERVER_URL  = os.environ.get("SERVER_URL", "http://localhost:5086/logs")',
)
source = source.replace(
    'HUB_METHOD  = "sendLog"',
    'HUB_METHOD  = os.environ.get("HUB_METHOD", "sendLog")',
)
source = source.replace(
    'LOG_FILE    = os.path.join(os.path.dirname(os.path.abspath(__file__)),',
    'LOG_FILE    = os.environ.get("LOG_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__))),',
)
source = source.replace(
    '                           "tracee-events.json")',
    '                           "tracee-events.json"))',
)
path.write_text(source)
print("collector config updated")
PYEOF

echo "[5/5] Starting services"
systemctl daemon-reload
systemctl enable --now soc-tracee.service
sleep 2
systemctl enable --now soc-collector.service
sleep 2

echo ""
echo "[OK] Victim is wired to ${SERVER_URL}"
systemctl --no-pager --lines=3 status soc-tracee.service | sed -n '1,5p'
systemctl --no-pager --lines=3 status soc-collector.service | sed -n '1,5p'
