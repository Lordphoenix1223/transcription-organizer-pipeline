from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass(frozen=True)
class AppConfig:
    base_dir: Path
    recordings_dir: Path
    transcripts_dir: Path
    logs_dir: Path
    state_db_path: Path
    metadata_path: Path
    enable_notion: bool
    notion_api_key: str
    notion_database_id: str
    api_key: str
    function_id: str
    function_version_id: Optional[str]
    grpc_server: str
    use_ssl: bool
    ssl_cert: Optional[str]
    language_code: str
    sample_rate_hz: int
    max_alternatives: int
    enable_automatic_punctuation: bool
    verbatim_transcripts: bool
    retry_max_attempts: int
    retry_base_delay_seconds: float
    retry_max_delay_seconds: float
    file_settle_seconds: float
    scan_interval_seconds: float
    log_level: str


def _as_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _detect_blocked_llm_keys() -> list[str]:
    return [name for name in BLOCKED_LLM_ENV_VARS if os.getenv(name, "").strip()]


def assert_no_external_llm_keys() -> None:
    blocked = _detect_blocked_llm_keys()
    if blocked:
        raise RuntimeError(
            "External or paid LLM API keys are not allowed in this pipeline. "
            f"Remove these environment variables and try again: {', '.join(blocked)}"
        )


def _env_name(prefix: str, suffix: str) -> str:
    return f"{prefix}{suffix}"


BLOCKED_LLM_ENV_VARS = (
    _env_name("OPENAI", "_API_KEY"),
    _env_name("OPENAI", "_ORG_ID"),
    _env_name("OPENAI", "_PROJECT_ID"),
    _env_name("ANTHROPIC", "_API_KEY"),
    _env_name("GEMINI", "_API_KEY"),
    _env_name("GOOGLE", "_API_KEY"),
    _env_name("MISTRAL", "_API_KEY"),
    _env_name("COHERE", "_API_KEY"),
    _env_name("TOGETHER", "_API_KEY"),
    _env_name("DEEPSEEK", "_API_KEY"),
    _env_name("PERPLEXITY", "_API_KEY"),
    _env_name("OPENROUTER", "_API_KEY"),
    _env_name("AZURE", "_" "OPENAI" "_API_KEY"),
    _env_name("XAI", "_API_KEY"),
    _env_name("GROQ", "_API_KEY"),
    _env_name("FIREWORKS", "_API_KEY"),
    _env_name("DEEPINFRA", "_API_TOKEN"),
    _env_name("REPLICATE", "_API_TOKEN"),
)


def load_config(base_dir: Optional[str] = None) -> AppConfig:
    resolved_base_dir = Path(base_dir or Path(__file__).resolve().parents[1]).resolve()
    load_dotenv(resolved_base_dir / ".env")
    assert_no_external_llm_keys()

    recordings_dir = Path(os.getenv("RECORDINGS_DIR", resolved_base_dir / "Recordings")).expanduser().resolve()
    transcripts_dir = Path(os.getenv("TRANSCRIPTS_DIR", resolved_base_dir / "Transcripts")).expanduser().resolve()
    logs_dir = Path(os.getenv("LOGS_DIR", resolved_base_dir / "logs")).expanduser().resolve()
    state_db_path = Path(os.getenv("STATE_DB_PATH", logs_dir / "transcription_state.sqlite3")).expanduser().resolve()
    metadata_path = Path(os.getenv("METADATA_PATH", transcripts_dir / "metadata.jsonl")).expanduser().resolve()

    return AppConfig(
        base_dir=resolved_base_dir,
        recordings_dir=recordings_dir,
        transcripts_dir=transcripts_dir,
        logs_dir=logs_dir,
        state_db_path=state_db_path,
        metadata_path=metadata_path,
        enable_notion=_as_bool(os.getenv("ENABLE_NOTION"), False),
        notion_api_key=os.getenv("NOTION_API_KEY", "").strip(),
        notion_database_id=os.getenv("NOTION_DATABASE_ID", "").strip(),
        api_key=os.getenv("NVCF_API_KEY", "").strip(),
        function_id=os.getenv("NVCF_FUNCTION_ID", "").strip(),
        function_version_id=os.getenv("NVCF_FUNCTION_VERSION_ID", "").strip() or None,
        grpc_server=os.getenv("NVCF_GRPC_SERVER", "grpc.nvcf.nvidia.com:443").strip(),
        use_ssl=_as_bool(os.getenv("NVCF_USE_SSL"), True),
        ssl_cert=os.getenv("NVCF_SSL_CERT", "").strip() or None,
        language_code=os.getenv("RIVA_LANGUAGE_CODE", "en-US").strip(),
        sample_rate_hz=int(os.getenv("RIVA_SAMPLE_RATE_HZ", "16000")),
        max_alternatives=int(os.getenv("RIVA_MAX_ALTERNATIVES", "1")),
        enable_automatic_punctuation=_as_bool(os.getenv("RIVA_ENABLE_AUTOMATIC_PUNCTUATION"), True),
        verbatim_transcripts=_as_bool(os.getenv("RIVA_VERBATIM_TRANSCRIPTS"), False),
        retry_max_attempts=max(1, int(os.getenv("RETRY_MAX_ATTEMPTS", "5"))),
        retry_base_delay_seconds=float(os.getenv("RETRY_BASE_DELAY_SECONDS", "5")),
        retry_max_delay_seconds=float(os.getenv("RETRY_MAX_DELAY_SECONDS", "120")),
        file_settle_seconds=float(os.getenv("FILE_SETTLE_SECONDS", "10")),
        scan_interval_seconds=float(os.getenv("SCAN_INTERVAL_SECONDS", "5")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
