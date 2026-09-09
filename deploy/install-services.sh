#!/usr/bin/env bash
# Install jobsearch-agent LaunchAgents: nightly run (02:30) + Phoenix keepalive.
# Idempotent; safe to re-run. Stop services with uninstall-services.sh.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LA="$HOME/Library/LaunchAgents"
LOGS="$HOME/Library/Logs/jobsearch-agent"
mkdir -p "$LA" "$LOGS"

for name in com.jobsearch-agent.nightly com.jobsearch-agent.phoenix; do
  plist="$REPO/deploy/$name.plist"
  sed "s|__REPO__|$REPO|g; s|__HOME__|$HOME|g" "$plist" > "$LA/$name.plist"
  launchctl bootout "gui/$(id -u)/$name" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$LA/$name.plist"
  echo "loaded $name"
done

echo
echo "nightly:    daily 02:30  -> $LOGS/nightly.out.log"
echo "phoenix:    keepalive    -> $LOGS/phoenix.out.log (UI http://localhost:6006)"
echo
echo "test nightly now:  launchctl kickstart gui/$(id -u)/com.jobsearch-agent.nightly"
echo "stop phoenix:      launchctl bootout gui/$(id -u)/com.jobsearch-agent.phoenix"
