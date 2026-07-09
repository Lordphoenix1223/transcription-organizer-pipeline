#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SAMPLE_TRANSCRIPT="$ROOT_DIR/tests/sample_transcript.txt"
OUTPUT_DIR="$ROOT_DIR/tests/output"
ANALYSIS_MD="$OUTPUT_DIR/analysis.md"
ANALYSIS_JSON="$OUTPUT_DIR/analysis.json"

PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

if [ ! -f "$SAMPLE_TRANSCRIPT" ]; then
  echo "Missing sample transcript: $SAMPLE_TRANSCRIPT" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

"$PYTHON_BIN" - <<PY
import json
import sys
from pathlib import Path

root = Path("$ROOT_DIR")
sys.path.insert(0, str(root))

from transcription_service.analysis import analyze_transcript

sample_path = Path("$SAMPLE_TRANSCRIPT")
output_dir = Path("$OUTPUT_DIR")
analysis_md = Path("$ANALYSIS_MD")
analysis_json = Path("$ANALYSIS_JSON")

transcript = sample_path.read_text(encoding="utf-8").strip()
analysis = analyze_transcript(transcript)

analysis_md.write_text(analysis.to_markdown() + "\n", encoding="utf-8")
analysis_json.write_text(
    json.dumps(analysis.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

if not analysis_md.exists() or analysis_md.stat().st_size == 0:
    raise SystemExit("analysis.md was not generated")
if not analysis_json.exists() or analysis_json.stat().st_size == 0:
    raise SystemExit("analysis.json was not generated")
PY

if rg -n -i \
  -g '!**/build/**' \
  -g '!**/node_modules/**' \
  -g '!**/.venv/**' \
  -g '!**/tests/output/**' \
  -g '!**/*.md' \
  -e '^\s*(from\s+openai\s+import|import\s+openai\b)' \
  -e '^\s*(from\s+anthropic\s+import|import\s+anthropic\b)' \
  -e '^\s*(from\s+google(\.generativeai|\.genai)?\s+import|import\s+google(\.generativeai|\.genai)?\b)' \
  -e '^\s*(from\s+vertexai\s+import|import\s+vertexai\b)' \
  -e '\bOpenAI\s*\(' \
  -e '\bAnthropic\s*\(' \
  -e '\bGenerativeModel\s*\(' \
  -e '\bGoogleGenerativeAI\s*\(' \
  -e '\bgenai\.[A-Za-z_][A-Za-z0-9_]*\s*\(' \
  "$ROOT_DIR"; then
  echo "Found paid LLM import or API-call paths. Remove them before using this pipeline." >&2
  exit 1
fi

printf 'PASS\n'
