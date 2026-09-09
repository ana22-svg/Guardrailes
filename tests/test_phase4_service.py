from __future__ import annotations

from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine

from guardrails_text2sql import (
    ColumnInfo,
    GeneratedSQL,
    HallucinationDetector,
    PromptEngine,
    QueryExecutor,
    QueryService,
    SchemaInfo,
    SQLGuardrailMiddleware,
    TableInfo,
)


class SequenceGenerator:
    def __init__(self, outputs: list[GeneratedSQL]) -> None:
        self.outputs = outputs

    def generate(self, prompt: str) -> GeneratedSQL:
        return self.outputs.pop(0)


def test_query_service_retries_and_keeps_latest_result_in_history():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    customers = Table(
        "customers",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String, nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(customers.insert(), [{"id": 1, "name": "Acme"}])

    service = QueryService(
        PromptEngine(
            SchemaInfo(
                (
                    TableInfo(
                        "customers",
                        (ColumnInfo("id", "INTEGER", False, primary_key=True), ColumnInfo("name", "VARCHAR", False)),
                    ),
                )
            )
        ),
        SequenceGenerator(
            [
                GeneratedSQL("SELECT name FROM customers", "Lists names.", 0.2),
                GeneratedSQL("SELECT name FROM customers", "Lists names.", 0.95),
            ]
        ),
        QueryExecutor(engine, SQLGuardrailMiddleware()),
        HallucinationDetector(),
    )

    result = service.query("List customer names")

    assert result.rows == ({"name": "Acme"},)
    assert result.retry_count == 1
    assert result.validation is not None and result.validation.passed
    assert len(service.history()) == 1


def test_query_service_integrates_back_translation_and_independent_query_agreement():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    customers = Table(
        "customers",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String, nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(customers.insert(), [{"id": 1, "name": "Acme"}])

    service = QueryService(
        PromptEngine(
            SchemaInfo(
                (TableInfo("customers", (ColumnInfo("id", "INTEGER", False, primary_key=True), ColumnInfo("name", "VARCHAR", False))),)
            )
        ),
        SequenceGenerator([GeneratedSQL("SELECT name FROM customers", "Lists names.", 0.95)]),
        QueryExecutor(engine),
        HallucinationDetector(translator=lambda _: "List customer names"),
        alternative_generator=SequenceGenerator(
            [GeneratedSQL("SELECT name FROM customers ORDER BY name", "Lists names.", 0.95)]
        ),
    )

    result = service.query("List customer names")

    assert result.validation is not None and result.validation.passed
    assert {signal.name for signal in result.validation.signals} == {
        "generation_confidence",
        "back_translation_alignment",
        "result_sanity",
        "multi_query_agreement",
    }