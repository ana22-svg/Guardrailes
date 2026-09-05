from __future__ import annotations

import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from guardrails_text2sql.guardrails import SQLGuardrailMiddleware
from guardrails_text2sql.models import GuardrailResult, QueryExecutionResult


class QueryExecutor:
    def __init__(self, engine: Engine, guardrails: SQLGuardrailMiddleware | None = None) -> None:
        self.engine = engine
        self.guardrails = guardrails or SQLGuardrailMiddleware()

    def validate(self, sql: str) -> GuardrailResult:
        return self.guardrails.validate(sql)

    def execute(self, sql: str) -> QueryExecutionResult:
        guardrail_result = self.guardrails.validate(sql)
        if not guardrail_result.allowed or guardrail_result.sql is None:
            messages = "; ".join(violation.message for violation in guardrail_result.violations)
            raise ValueError(f"Unsafe SQL blocked: {messages}")

        safe_sql = guardrail_result.sql
        explain_plan = self._explain(safe_sql)
        started = time.perf_counter()
        with self.engine.connect() as connection:
            transaction = connection.begin()
            try:
                result = connection.execute(text(safe_sql))
                rows = tuple(dict(row._mapping) for row in result)
            finally:
                transaction.rollback()
        elapsed_ms = (time.perf_counter() - started) * 1000

        return QueryExecutionResult(
            sql=safe_sql,
            rows=rows,
            row_count=len(rows),
            execution_time_ms=elapsed_ms,
            explain_plan=explain_plan,
        )

    def _explain(self, sql: str) -> tuple[dict[str, Any], ...]:
        explain_prefix = "EXPLAIN QUERY PLAN" if self.engine.dialect.name == "sqlite" else "EXPLAIN"
        try:
            with self.engine.connect() as connection:
                result = connection.execute(text(f"{explain_prefix} {sql}"))
                return tuple(dict(row._mapping) for row in result)
        except Exception:
            return ()
