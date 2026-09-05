from __future__ import annotations

import math
import re
from collections import Counter

from guardrails_text2sql.models import SchemaInfo, TableInfo

TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_]*")


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text.replace("_", " "))]


class LexicalSchemaRelevanceFilter:
    def __init__(
        self,
        *,
        min_score: float = 0.08,
        min_relative_score: float = 0.25,
        max_tables: int = 6,
        include_fk_neighbors: bool = True,
    ) -> None:
        self.min_score = min_score
        self.min_relative_score = min_relative_score
        self.max_tables = max_tables
        self.include_fk_neighbors = include_fk_neighbors

    def filter(self, question: str, schema: SchemaInfo) -> tuple[SchemaInfo, dict[str, float]]:
        if not schema.tables:
            return schema, {}

        question_vector = Counter(tokenize(question))
        scores = {table.name: self._score(question_vector, Counter(tokenize(table.searchable_text()))) for table in schema.tables}
        ranked = sorted(schema.tables, key=lambda table: (scores[table.name], self._name_overlap(question, table)), reverse=True)

        top_score = scores[ranked[0].name]
        selected_names = [
            table.name
            for table in ranked
            if scores[table.name] >= self.min_score and scores[table.name] >= top_score * self.min_relative_score
        ]
        if not selected_names:
            selected_names.append(ranked[0].name)

        selected_names = selected_names[: self.max_tables]

        if self.include_fk_neighbors:
            selected_set = set(selected_names)
            for neighbor in self._foreign_key_neighbors(schema, selected_set):
                if neighbor not in selected_set and len(selected_names) < self.max_tables:
                    selected_names.append(neighbor)
                    selected_set.add(neighbor)

        return SchemaInfo(tuple(table for table in ranked if table.name in set(selected_names))), scores

    def _score(self, question_vector: Counter[str], table_vector: Counter[str]) -> float:
        if not question_vector or not table_vector:
            return 0.0
        shared = set(question_vector) & set(table_vector)
        numerator = sum(question_vector[token] * table_vector[token] for token in shared)
        question_norm = math.sqrt(sum(value * value for value in question_vector.values()))
        table_norm = math.sqrt(sum(value * value for value in table_vector.values()))
        return numerator / (question_norm * table_norm)

    def _name_overlap(self, question: str, table: TableInfo) -> int:
        question_tokens = set(tokenize(question))
        table_tokens = set(tokenize(table.name))
        return len(question_tokens & table_tokens)

    def _foreign_key_neighbors(self, schema: SchemaInfo, selected_names: set[str]) -> set[str]:
        neighbors: set[str] = set()
        for table in schema.tables:
            if table.name in selected_names:
                neighbors.update(fk.referred_table for fk in table.foreign_keys)
        return neighbors & schema.table_names()
