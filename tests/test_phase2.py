from __future__ import annotations

from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, select

from guardrails_text2sql import (
    GeneratedSQL,
    GuardrailConfig,
    HallucinationDetector,
    QueryExecutor,
    QueryExecutionResult,
    SQLGuardrailMiddleware,
    StructuredOutputParser,
)


def build_engine():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    Table(
        "customers",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String, nullable=False),
        Column("region", String, nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            metadata.tables["customers"].insert(),
            [
                {"id": 1, "name": "Acme", "region": "North"},
                {"id": 2, "name": "Globex", "region": "South"},
            ],
        )
    return engine, metadata


def test_structured_output_parser_validates_required_fields_and_confidence():
    parsed = StructuredOutputParser().parse_json(
        {
            "sql": "SELECT id FROM customers",
            "explanation": "Lists customer ids.",
            "confidence": 0.82,
            "tables": ["customers"],
            "columns": ["customers.id"],
        }
    )

    assert parsed.sql == "SELECT id FROM customers"
    assert parsed.confidence == 0.82
    assert parsed.tables == ("customers",)
    assert parsed.columns == ("customers.id",)


def test_guardrails_apply_limit_to_read_only_select():
    guardrails = SQLGuardrailMiddleware(GuardrailConfig(row_limit=25))

    result = guardrails.validate("SELECT id, name FROM customers")

    assert result.allowed
    assert result.sql == "SELECT id, name FROM customers LIMIT 25"
    assert result.warnings == ("Applied LIMIT 25.",)


def test_guardrails_preserve_existing_limit():
    guardrails = SQLGuardrailMiddleware(GuardrailConfig(row_limit=25))

    result = guardrails.validate("SELECT id, name FROM customers LIMIT 5")

    assert result.allowed
    assert result.sql == "SELECT id, name FROM customers LIMIT 5"
    assert result.warnings == ()


def test_guardrails_block_multiple_statements_and_dml():
    guardrails = SQLGuardrailMiddleware()

    result = guardrails.validate("SELECT id FROM customers; DROP TABLE customers;")

    assert not result.allowed
    assert {violation.code for violation in result.violations} == {"multiple_statements"}


def test_guardrails_block_destructive_keyword_after_comment_obfuscation():
    guardrails = SQLGuardrailMiddleware()

    result = guardrails.validate("/* harmless? */ DELETE FROM customers")

    assert not result.allowed
    assert {violation.code for violation in result.violations} == {"non_select_query", "forbidden_keyword"}


def test_guardrails_block_deep_subqueries():
    guardrails = SQLGuardrailMiddleware(GuardrailConfig(max_subquery_depth=2))
    sql = (
        "SELECT id FROM customers WHERE id IN "
        "(SELECT id FROM customers WHERE id IN "
        "(SELECT id FROM customers WHERE id IN "
        "(SELECT id FROM customers)))"
    )

    result = guardrails.validate(sql)

    assert not result.allowed
    assert {violation.code for violation in result.violations} == {"subquery_depth"}


def test_executor_runs_read_only_query_and_rolls_back_transaction():
    engine, metadata = build_engine()
    executor = QueryExecutor(engine, SQLGuardrailMiddleware(GuardrailConfig(row_limit=1)))

    result = executor.execute("SELECT id, name FROM customers ORDER BY id")

    assert result.sql == "SELECT id, name FROM customers ORDER BY id LIMIT 1"
    assert result.row_count == 1
    assert result.rows == ({"id": 1, "name": "Acme"},)
    assert result.explain_plan

    with engine.connect() as connection:
        count = connection.execute(select(metadata.tables["customers"].c.id)).all()
    assert len(count) == 2


def test_executor_raises_for_blocked_sql():
    engine, _ = build_engine()
    executor = QueryExecutor(engine)

    try:
        executor.execute("UPDATE customers SET name = 'x'")
    except ValueError as exc:
        assert "Unsafe SQL blocked" in str(exc)
    else:
        raise AssertionError("Expected unsafe SQL to be blocked")


def test_executor_blocks_queries_above_explain_estimated_row_limit():
    engine, _ = build_engine()
    guardrails = SQLGuardrailMiddleware(GuardrailConfig(max_estimated_rows=100))
    executor = QueryExecutor(engine, guardrails)
    executor._explain = lambda _: ({"QUERY PLAN": "Seq Scan on customers (rows=101)"},)

    result = executor.validate("SELECT id FROM customers")

    assert not result.allowed
    assert {violation.code for violation in result.violations} == {"estimated_rows"}


def test_hallucination_detector_combines_back_translation_and_result_signals():
    generated = GeneratedSQL(
        sql="SELECT region, COUNT(*) AS customer_count FROM customers GROUP BY region",
        explanation="Counts customers by region.",
        confidence=0.9,
    )
    execution = QueryExecutionResult(
        sql=generated.sql,
        rows=({"region": "North"},),
        row_count=1,
        execution_time_ms=1.0,
    )

    result = HallucinationDetector(
        translator=lambda _: "How many customers are in each region?"
    ).validate("How many customers are in each region?", generated, execution)

    assert result.confidence == 0.9667
    assert result.passed
    assert {signal.name for signal in result.signals} == {
        "generation_confidence",
        "back_translation_alignment",
        "result_sanity",
    }


def test_hallucination_detector_flags_null_heavy_results():
    generated = GeneratedSQL("SELECT customers.name FROM customers", "Lists names.", 0.95)
    execution = QueryExecutionResult(
        sql=generated.sql,
        rows=({"name": None}, {"name": None}),
        row_count=2,
        execution_time_ms=1.0,
    )

    result = HallucinationDetector().validate("List customer names", generated, execution)

    assert not result.passed
    assert any("NULL" in reason for reason in result.reasons)


def test_hallucination_detector_flags_disagreeing_independent_queries():
    generated = GeneratedSQL("SELECT region FROM customers", "Lists regions.", 0.9)
    primary = QueryExecutionResult(generated.sql, ({"region": "North"},), 1, 1.0)
    alternative = QueryExecutionResult(generated.sql, ({"region": "South"},), 1, 1.0)

    result = HallucinationDetector().validate(
        "List customer regions", generated, primary, alternative_execution=alternative
    )

    agreement = next(signal for signal in result.signals if signal.name == "multi_query_agreement")
    assert not agreement.passed
    assert "disagree" in agreement.explanation
