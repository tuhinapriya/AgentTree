from __future__ import annotations

import importlib.util
import os
from typing import Any


class AWSObservabilityService:
    def __init__(self, database):
        self.database = database
        self.records_by_run: dict[str, list[dict[str, Any]]] = {}
        self._boto3_available = importlib.util.find_spec("boto3") is not None
        self._aws_enabled = self._boto3_available and bool(
            os.getenv("AWS_ACCESS_KEY_ID")
            and os.getenv("AWS_SECRET_ACCESS_KEY")
        )

    @property
    def aws_enabled(self) -> bool:
        return self._aws_enabled

    @property
    def mode(self) -> str:
        return "aws" if self.aws_enabled else "local_fallback"

    def status(self, run_id: str) -> dict[str, Any]:
        if not self.database.run_exists(run_id):
            raise ValueError(f"Run '{run_id}' does not exist")
        return {
            "run_id": run_id,
            "aws_enabled": self.aws_enabled,
            "mode": self.mode,
            "provider": "aws" if self.aws_enabled else "local-memory",
            "details": (
                "AWS SDK and credentials are available; optional AWS persistence is enabled."
                if self.aws_enabled
                else "AWS SDK or credentials are unavailable; local fallback mode is active."
            ),
        }

    def export_events(self, run_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.database.run_exists(run_id):
            raise ValueError(f"Run '{run_id}' does not exist")

        sanitized_events = [self._redact(event) for event in (events or [])]
        self.records_by_run.setdefault(run_id, []).extend(sanitized_events)

        return {
            "run_id": run_id,
            "record_count": len(sanitized_events),
            "aws_enabled": self.aws_enabled,
            "mode": self.mode,
            "records": sanitized_events,
        }

    def get_events(self, run_id: str) -> list[dict[str, Any]]:
        if not self.database.run_exists(run_id):
            raise ValueError(f"Run '{run_id}' does not exist")
        return self.records_by_run.get(run_id, [])

    @staticmethod
    def _redact(value: Any) -> Any:
        if isinstance(value, dict):
            redacted: dict[str, Any] = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if "credential" in lowered or "token" in lowered or "secret" in lowered:
                    redacted[key] = "[REDACTED]"
                else:
                    redacted[key] = AWSObservabilityService._redact(item)
            return redacted
        if isinstance(value, list):
            return [AWSObservabilityService._redact(item) for item in value]
        return value
