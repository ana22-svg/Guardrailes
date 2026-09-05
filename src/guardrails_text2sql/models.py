from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    data_type: str
    nullable: bool
    primary_key: bool = False
    sample_values: tuple[str, ...] = ()
    description: str | None = None

    def searchable_text(self) -> str:
        parts = [self.name, self.data_type]
        if self.description:
            parts.append(self.description)
        parts.extend(self.sample_values)
        return " ".join(parts)


@dataclass(frozen=True)
class ForeignKeyInfo:
    constrained_columns: tuple[str, ...]
    referred_table: str
    referred_columns: tuple[str, ...]

    def render(self, table_name: str) -> str:
        left = ", ".join(f"{table_name}.{column}" for column in self.constrained_columns)
        right = ", ".join(f"{self.referred_table}.{column}" for column in self.referred_columns)
        return f"{left} -> {right}"


@dataclass(frozen=True)
class TableInfo:
    name: str
    columns: tuple[ColumnInfo, ...]
    foreign_keys: tuple[ForeignKeyInfo, ...] = ()
    description: str | None = None

    @property
    def primary_key_columns(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns if column.primary_key)

    def searchable_text(self) -> str:
        parts = [self.name]
        if self.description:
            parts.append(self.description)
        for column in self.columns:
            parts.append(column.searchable_text())
        for foreign_key in self.foreign_keys:
            parts.append(foreign_key.referred_table)
            parts.extend(foreign_key.referred_columns)
        return " ".join(parts)


@dataclass(frozen=True)
class SchemaInfo:
    tables: tuple[TableInfo, ...]

    def table_names(self) -> set[str]:
        return {table.name for table in self.tables}

    def find_table(self, table_name: str) -> TableInfo | None:
        return next((table for table in self.tables if table.name == table_name), None)

    def subset(self, table_names: set[str]) -> "SchemaInfo":
        return SchemaInfo(tuple(table for table in self.tables if table.name in table_names))


@dataclass(frozen=True)
class FewShotExample:
    question: str
    sql: str
    tables: tuple[str, ...] = ()


@dataclass(frozen=True)
class AmbiguityOption:
    label: str
    meaning: str
    example_sql: str


@dataclass(frozen=True)
class ClarificationRequest:
    term: str
    question: str
    options: tuple[AmbiguityOption, ...]


@dataclass(frozen=True)
class PromptBuildResult:
    question: str
    prompt: str | None
    selected_tables: tuple[str, ...] = ()
    table_scores: dict[str, float] = field(default_factory=dict)
    clarification: ClarificationRequest | None = None

    @property
    def needs_clarification(self) -> bool:
        return self.clarification is not None


@dataclass(frozen=True)
class GeneratedSQL:
    sql: str
    explanation: str
    confidence: float
    tables: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class GuardrailConfig:
    row_limit: int = 1000
    max_subquery_depth: int = 3
    enforce_limit: bool = True
    block_multiple_statements: bool = True
    explain_before_execution: bool = False


@dataclass(frozen=True)
class GuardrailViolation:
    code: str
    message: str


@dataclass(frozen=True)
class GuardrailResult:
    allowed: bool
    sql: str | None
    violations: tuple[GuardrailViolation, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueryExecutionResult:
    sql: str
    rows: tuple[dict[str, Any], ...]
    row_count: int
    execution_time_ms: float
    explain_plan: tuple[dict[str, Any], ...] = ()
