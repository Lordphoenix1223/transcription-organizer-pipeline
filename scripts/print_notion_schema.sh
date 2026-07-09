#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

exec "$PYTHON_BIN" - "$ROOT_DIR" <<'PY'
import sys
from pathlib import Path

from notion_client import Client

from transcription_service.config import load_config
from transcription_service.notion_fields import load_notion_database_schema, print_notion_schema

root = Path(sys.argv[1])
config = load_config(str(root))
if not config.enable_notion:
    raise SystemExit("ENABLE_NOTION=false. Turn it on and configure NOTION_API_KEY / NOTION_DATABASE_ID first.")
client = Client(auth=config.notion_api_key)
schema = load_notion_database_schema(client, config.notion_database_id)
print(print_notion_schema(schema))
PY
