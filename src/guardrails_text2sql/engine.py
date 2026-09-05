from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from guardrails_text2sql.ambiguity import AmbiguityDetector
from guardrails_text2sql.models import AmbiguityOption, FewShotExample, PromptBuildResult, SchemaInfo
from guardrails_text2sql.prompts import PromptConstructor
from guardrails_text2sql.relevance import LexicalSchemaRelevanceFilter
from guardrails_text2sql.schema import SchemaIntrospector


class PromptEngine:
    def __init__(
        self,
        schema: SchemaInfo,
        *,
        relevance_filter: LexicalSchemaRelevanceFilter | None = None,
        ambiguity_detector: AmbiguityDetector | None = None,
        prompt_constructor: PromptConstructor | None = None,
    ) -> None:
        self.schema = schema
        self.relevance_filter = relevance_filter or LexicalSchemaRelevanceFilter()
        self.ambiguity_detector = ambiguity_detector or AmbiguityDetector()
        self.prompt_constructor = prompt_constructor or PromptConstructor()

    @classmethod
    def from_engine(
        cls,
        engine: Engine,
        *,
        examples: tuple[FewShotExample, ...] = (),
        ambiguous_terms: Mapping[str, tuple[AmbiguityOption, ...]] | None = None,
        table_descriptions: Mapping[str, str] | None = None,
        column_descriptions: Mapping[str, str] | None = None,
        relevance_filter: LexicalSchemaRelevanceFilter | None = None,
    ) -> "PromptEngine":
        schema = SchemaIntrospector(
            engine,
            table_descriptions=table_descriptions,
            column_descriptions=column_descriptions,
        ).introspect()
        return cls(
            schema,
            relevance_filter=relevance_filter,
            ambiguity_detector=AmbiguityDetector(ambiguous_terms),
            prompt_constructor=PromptConstructor(examples),
        )

    @classmethod
    def from_connection_string(cls, connection_string: str, **kwargs: object) -> "PromptEngine":
        return cls.from_engine(create_engine(connection_string), **kwargs)

    def build(self, question: str) -> PromptBuildResult:
        clarification = self.ambiguity_detector.detect(question)
        if clarification:
            return PromptBuildResult(question=question, prompt=None, clarification=clarification)

        relevant_schema, scores = self.relevance_filter.filter(question, self.schema)
        prompt = self.prompt_constructor.build(question, relevant_schema)
        return PromptBuildResult(
            question=question,
            prompt=prompt,
            selected_tables=tuple(table.name for table in relevant_schema.tables),
            table_scores=scores,
        )
