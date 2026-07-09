from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import grpc
import riva.client
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .config import AppConfig


def is_retryable_exception(error: BaseException) -> bool:
    if isinstance(error, grpc.RpcError):
        try:
            return error.code() in {
                grpc.StatusCode.UNAVAILABLE,
                grpc.StatusCode.DEADLINE_EXCEEDED,
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                grpc.StatusCode.INTERNAL,
            }
        except Exception:
            return True
    return isinstance(error, (ConnectionError, TimeoutError, OSError))


@dataclass
class NvidiaTranscriber:
    config: AppConfig

    def __post_init__(self) -> None:
        if not self.config.api_key:
            raise ValueError("NVCF_API_KEY must be set.")
        if not self.config.function_id:
            raise ValueError("NVCF_FUNCTION_ID must be set.")

        auth_metadata = [("authorization", f"Bearer {self.config.api_key}"), ("function-id", self.config.function_id)]
        if self.config.function_version_id:
            auth_metadata.append(("function-version-id", self.config.function_version_id))

        self._auth = riva.client.Auth(
            self.config.ssl_cert,
            self.config.use_ssl,
            self.config.grpc_server,
            auth_metadata,
        )
        self._asr = riva.client.ASRService(self._auth)

    @retry(
        retry=retry_if_exception(is_retryable_exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def transcribe_wav(self, wav_path: Path) -> str:
        wav_bytes = wav_path.read_bytes()
        recognition_config = riva.client.RecognitionConfig(
            language_code=self.config.language_code,
            max_alternatives=self.config.max_alternatives,
            enable_automatic_punctuation=self.config.enable_automatic_punctuation,
            audio_channel_count=1,
            verbatim_transcripts=self.config.verbatim_transcripts,
            sample_rate_hertz=self.config.sample_rate_hz,
        )
        response = self._asr.offline_recognize(wav_bytes, recognition_config)
        if not response.results:
            return ""

        transcripts: list[str] = []
        for result in response.results:
            alternatives = getattr(result, "alternatives", None) or []
            if not alternatives:
                continue
            transcript = alternatives[0].transcript.strip()
            if transcript:
                transcripts.append(transcript)
        return "\n".join(transcripts).strip()
