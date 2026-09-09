from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4
from typing import Any

from guardrails_text2sql.engine import PromptEngine
from guardrails_text2sql.execution import QueryExecutor
from guardrails_text2sql.generation import SQLGenerator
from guardrails_text2sql.models import (
    ClarificationRequest,
    GeneratedSQL,
    GuardrailViolation,
    HallucinationValidationResult,
    QueryExecutionResult,
)
from guardrails_text2sql.validation import HallucinationDetector


@dataclass(frozen=True)
class QueryAttempt:
    generated: GeneratedSQL | None
    execution: QueryExecutionResult | None
    validation: HallucinationValidationResult | None
    alternative_generated: GeneratedSQL | None = None
    alternative_execution: QueryExecutionResult | None = None
    guardrail_warnings: tuple[str, ...] = ()
    guardrail_violations: tuple[GuardrailViolation, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class QueryServiceResult:
    question: str
    query_id: str = field(default_factory=lambda: uuid4().hex)
    sql: str | None = None
    explanation: str | None = None
    rows: tuple[dict[str, Any], ...] = ()
    confidence: float = 0.0
    retry_count: int = 0
    guardrail_warnings: tuple[str, ...] = ()
    validation: HallucinationValidationResult | None = None
    clarification: ClarificationRequest | None = None
    attempts: tuple[QueryAttempt, ...] = ()
    error: str | None = None


class QueryService:
    def __init__(
        self,
        prompt_engine: PromptEngine,
        generator: SQLGenerator,
        executor: QueryExecutor,
        detector: HallucinationDetector,
        *,
        alternative_generator: SQLGenerator | None = None,
        max_attempts: int = 3,
        history_limit: int = 100,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")
        if history_limit < 1:
            raise ValueError("history_limit must be at least 1.")
        self.prompt_engine = prompt_engine
        self.generator = generator
        self.executor = executor
        self.detector = detector
        self.alternative_generator = alternative_generator
        self.max_attempts = max_attempts
        self.history_limit = history_limit
        self._history: list[QueryServiceResult] = []

    def query(self, question: str) -> QueryServiceResult:
        prompt_result = self.prompt_engine.build(question)
        if prompt_result.needs_clarification:
            result = QueryServiceResult(question=question, clarification=prompt_result.clarification)
            self._remember(result)
            return result
        if prompt_result.prompt is None:
            raise ValueError("Prompt engine returned no prompt for a non-clarification request.")

        attempts: list[QueryAttempt] = []
        prompt = prompt_result.prompt
        for attempt_number in range(self.max_attempts):
            generated = self.generator.generate(prompt)
            guardrail_result = self.executor.validate(generated.sql)
            if not guardrail_result.allowed or guardrail_result.sql is None:
                attempt = QueryAttempt(
                    generated=generated,
                    execution=None,
                    validation=None,
                    guardrail_warnings=guardrail_result.warnings,
                    guardrail_violations=guardrail_result.violations,
                    error="Unsafe SQL blocked.",
                )
                attempts.append(attempt)
                result = QueryServiceResult(
                    question=question,
                    sql=generated.sql,
                    explanation=generated.explanation,
                    confidence=generated.confidence,
                    retry_count=attempt_number,
                    guardrail_warnings=guardrail_result.warnings,
                    attempts=tuple(attempts),
                    error="Unsafe SQL blocked.",
                )
                self._remember(result)
                return result

            execution = self.executor.execute(guardrail_result.sql)
            alternative_generated = None
            alternative_execution = None
            if self.alternative_generator is not None:
                alternative_generated = self.alternative_generator.generate(
                    f"{prompt}\n\nProduce an independent SQL approach. Do not copy the first approach."
                )
                alternative_guardrail = self.executor.validate(alternative_generated.sql)
                if alternative_guardrail.allowed and alternative_guardrail.sql is not None:
                    alternative_execution = self.executor.execute(alternative_guardrail.sql)
            validation = self.detector.validate(
                question,
                generated,
                execution,
                alternative_execution=alternative_execution,
            )
            attempts.append(
                QueryAttempt(
                    generated=generated,
                    execution=execution,
                    validation=validation,
                    alternative_generated=alternative_generated,
                    alternative_execution=alternative_execution,
                    guardrail_warnings=guardrail_result.warnings,
                )
            )
            if validation.passed or attempt_number == self.max_attempts - 1:
                result = QueryServiceResult(
                    question=question,
                    sql=execution.sql,
                    explanation=generated.explanation,
                    rows=execution.rows,
                    confidence=validation.confidence,
                    retry_count=attempt_number,
                    guardrail_warnings=guardrail_result.warnings,
                    validation=validation,
                    attempts=tuple(attempts),
                )
                self._remember(result)
                return result
            prompt = f"{prompt_result.prompt}\n\nPrevious attempt feedback: {' '.join(validation.reasons)}"

        raise RuntimeError("Query service exhausted its attempt budget without a result.")

    def history(self) -> tuple[QueryServiceResult, ...]:
        return tuple(reversed(self._history))

    def _remember(self, result: QueryServiceResult) -> None:
        self._history.append(result)
        del self._history[:-self.history_limit]