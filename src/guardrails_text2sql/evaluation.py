from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from guardrails_text2sql.service import QueryServiceResult


@dataclass(frozen=True)
class GoldenCase:
    question: str
    expected_sql: str | None = None
    expected_rows: tuple[dict[str, Any], ...] | None = None
    category: str = "uncategorized"
    expect_hallucination: bool = False
    expect_guardrail_block: bool = False


def load_golden_cases(path: str | Path) -> tuple[GoldenCase, ...]:
    """Load a frozen evaluation dataset from a JSON file."""
    records = json.loads(Path(path).read_text(encoding="utf-8"))
    return tuple(
        GoldenCase(
            question=str(record["question"]),
            expected_sql=record.get("expected_sql"),
            expected_rows=tuple(record["expected_rows"]) if record.get("expected_rows") is not None else None,
            category=str(record.get("category", "uncategorized")),
            expect_hallucination=bool(record.get("expect_hallucination", False)),
            expect_guardrail_block=bool(record.get("expect_guardrail_block", False)),
        )
        for record in records
    )


@dataclass(frozen=True)
class EvaluationCaseResult:
    case: GoldenCase
    response: QueryServiceResult
    sql_exact_match: bool
    execution_match: bool | None
    hallucination_flagged: bool
    guardrail_blocked: bool


@dataclass(frozen=True)
class EvaluationReport:
    cases: tuple[EvaluationCaseResult, ...]
    sql_exact_match_rate: float
    execution_match_rate: float
    hallucination_detection_rate: float
    hallucination_false_alarm_rate: float
    guardrail_block_rate: float
    category_metrics: dict[str, dict[str, float]]

    @property
    def total_cases(self) -> int:
        return len(self.cases)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "sql_exact_match_rate": self.sql_exact_match_rate,
            "execution_match_rate": self.execution_match_rate,
            "hallucination_detection_rate": self.hallucination_detection_rate,
            "hallucination_false_alarm_rate": self.hallucination_false_alarm_rate,
            "guardrail_block_rate": self.guardrail_block_rate,
            "category_metrics": self.category_metrics,
        }


class EvaluationSuite:
    def __init__(self, runner: Callable[[GoldenCase], QueryServiceResult]) -> None:
        self.runner = runner

    def run(self, cases: Iterable[GoldenCase]) -> EvaluationReport:
        results = tuple(self._evaluate_case(case) for case in cases)
        return EvaluationReport(
            cases=results,
            sql_exact_match_rate=self._rate(sum(result.sql_exact_match for result in results), len(results)),
            execution_match_rate=self._execution_rate(results),
            hallucination_detection_rate=self._hallucination_detection_rate(results),
            hallucination_false_alarm_rate=self._false_alarm_rate(results),
            guardrail_block_rate=self._guardrail_block_rate(results),
            category_metrics=self._category_metrics(results),
        )

    def _evaluate_case(self, case: GoldenCase) -> EvaluationCaseResult:
        response = self.runner(case)
        flagged = response.error is not None or (
            response.validation is not None and not response.validation.passed
        )
        blocked = any(attempt.guardrail_violations for attempt in response.attempts)
        execution_match = None
        if case.expected_rows is not None:
            execution_match = response.error is None and _canonical_rows(response.rows) == _canonical_rows(case.expected_rows)
        return EvaluationCaseResult(
            case=case,
            response=response,
            sql_exact_match=(
                case.expected_sql is not None
                and response.sql is not None
                and _normalize_sql(case.expected_sql) == _normalize_sql(response.sql)
            ),
            execution_match=execution_match,
            hallucination_flagged=flagged,
            guardrail_blocked=blocked,
        )

    def _execution_rate(self, results: tuple[EvaluationCaseResult, ...]) -> float:
        measured = [result for result in results if result.execution_match is not None]
        return self._rate(sum(result.execution_match is True for result in measured), len(measured))

    def _hallucination_detection_rate(self, results: tuple[EvaluationCaseResult, ...]) -> float:
        hallucinated = [result for result in results if result.case.expect_hallucination]
        return self._rate(sum(result.hallucination_flagged for result in hallucinated), len(hallucinated))

    def _false_alarm_rate(self, results: tuple[EvaluationCaseResult, ...]) -> float:
        expected_correct = [
            result
            for result in results
            if not result.case.expect_hallucination and not result.case.expect_guardrail_block
        ]
        return self._rate(sum(result.hallucination_flagged for result in expected_correct), len(expected_correct))

    def _guardrail_block_rate(self, results: tuple[EvaluationCaseResult, ...]) -> float:
        dangerous = [result for result in results if result.case.expect_guardrail_block]
        return self._rate(sum(result.guardrail_blocked for result in dangerous), len(dangerous))

    def _category_metrics(self, results: tuple[EvaluationCaseResult, ...]) -> dict[str, dict[str, float]]:
        grouped: dict[str, list[EvaluationCaseResult]] = {}
        for result in results:
            grouped.setdefault(result.case.category, []).append(result)
        metrics: dict[str, dict[str, float]] = {}
        for category, category_results in grouped.items():
            measured = [result for result in category_results if result.execution_match is not None]
            metrics[category] = {
                "count": float(len(category_results)),
                "execution_match_rate": self._rate(
                    sum(result.execution_match is True for result in measured), len(measured)
                ),
            }
        return metrics

    def _rate(self, numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 4) if denominator else 0.0


def _normalize_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.strip().rstrip(";")).lower()


def _canonical_rows(rows: tuple[dict[str, Any], ...]) -> tuple[tuple[tuple[str, str], ...], ...]:
    return tuple(
        tuple(sorted((key, _canonical_value(value)) for key, value in row.items()))
        for row in rows
    )


def _canonical_value(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    return repr(value)