from __future__ import annotations

import time
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from guardrails_text2sql.guardrails import SQLGuardrailMiddleware
from guardrails_text2sql.models import GuardrailResult, GuardrailViolation, QueryExecutionResult


class QueryExecutor:
    def __init__(self, engine: Engine, guardrails: SQLGuardrailMiddleware | None = None) -> None:
        self.engine = engine
        self.guardrails = guardrails or SQLGuardrailMiddleware()

    def validate(self, sql: str) -> GuardrailResult:
        result = self.guardrails.validate(sql)
        if not result.allowed or result.sql is None:
            return result

        max_estimated_rows = self.guardrails.config.max_estimated_rows
        if max_estimated_rows is None:
            return result

        plan = self._explain(result.sql)
        estimated_rows = self._estimated_rows(plan)
        if estimated_rows is None or estimated_rows <= max_estimated_rows:
            return result

        violation = GuardrailViolation(
            "estimated_rows",
            f"Estimated scan of {estimated_rows} rows exceeds limit {max_estimated_rows}.",
        )
        return GuardrailResult(
            allowed=False,
            sql=None,
            violations=(*result.violations, violation),
            warnings=result.warnings,
        )

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

    def _estimated_rows(self, plan: tuple[dict[str, Any], ...]) -> int | None:
        estimates: list[int] = []
        for row in plan:
            for key, value in row.items():
                key_text = str(key).lower()
                value_text = str(value)
                if "row" in key_text and value_text.isdigit():
                    estimates.append(int(value_text))
                for match in re.finditer(r"\brows[= ]+(\d+)", value_text, re.IGNORECASE):
                    estimates.append(int(match.group(1)))
        return max(estimates, default=None)
