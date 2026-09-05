from __future__ import annotations

from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine

from guardrails_text2sql import GuardrailConfig, QueryExecutor, SQLGuardrailMiddleware


engine = create_engine("sqlite:///:memory:")
metadata = MetaData()
customers = Table(
    "customers",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String, nullable=False),
    Column("region", String, nullable=False),
)
metadata.create_all(engine)

with engine.begin() as connection:
    connection.execute(
        customers.insert(),
        [
            {"id": 1, "name": "Acme", "region": "North"},
            {"id": 2, "name": "Globex", "region": "South"},
        ],
    )

executor = QueryExecutor(engine, SQLGuardrailMiddleware(GuardrailConfig(row_limit=1)))

safe = executor.execute("SELECT id, name FROM customers ORDER BY id")
print("SAFE SQL:", safe.sql)
print("ROWS:", safe.rows)
print("EXPLAIN:", safe.explain_plan)

blocked = executor.validate("SELECT id FROM customers; DROP TABLE customers;")
print("BLOCKED:", blocked.allowed)
print("VIOLATIONS:", blocked.violations)
