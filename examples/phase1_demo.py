from __future__ import annotations

from datetime import date

from sqlalchemy import Column, Date, ForeignKey, Integer, MetaData, Numeric, String, Table, create_engine

from guardrails_text2sql import AmbiguityOption, FewShotExample, LexicalSchemaRelevanceFilter, PromptEngine


def seed_demo_database():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    Table(
        "customers",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String, nullable=False),
        Column("region", String, nullable=False),
    )
    Table(
        "orders",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("customer_id", Integer, ForeignKey("customers.id"), nullable=False),
        Column("order_date", Date, nullable=False),
        Column("status", String, nullable=False),
        Column("gross_revenue", Numeric, nullable=False),
        Column("net_revenue", Numeric, nullable=False),
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
        connection.execute(
            metadata.tables["orders"].insert(),
            [
                {
                    "id": 10,
                    "customer_id": 1,
                    "order_date": date(2026, 1, 1),
                    "status": "paid",
                    "gross_revenue": 120,
                    "net_revenue": 100,
                },
                {
                    "id": 11,
                    "customer_id": 2,
                    "order_date": date(2026, 1, 2),
                    "status": "refunded",
                    "gross_revenue": 80,
                    "net_revenue": 0,
                },
            ],
        )
    return engine


engine = PromptEngine.from_engine(
    seed_demo_database(),
    examples=(
        FewShotExample(
            question="Show net revenue by customer region.",
            sql=(
                "SELECT customers.region, SUM(orders.net_revenue) AS net_revenue "
                "FROM orders JOIN customers ON customers.id = orders.customer_id "
                "GROUP BY customers.region"
            ),
            tables=("orders", "customers"),
        ),
    ),
    ambiguous_terms={
        "revenue": (
            AmbiguityOption(
                label="gross revenue",
                meaning="Total order value before refunds and discounts.",
                example_sql="SELECT SUM(gross_revenue) FROM orders",
            ),
            AmbiguityOption(
                label="net revenue",
                meaning="Revenue after refunds and discounts.",
                example_sql="SELECT SUM(net_revenue) FROM orders",
            ),
        )
    },
    table_descriptions={"orders": "Customer purchases and revenue facts."},
    column_descriptions={"orders.net_revenue": "Revenue after refunds and discounts."},
    relevance_filter=LexicalSchemaRelevanceFilter(min_score=0.05),
)

for question in ("Show net revenue by customer region", "Show revenue by region"):
    result = engine.build(question)
    print(f"\nQUESTION: {question}")
    if result.needs_clarification:
        print(result.clarification)
    else:
        print(result.prompt)
