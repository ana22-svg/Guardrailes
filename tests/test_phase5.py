from __future__ import annotations

from guardrails_text2sql import (
    EvaluationSuite,
    GeneratedSQL,
    GoldenCase,
    GuardrailViolation,
    HallucinationValidationResult,
    QueryAttempt,
    QueryServiceResult,
    ValidationSignal,
    load_golden_cases,
)


def test_evaluation_suite_reports_accuracy_detection_and_guardrail_metrics():
    correct = QueryServiceResult(
        question="List customer names",
        sql=" select name\n from customers; ",
        rows=({"name": "Acme"},),
        validation=HallucinationValidationResult(
            confidence=0.95,
            signals=(ValidationSignal("result_sanity", 1.0, True, "ok"),),
        ),
    )
    hallucinated = QueryServiceResult(
        question="Show net revenue",
        sql="SELECT gross_revenue FROM orders",
        validation=HallucinationValidationResult(
            confidence=0.2,
            signals=(ValidationSignal("alignment", 0.0, False, "wrong measure"),),
            reasons=("wrong measure",),
        ),
    )
    blocked = QueryServiceResult(
        question="Delete all customers",
        sql="DELETE FROM customers",
        error="Unsafe SQL blocked.",
        attempts=(
            QueryAttempt(
                generated=GeneratedSQL("DELETE FROM customers", "Deletes customers.", 0.9),
                execution=None,
                validation=None,
                guardrail_violations=(GuardrailViolation("non_select_query", "blocked"),),
                error="Unsafe SQL blocked.",
            ),
        ),
    )
    responses = {
        "List customer names": correct,
        "Show net revenue": hallucinated,
        "Delete all customers": blocked,
    }

    report = EvaluationSuite(lambda case: responses[case.question]).run(
        [
            GoldenCase(
                question="List customer names",
                expected_sql="SELECT name FROM customers",
                expected_rows=({"name": "Acme"},),
                category="lookup",
            ),
            GoldenCase(
                question="Show net revenue",
                expected_sql="SELECT net_revenue FROM orders",
                category="aggregation",
                expect_hallucination=True,
            ),
            GoldenCase(
                question="Delete all customers",
                category="guardrail",
                expect_guardrail_block=True,
            ),
        ]
    )

    assert report.total_cases == 3
    assert report.sql_exact_match_rate == 0.3333
    assert report.execution_match_rate == 1.0
    assert report.hallucination_detection_rate == 1.0
    assert report.hallucination_false_alarm_rate == 0.0
    assert report.guardrail_block_rate == 1.0
    assert report.category_metrics["lookup"]["execution_match_rate"] == 1.0


def test_repository_golden_dataset_has_fifty_cases_across_required_categories():
    cases = load_golden_cases("data/golden_cases.json")

    assert len(cases) >= 50
    assert {case.category for case in cases} >= {
        "lookup",
        "join",
        "aggregation",
        "date_filter",
        "ambiguous",
        "hallucination",
        "guardrail",
    }