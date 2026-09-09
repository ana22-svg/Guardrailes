# Guardrails Text-to-SQL

Phase 1 through 5 implementation for a text-to-SQL interface:

- Introspects database schema with SQLAlchemy.
- Captures tables, columns, primary keys, foreign keys, and sample values.
- Filters schema context to tables relevant to the user's question.
- Detects curated ambiguous business terms and returns clarification options.
- Builds a dynamic prompt with focused schema context and schema-specific few-shot examples.
- Parses structured SQL-generation output.
- Blocks unsafe SQL before execution.
- Enforces row limits on read-only queries.
- Executes approved SQL in a transaction that rolls back automatically.
- Captures execution metadata and an `EXPLAIN` plan when available.
- Runs golden-query evaluations with execution accuracy, SQL exact match, hallucination detection, and guardrail metrics.

## Quick Start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
python examples\phase1_demo.py
python examples\phase2_demo.py
uvicorn examples.demo_app:app --reload
```

Open `http://localhost:8000` for the browser workbench. The demo generator is deterministic so the interface works without API keys; replace it with an implementation of `SQLGenerator` when connecting an LLM.

## Phase 1 API

```python
from guardrails_text2sql import PromptEngine

engine = PromptEngine.from_connection_string("duckdb:///warehouse.duckdb")
response = engine.build("Show revenue by region last quarter")

if response.needs_clarification:
    print(response.clarification)
else:
    print(response.prompt)
```

The default relevance filter is deterministic and local. It can be replaced later with an embedding-backed implementation without changing the prompt engine contract.

## Phase 2 API

```python
from guardrails_text2sql import QueryExecutor, SQLGuardrailMiddleware

executor = QueryExecutor(engine, SQLGuardrailMiddleware())
result = executor.execute("SELECT id, name FROM customers")

print(result.sql)       # SELECT id, name FROM customers LIMIT 1000
print(result.rows)
```

Unsafe queries are blocked before execution:

```python
executor.execute("SELECT 1; DROP TABLE customers;")
```

The guardrail layer blocks:

- Multiple statements.
- Non-`SELECT` queries.
- DDL and DML keywords such as `DROP`, `ALTER`, `INSERT`, `UPDATE`, and `DELETE`.
- Subqueries deeper than the configured limit.
- Missing row caps by adding `LIMIT`.
- EXPLAIN plans whose estimated row scan exceeds `GuardrailConfig.max_estimated_rows`.

The scan estimate is enforced when the database dialect exposes row estimates in its EXPLAIN output. Plans without an extractable estimate remain executable and retain their captured plan for auditability.

## Phase 3 Validation

The query service can combine back-translation and an independent SQL approach:

```python
service = QueryService(
    prompt_engine,
    generator,
    executor,
    HallucinationDetector(translator=question_translator),
    alternative_generator=independent_generator,
)
```

The final validation includes the translator alignment and multi-query agreement signals when those dependencies are supplied.

## Phase 4 API

Create an app by injecting the prompt engine, SQL generator, executor, and hallucination detector:

```python
from guardrails_text2sql.api import create_app
from guardrails_text2sql import QueryService

service = QueryService(prompt_engine, generator, executor, detector)
app = create_app(service)
```

The app exposes `POST /v1/query`, `GET /v1/schema`, `GET /v1/history`, `POST /v1/feedback`, and `GET /v1/feedback`. The included frontend shows generated SQL, returned rows, confidence signals, retries, history, and human correctness feedback.

## Phase 5 Evaluation

Use `GoldenCase` records with verified SQL and frozen expected rows:

```python
from guardrails_text2sql import EvaluationSuite, GoldenCase

cases = [
    GoldenCase(
        question="List customer names",
        expected_sql="SELECT name FROM customers LIMIT 1000",
        expected_rows=({"name": "Acme"},),
        category="lookup",
    ),
]
report = EvaluationSuite(lambda case: service.query(case.question)).run(cases)
print(report.as_dict())
```

Execution match is the primary accuracy metric; SQL exact match is retained as a diagnostic because equivalent SQL can have different formatting or structure. Keep the database snapshot fixed while evaluating expected rows.

The repository includes `data/golden_cases.json`, a 50+ case starter dataset covering lookups, joins, aggregations, date filters, ambiguity, hallucination, and guardrail cases:

```python
from guardrails_text2sql import load_golden_cases

cases = load_golden_cases("data/golden_cases.json")
```

## Docker

```powershell
docker compose up --build
```

Then open `http://localhost:8000`. The demo database is persisted in the `demo-data` volume.
