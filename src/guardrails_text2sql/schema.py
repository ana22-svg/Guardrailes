from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, inspect, select
from sqlalchemy.engine import Engine

from guardrails_text2sql.models import ColumnInfo, ForeignKeyInfo, SchemaInfo, TableInfo


class SchemaIntrospector:
    def __init__(
        self,
        engine: Engine,
        *,
        sample_size: int = 5,
        sample_max_distinct: int = 20,
        table_descriptions: Mapping[str, str] | None = None,
        column_descriptions: Mapping[str, str] | None = None,
    ) -> None:
        self.engine = engine
        self.sample_size = sample_size
        self.sample_max_distinct = sample_max_distinct
        self.table_descriptions = dict(table_descriptions or {})
        self.column_descriptions = dict(column_descriptions or {})

    @classmethod
    def from_connection_string(cls, connection_string: str, **kwargs: Any) -> "SchemaIntrospector":
        return cls(create_engine(connection_string), **kwargs)

    def introspect(self) -> SchemaInfo:
        inspector = inspect(self.engine)
        metadata = MetaData()
        tables: list[TableInfo] = []

        for table_name in sorted(inspector.get_table_names()):
            table = Table(table_name, metadata, autoload_with=self.engine)
            pk_columns = set(inspector.get_pk_constraint(table_name).get("constrained_columns") or [])
            columns = tuple(
                ColumnInfo(
                    name=column["name"],
                    data_type=str(column["type"]),
                    nullable=bool(column["nullable"]),
                    primary_key=column["name"] in pk_columns,
                    sample_values=self._sample_values(table, column["name"]),
                    description=self.column_descriptions.get(f"{table_name}.{column['name']}"),
                )
                for column in inspector.get_columns(table_name)
            )
            foreign_keys = tuple(
                ForeignKeyInfo(
                    constrained_columns=tuple(fk.get("constrained_columns") or ()),
                    referred_table=str(fk.get("referred_table") or ""),
                    referred_columns=tuple(fk.get("referred_columns") or ()),
                )
                for fk in inspector.get_foreign_keys(table_name)
                if fk.get("referred_table")
            )
            tables.append(
                TableInfo(
                    name=table_name,
                    columns=columns,
                    foreign_keys=foreign_keys,
                    description=self.table_descriptions.get(table_name),
                )
            )

        return SchemaInfo(tuple(tables))

    def _sample_values(self, table: Table, column_name: str) -> tuple[str, ...]:
        column = table.c[column_name]
        try:
            statement = select(column).where(column.is_not(None)).distinct().limit(self.sample_max_distinct)
            with self.engine.connect() as connection:
                values = [row[0] for row in connection.execute(statement)]
        except Exception:
            return ()

        if 0 < len(values) <= self.sample_max_distinct:
            return tuple(str(value) for value in values[: self.sample_size])
        return ()
