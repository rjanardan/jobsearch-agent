#!/usr/bin/env bash
# Unload jobsearch-agent LaunchAgents and remove their plists (logs are kept).
set -euo pipefail

LA="$HOME/Library/LaunchAgents"
for name in com.jobsearch-agent.nightly com.jobsearch-agent.phoenix; do
  launchctl bootout "gui/$(id -u)/$name" 2>/dev/null || true
  rm -f "$LA/$name.plist"
  echo "unloaded $name"
done
