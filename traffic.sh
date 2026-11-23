#!/usr/bin/env bash
# Continuous benign system activity generator.
# Simulates realistic server workload so the SOC dashboard shows a live,
# flowing event stream. Safe: read-only commands + harmless file activity.
# Usage: sudo bash traffic.sh [seconds]   (default: runs for 600 seconds)

DURATION="${1:-600}"
END=$(( $(date +%s) + DURATION ))
DIR="/tmp/soc-traffic-$$"
mkdir -p "$DIR"

CMDS=(
  "ls -la /var/log"
  "cat /etc/passwd"
  "df -h"
  "free -m"
  "uptime"
  "ps aux"
  "ss -tuln"
  "find /etc -name '*.conf'"
  "journalctl --no-pager -n 20"
  "stat /etc/hostname"
  "sha256sum /etc/hosts"
  "tar -czf $DIR/bundle.tgz /etc/hostname"
  "cp /etc/hosts $DIR/hosts.bak"
  "grep -r 'root' /etc/group | head -5"
  "curl -s -o $DIR/motd.txt http://archive.ubuntu.com --max-time 3"
)

n=0
while [ "$(date +%s)" -lt "$END" ]; do
  for cmd in "${CMDS[@]}"; do
    eval "$cmd" >/dev/null 2>&1
    n=$((n+1))
    echo "$n: $cmd"
    sleep 0.4
  done
  rm -rf "$DIR"/*
done
rm -rf "$DIR"
echo "traffic generator finished after $n command batches"
