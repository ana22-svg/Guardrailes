# Guardrails Text-to-SQL

Phase 1 and 2 implementation for a text-to-SQL interface:

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

## Quick Start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
python examples\phase1_demo.py
python examples\phase2_demo.py
```

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
