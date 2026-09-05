from __future__ import annotations

from guardrails_text2sql.models import FewShotExample, SchemaInfo, TableInfo


class PromptConstructor:
    def __init__(self, examples: tuple[FewShotExample, ...] = ()) -> None:
        self.examples = examples

    def build(self, question: str, schema: SchemaInfo) -> str:
        examples = self._select_examples(schema, limit=5)
        parts = [
            "You are a careful text-to-SQL assistant.",
            "Write one read-only SQL query that answers the user's question using only the provided schema.",
            "If the schema is insufficient or the question is ambiguous, return a clarification instead of guessing.",
            "",
            "Relevant schema:",
            self._render_schema(schema),
        ]
        if examples:
            parts.extend(["", "Schema-specific examples:", self._render_examples(examples)])
        parts.extend(["", f"User question: {question}", "", "Return SQL only for unambiguous answerable questions."])
        return "\n".join(parts)

    def _select_examples(self, schema: SchemaInfo, *, limit: int) -> tuple[FewShotExample, ...]:
        table_names = schema.table_names()
        matching = [example for example in self.examples if not example.tables or table_names.intersection(example.tables)]
        return tuple(matching[:limit])

    def _render_schema(self, schema: SchemaInfo) -> str:
        return "\n\n".join(self._render_table(table) for table in schema.tables)

    def _render_table(self, table: TableInfo) -> str:
        lines = [f"Table: {table.name}"]
        if table.description:
            lines.append(f"Description: {table.description}")
        primary_keys = table.primary_key_columns
        if primary_keys:
            lines.append(f"Primary key: {', '.join(primary_keys)}")
        lines.append("Columns:")
        for column in table.columns:
            flags = []
            if column.primary_key:
                flags.append("primary key")
            if not column.nullable:
                flags.append("not null")
            flag_text = f" ({', '.join(flags)})" if flags else ""
            sample_text = f" sample values: {', '.join(column.sample_values)}" if column.sample_values else ""
            description_text = f" - {column.description}" if column.description else ""
            lines.append(f"- {column.name}: {column.data_type}{flag_text}{description_text}{sample_text}")
        if table.foreign_keys:
            lines.append("Foreign keys:")
            lines.extend(f"- {foreign_key.render(table.name)}" for foreign_key in table.foreign_keys)
        return "\n".join(lines)

    def _render_examples(self, examples: tuple[FewShotExample, ...]) -> str:
        rendered = []
        for example in examples:
            rendered.append(f"Question: {example.question}\nSQL: {example.sql}")
        return "\n\n".join(rendered)
