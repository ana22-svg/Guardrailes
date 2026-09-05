from __future__ import annotations

from datetime import date

from sqlalchemy import Column, Date, ForeignKey, Integer, MetaData, Numeric, String, Table, create_engine

from guardrails_text2sql import AmbiguityOption, FewShotExample, LexicalSchemaRelevanceFilter, PromptEngine


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
    Table(
        "support_tickets",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("customer_id", Integer, ForeignKey("customers.id"), nullable=False),
        Column("priority", String, nullable=False),
        Column("status", String, nullable=False),
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
        connection.execute(
            metadata.tables["support_tickets"].insert(),
            [
                {"id": 100, "customer_id": 1, "priority": "high", "status": "open"},
                {"id": 101, "customer_id": 2, "priority": "low", "status": "closed"},
            ],
        )
    return engine


def test_introspection_builds_focused_prompt_with_samples_and_foreign_keys():
    prompt_engine = PromptEngine.from_engine(
        build_engine(),
        examples=(
            FewShotExample(
                question="What is net revenue by customer?",
                sql=(
                    "SELECT customers.name, SUM(orders.net_revenue) AS net_revenue "
                    "FROM orders JOIN customers ON customers.id = orders.customer_id "
                    "GROUP BY customers.name"
                ),
                tables=("orders", "customers"),
            ),
        ),
        table_descriptions={"orders": "Customer purchases and revenue facts."},
        column_descriptions={"orders.net_revenue": "Revenue after refunds and discounts."},
        relevance_filter=LexicalSchemaRelevanceFilter(min_score=0.05, max_tables=3),
    )

    result = prompt_engine.build("Show net revenue by customer region")

    assert not result.needs_clarification
    assert result.prompt is not None
    assert "Table: orders" in result.prompt
    assert "Table: customers" in result.prompt
    assert "orders.customer_id -> customers.id" in result.prompt
    assert "sample values: North, South" in result.prompt
    assert "What is net revenue by customer?" in result.prompt
    assert "support_tickets" not in result.selected_tables


def test_ambiguity_returns_structured_clarification_instead_of_prompt():
    prompt_engine = PromptEngine.from_engine(
        build_engine(),
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
    )

    result = prompt_engine.build("Show revenue by region")

    assert result.needs_clarification
    assert result.prompt is None
    assert result.clarification is not None
    assert result.clarification.term == "revenue"
    assert [option.label for option in result.clarification.options] == ["gross revenue", "net revenue"]


def test_explicit_ambiguity_option_does_not_request_clarification():
    prompt_engine = PromptEngine.from_engine(
        build_engine(),
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
    )

    result = prompt_engine.build("Show net revenue by region")

    assert not result.needs_clarification
    assert result.prompt is not None


def test_relevance_filter_falls_back_to_best_matching_table():
    prompt_engine = PromptEngine.from_engine(build_engine(), relevance_filter=LexicalSchemaRelevanceFilter(min_score=0.95))

    result = prompt_engine.build("Which tickets are open?")

    assert result.selected_tables
    assert result.selected_tables[0] == "support_tickets"
