from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .analysis import HeuristicAnalysis
from .config import AppConfig
from .field_extractor import InterviewExtraction
from .notion_fields import build_notion_properties, load_notion_database_schema, print_notion_schema

if TYPE_CHECKING:
    from notion_client import Client


@dataclass
class NotionUpdater:
    config: AppConfig
    logger: logging.Logger

    def __post_init__(self) -> None:
        if not self.config.notion_api_key:
            raise ValueError("NOTION_API_KEY must be set.")
        if not self.config.notion_database_id:
            raise ValueError("NOTION_DATABASE_ID must be set.")
        from notion_client import Client

        self._client = Client(auth=self.config.notion_api_key)
        self._schema = load_notion_database_schema(self._client, self.config.notion_database_id)
        self.logger.info(
            "Detected Notion schema for database %s:\n%s",
            self.config.notion_database_id,
            print_notion_schema(self._schema),
        )

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def publish_interview_row(
        self,
        title: str,
        transcript: str,
        transcript_filename: str,
        analysis: HeuristicAnalysis,
        recording_date: str | None = None,
        participant_name: str | None = None,
        extraction: InterviewExtraction | None = None,
        transcript_bundle_name: str | None = None,
        transcript_metadata: dict[str, object] | None = None,
        fallback_timestamp: str | None = None,
    ) -> str:
        database_id = self.config.notion_database_id
        self.logger.info(
            "Publishing transcript %s to Notion database %s",
            transcript_filename,
            database_id,
        )

        properties = build_notion_properties(
            title=title,
            transcript=transcript,
            analysis=analysis,
            recording_date=recording_date,
            participant_name=participant_name,
            extraction=extraction,
            schema=self._schema,
            logger=self.logger,
            transcript_bundle_name=transcript_bundle_name,
            transcript_metadata=transcript_metadata,
            fallback_timestamp=fallback_timestamp,
        )

        try:
            self.logger.info("Creating new Notion row in database %s", database_id)
            page = self._client.pages.create(
                parent={"database_id": database_id},
                properties=properties,
            )
        except Exception:
            self.logger.exception("Failed to publish transcript %s to Notion database %s", transcript_filename, database_id)
            raise

        row_id = page["id"]
        self.logger.info("Successfully published transcript %s to Notion database %s", transcript_filename, database_id)
        return row_id

    def update_database_page(self, transcript: str, transcript_filename: str, analysis: HeuristicAnalysis) -> str:
        return self.publish_interview_row(
            title=transcript_filename.rsplit(".", 1)[0],
            transcript=transcript,
            transcript_filename=transcript_filename,
            analysis=analysis,
        )
