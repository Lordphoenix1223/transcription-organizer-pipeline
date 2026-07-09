#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT_ID="com.customer-interview.transcription"
PLIST_TEMPLATE="$ROOT_DIR/launchd/$AGENT_ID.plist.example"
PLIST_DEST="$HOME/Library/LaunchAgents/$AGENT_ID.plist"

mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__REPO_ROOT__|$ROOT_DIR|g" "$PLIST_TEMPLATE" > "$PLIST_DEST"

launchctl bootout "gui/$(id -u)" "$PLIST_DEST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DEST"
launchctl enable "gui/$(id -u)/$AGENT_ID"
launchctl kickstart -k "gui/$(id -u)/$AGENT_ID"

echo "Installed and started $AGENT_ID"
