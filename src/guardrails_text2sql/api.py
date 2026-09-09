from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from guardrails_text2sql.models import ClarificationRequest, SchemaInfo
from guardrails_text2sql.service import QueryService, QueryServiceResult


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)


class FeedbackRequest(BaseModel):
    query_id: str = Field(min_length=1)
    correct: bool
    note: str = Field(default="", max_length=2000)


def create_app(service: QueryService) -> FastAPI:
    app = FastAPI(title="Guardrails Text-to-SQL API", version="0.1.0")
    feedback: dict[str, dict[str, Any]] = {}

    @app.post("/v1/query")
    def query(request: QueryRequest) -> dict[str, Any]:
        return _query_payload(service.query(request.question))

    @app.get("/v1/schema")
    def schema() -> dict[str, Any]:
        return _schema_payload(service.prompt_engine.schema)

    @app.get("/v1/history")
    def history(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        return {"items": [_query_payload(item) for item in service.history()[:limit]]}

    @app.post("/v1/feedback")
    def submit_feedback(request: FeedbackRequest) -> dict[str, Any]:
        known_ids = {item.query_id for item in service.history()}
        if request.query_id not in known_ids:
            raise HTTPException(status_code=404, detail="Query not found.")
        feedback[request.query_id] = {
            "query_id": request.query_id,
            "correct": request.correct,
            "note": request.note,
        }
        return feedback[request.query_id]

    @app.get("/v1/feedback")
    def list_feedback() -> dict[str, Any]:
        return {"items": list(feedback.values())}

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app


def _query_payload(result: QueryServiceResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query_id": result.query_id,
        "question": result.question,
        "sql": result.sql,
        "explanation": result.explanation,
        "rows": list(result.rows),
        "confidence": result.confidence,
        "retry_count": result.retry_count,
        "guardrail_warnings": list(result.guardrail_warnings),
        "error": result.error,
    }
    if result.validation is not None:
        payload["validation"] = {
            "confidence": result.validation.confidence,
            "passed": result.validation.passed,
            "reasons": list(result.validation.reasons),
            "signals": [
                {
                    "name": signal.name,
                    "score": signal.score,
                    "passed": signal.passed,
                    "explanation": signal.explanation,
                }
                for signal in result.validation.signals
            ],
        }
    if result.clarification is not None:
        payload["clarification"] = _clarification_payload(result.clarification)
    return payload


def _clarification_payload(clarification: ClarificationRequest) -> dict[str, Any]:
    return {
        "term": clarification.term,
        "question": clarification.question,
        "options": [
            {"label": option.label, "meaning": option.meaning, "example_sql": option.example_sql}
            for option in clarification.options
        ],
    }


def _schema_payload(schema: SchemaInfo) -> dict[str, Any]:
    return {
        "tables": [
            {
                "name": table.name,
                "description": table.description,
                "columns": [
                    {
                        "name": column.name,
                        "data_type": column.data_type,
                        "nullable": column.nullable,
                        "primary_key": column.primary_key,
                        "sample_values": list(column.sample_values),
                        "description": column.description,
                    }
                    for column in table.columns
                ],
                "foreign_keys": [
                    {
                        "constrained_columns": list(foreign_key.constrained_columns),
                        "referred_table": foreign_key.referred_table,
                        "referred_columns": list(foreign_key.referred_columns),
                    }
                    for foreign_key in table.foreign_keys
                ],
            }
            for table in schema.tables
        ]
    }