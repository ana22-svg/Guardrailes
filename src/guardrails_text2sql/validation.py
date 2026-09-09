from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from guardrails_text2sql.models import (
    GeneratedSQL,
    HallucinationValidationResult,
    QueryExecutionResult,
    ValidationSignal,
)


class SQLQuestionTranslator(Protocol):
    def translate(self, sql: str) -> str:
        """Describe the question answered by SQL."""


@dataclass(frozen=True)
class ValidationConfig:
    minimum_confidence: float = 0.7
    minimum_alignment: float = 0.7
    minimum_sanity: float = 0.75
    max_null_ratio: float = 0.9


class HallucinationDetector:
    """Combine independent signals that a generated query answers the question."""

    def __init__(
        self,
        *,
        translator: SQLQuestionTranslator | Callable[[str], str] | None = None,
        config: ValidationConfig | None = None,
    ) -> None:
        self.translator = translator
        self.config = config or ValidationConfig()

    def validate(
        self,
        question: str,
        generated: GeneratedSQL,
        execution: QueryExecutionResult,
        *,
        alternative_execution: QueryExecutionResult | None = None,
    ) -> HallucinationValidationResult:
        signals = [self._generation_signal(generated)]
        reasons: list[str] = []

        alignment = self._alignment_signal(question, generated.sql)
        if alignment is not None:
            signals.append(alignment)

        sanity = self._sanity_signal(execution)
        signals.append(sanity)

        if alternative_execution is not None:
            signals.append(self._agreement_signal(execution, alternative_execution))

        confidence = sum(signal.score for signal in signals) / len(signals)
        if confidence < self.config.minimum_confidence:
            reasons.append(f"Combined confidence {confidence:.2f} is below {self.config.minimum_confidence:.2f}.")
        reasons.extend(signal.explanation for signal in signals if not signal.passed)
        return HallucinationValidationResult(
            confidence=round(confidence, 4),
            signals=tuple(signals),
            reasons=tuple(reasons),
        )

    def _generation_signal(self, generated: GeneratedSQL) -> ValidationSignal:
        passed = generated.confidence >= self.config.minimum_confidence
        return ValidationSignal(
            name="generation_confidence",
            score=generated.confidence,
            passed=passed,
            explanation=(
                f"Generator confidence {generated.confidence:.2f} is below "
                f"{self.config.minimum_confidence:.2f}."
                if not passed
                else "Generator confidence cleared the configured threshold."
            ),
        )

    def _alignment_signal(self, question: str, sql: str) -> ValidationSignal | None:
        if self.translator is None:
            return None
        translated = (
            self.translator.translate(sql)
            if hasattr(self.translator, "translate")
            else self.translator(sql)
        )
        score = self._text_alignment(question, translated)
        passed = score >= self.config.minimum_alignment
        return ValidationSignal(
            name="back_translation_alignment",
            score=score,
            passed=passed,
            explanation=(
                f"Back-translation alignment is {score:.2f}; expected at least "
                f"{self.config.minimum_alignment:.2f}."
                if not passed
                else "Back-translation is aligned with the requested question."
            ),
        )

    def _sanity_signal(self, execution: QueryExecutionResult) -> ValidationSignal:
        issues: list[str] = []
        if execution.row_count != len(execution.rows):
            issues.append("reported row count differs from returned rows")
        if execution.row_count and self._null_ratio(execution.rows) > self.config.max_null_ratio:
            issues.append("returned rows are heavily NULL-valued")
        score = 0.0 if issues else 1.0
        passed = score >= self.config.minimum_sanity
        return ValidationSignal(
            name="result_sanity",
            score=score,
            passed=passed,
            explanation=(
                "Result sanity checks passed."
                if not issues
                else f"Result sanity check failed: {', '.join(issues)}."
            ),
        )

    def _agreement_signal(
        self,
        primary: QueryExecutionResult,
        alternative: QueryExecutionResult,
    ) -> ValidationSignal:
        matches = self._canonical_rows(primary.rows) == self._canonical_rows(alternative.rows)
        return ValidationSignal(
            name="multi_query_agreement",
            score=1.0 if matches else 0.0,
            passed=matches,
            explanation=(
                "Independent query results agree."
                if matches
                else "Independent query results disagree."
            ),
        )

    def _text_alignment(self, question: str, translated: str) -> float:
        question_words = self._meaningful_words(question)
        translated_words = self._meaningful_words(translated)
        if not question_words:
            return 0.0
        return len(question_words & translated_words) / len(question_words)

    def _meaningful_words(self, text: str) -> set[str]:
        return {word for word in self._words(text) if len(word) > 2}

    def _words(self, text: str) -> Iterable[str]:
        return (word.strip(".,?!:;()[]{}\"").lower() for word in text.split())

    def _null_ratio(self, rows: tuple[dict[str, Any], ...]) -> float:
        values = [value for row in rows for value in row.values()]
        if not values:
            return 0.0
        return sum(value is None for value in values) / len(values)

    def _canonical_rows(self, rows: tuple[dict[str, Any], ...]) -> tuple[tuple[tuple[str, str], ...], ...]:
        canonical: list[tuple[tuple[str, str], ...]] = []
        for row in rows:
            canonical.append(tuple(sorted((key, self._canonical_value(value)) for key, value in row.items())))
        return tuple(sorted(canonical))

    def _canonical_value(self, value: Any) -> str:
        if isinstance(value, Decimal):
            return format(value, "f")
        return repr(value)