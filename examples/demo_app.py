from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy import Column, Date, Integer, MetaData, Numeric, String, Table, create_engine, select

from guardrails_text2sql import (
    GeneratedSQL,
    HallucinationDetector,
    PromptEngine,
    QueryExecutor,
    QueryService,
    SQLGuardrailMiddleware,
)
from guardrails_text2sql.api import create_app


class DemoGenerator:
    """Deterministic local generator for the portfolio demo and smoke tests."""

    def generate(self, prompt: str) -> GeneratedSQL:
        question = prompt.lower()
        if "net revenue" in question and "region" in question:
            sql = (
                "SELECT customers.region, SUM(orders.net_revenue) AS net_revenue "
                "FROM orders JOIN customers ON customers.id = orders.customer_id "
                "GROUP BY customers.region"
            )
            return GeneratedSQL(sql, "Sums net revenue after joining orders to customer regions.", 0.94)
        if "open" in question and "ticket" in question:
            sql = "SELECT id, customer_id, priority FROM support_tickets WHERE status = 'open'"
            return GeneratedSQL(sql, "Lists support tickets that are currently open.", 0.91)
        if "customer" in question and "region" in question:
            return GeneratedSQL("SELECT name, region FROM customers", "Lists each customer and their region.", 0.96)
        if "customer" in question and "name" in question:
            return GeneratedSQL("SELECT name FROM customers", "Lists customer names.", 0.95)
        return GeneratedSQL("SELECT id, name, region FROM customers", "Lists the customer directory.", 0.78)


def build_demo_database():
    database_path = Path("data") / "demo.db"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{database_path}")
    metadata = MetaData()
    customers = Table(
        "customers", metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String, nullable=False),
        Column("region", String, nullable=False),
    )
    orders = Table(
        "orders", metadata,
        Column("id", Integer, primary_key=True),
        Column("customer_id", Integer, nullable=False),
        Column("order_date", Date, nullable=False),
        Column("status", String, nullable=False),
        Column("gross_revenue", Numeric, nullable=False),
        Column("net_revenue", Numeric, nullable=False),
    )
    tickets = Table(
        "support_tickets", metadata,
        Column("id", Integer, primary_key=True),
        Column("customer_id", Integer, nullable=False),
        Column("priority", String, nullable=False),
        Column("status", String, nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        if connection.execute(select(customers.c.id).limit(1)).first() is None:
            connection.execute(customers.insert(), [
                {"id": 1, "name": "Acme", "region": "North"},
                {"id": 2, "name": "Globex", "region": "South"},
            ])
            connection.execute(orders.insert(), [
                {"id": 10, "customer_id": 1, "order_date": date(2026, 1, 1), "status": "paid", "gross_revenue": 120, "net_revenue": 100},
                {"id": 11, "customer_id": 2, "order_date": date(2026, 1, 2), "status": "refunded", "gross_revenue": 80, "net_revenue": 0},
            ])
            connection.execute(tickets.insert(), [
                {"id": 100, "customer_id": 1, "priority": "high", "status": "open"},
                {"id": 101, "customer_id": 2, "priority": "low", "status": "closed"},
            ])
    return engine


engine = build_demo_database()
prompt_engine = PromptEngine.from_engine(engine)
service = QueryService(
    prompt_engine,
    DemoGenerator(),
    QueryExecutor(engine, SQLGuardrailMiddleware()),
    HallucinationDetector(),
)
app = create_app(service)