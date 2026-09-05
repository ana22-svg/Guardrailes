from __future__ import annotations

import json
from typing import Any, Protocol

from guardrails_text2sql.models import GeneratedSQL


class SQLGenerator(Protocol):
    def generate(self, prompt: str) -> GeneratedSQL:
        """Return structured SQL output from an LLM or deterministic test double."""


class StructuredOutputParser:
    REQUIRED_FIELDS = {"sql", "explanation", "confidence", "tables", "columns"}

    def parse_json(self, payload: str | dict[str, Any]) -> GeneratedSQL:
        data = json.loads(payload) if isinstance(payload, str) else payload
        missing = self.REQUIRED_FIELDS - set(data)
        if missing:
            raise ValueError(f"Missing generated SQL fields: {', '.join(sorted(missing))}")

        confidence = float(data["confidence"])
        if not 0 <= confidence <= 1:
            raise ValueError("Generated SQL confidence must be between 0 and 1.")

        return GeneratedSQL(
            sql=str(data["sql"]),
            explanation=str(data["explanation"]),
            confidence=confidence,
            tables=tuple(str(table) for table in data["tables"]),
            columns=tuple(str(column) for column in data["columns"]),
        )
