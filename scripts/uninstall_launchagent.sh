#!/bin/bash
set -euo pipefail

AGENT_ID="com.customer-interview.transcription"
PLIST_DEST="$HOME/Library/LaunchAgents/$AGENT_ID.plist"

launchctl bootout "gui/$(id -u)" "$PLIST_DEST" 2>/dev/null || true
rm -f "$PLIST_DEST"

echo "Removed $AGENT_ID"
