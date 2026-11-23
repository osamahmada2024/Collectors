#!/usr/bin/env bash
# ============================================================================
#  BENIGN ACTIVITY SCRIPT — normal admin/day-to-day behaviour.
#
#  Run this ON THE VICTIM machine to demonstrate the "no anomaly" case:
#  same Tracee stream, same collector, but the detection engine stays quiet.
#
#  Usage:  bash benign.sh
# ============================================================================
echo "[1/5] Browsing files"
ls -la /home/ubuntu 2>/dev/null || ls -la ~
cat /etc/os-release | head -3
df -h | head -3

echo "[2/5] Checking system state"
uptime
free -h

echo "[3/5] Reading documentation"
cat README.md 2>/dev/null | head -5 || head -5 /etc/hostname

echo "[4/5] Light scripting"
python3 -c "print('benign demo: python working')" 2>/dev/null || python -c "print('benign demo')"

echo "[5/5] Network read from a legit source"
curl -s -m 5 https://example.com -o /dev/null && echo "GET example.com -> 200" || echo "network read skipped"

echo ""
echo "[OK] Benign session complete — the SOC should show NO alert for these."
