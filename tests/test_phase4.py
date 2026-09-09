from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from guardrails_text2sql import (
    AmbiguityOption,
    GeneratedSQL,
    HallucinationDetector,
    PromptEngine,
    QueryExecutor,
    QueryService,
    SchemaInfo,
    TableInfo,
    ColumnInfo,
    SQLGuardrailMiddleware,
)
from guardrails_text2sql.api import create_app


class SequenceGenerator:
    def __init__(self, outputs: list[GeneratedSQL]) -> None:
        self.outputs = outputs
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> GeneratedSQL:
        self.prompts.append(prompt)
        return self.outputs.pop(0)


def build_service(generator: SequenceGenerator) -> QueryService:
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

    schema = SchemaInfo(
        (
            TableInfo(
                name="customers",
                columns=(ColumnInfo("id", "INTEGER", False, primary_key=True), ColumnInfo("name", "VARCHAR", False)),
            ),
        )
    )
    return QueryService(
        PromptEngine(schema),
        generator,
        QueryExecutor(engine, SQLGuardrailMiddleware()),
        HallucinationDetector(),
        max_attempts=3,
    )


def test_query_endpoint_retries_low_confidence_and_records_history():
    generator = SequenceGenerator(
        [
            GeneratedSQL("SELECT name FROM customers", "Lists names.", 0.2),
            GeneratedSQL("SELECT name FROM customers", "Lists names.", 0.95),
        ]
    )
    client = TestClient(create_app(build_service(generator)))

    response = client.post("/v1/query", json={"question": "List customer names"})

    assert response.status_code == 200
    body = response.json()
    assert body["rows"] == [{"name": "Acme"}]
    assert body["retry_count"] == 1
    assert body["confidence"] == 0.975
    assert len(generator.prompts) == 2
    assert "Previous attempt feedback:" in generator.prompts[1]

    history = client.get("/v1/history")
    assert history.status_code == 200
    assert len(history.json()["items"]) == 1


def test_schema_endpoint_returns_schema_and_ambiguity_is_not_generated():
    generator = SequenceGenerator([])
    service = build_service(generator)
    service.prompt_engine.ambiguity_detector = service.prompt_engine.ambiguity_detector.__class__(
        {
            "customer": (
                AmbiguityOption("customer", "A customer account.", "SELECT * FROM customers"),
            )
        }
    )
    client = TestClient(create_app(service))

    schema = client.get("/v1/schema")
    assert schema.status_code == 200
    assert schema.json()["tables"][0]["name"] == "customers"
    assert schema.json()["tables"][0]["columns"][0]["primary_key"] is True

    response = client.post("/v1/query", json={"question": "Show each customer"})
    assert response.status_code == 200
    assert response.json()["clarification"]["term"] == "customer"
    assert generator.prompts == []