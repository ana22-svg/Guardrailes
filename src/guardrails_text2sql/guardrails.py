from __future__ import annotations

import logging

import sqlparse
from sqlparse.sql import Statement, Token
from sqlparse.tokens import Comment, DDL, DML, Keyword, Literal, Name, Punctuation, Whitespace

from guardrails_text2sql.models import GuardrailConfig, GuardrailResult, GuardrailViolation

LOGGER = logging.getLogger(__name__)

FORBIDDEN_KEYWORDS = {
    "ALTER",
    "CALL",
    "CREATE",
    "DELETE",
    "DROP",
    "EXEC",
    "EXECUTE",
    "GRANT",
    "INSERT",
    "MERGE",
    "REINDEX",
    "REPLACE",
    "REVOKE",
    "TRUNCATE",
    "UPDATE",
    "VACUUM",
}


class SQLGuardrailMiddleware:
    def __init__(self, config: GuardrailConfig | None = None) -> None:
        self.config = config or GuardrailConfig()

    def validate(self, sql: str) -> GuardrailResult:
        statements = [statement for statement in sqlparse.parse(sql) if self._has_code(statement)]
        violations: list[GuardrailViolation] = []

        if not statements:
            violations.append(GuardrailViolation("empty_query", "SQL query is empty."))
            return self._blocked(sql, violations)

        if self.config.block_multiple_statements and len(statements) != 1:
            violations.append(GuardrailViolation("multiple_statements", "Only one SQL statement may be executed."))
            return self._blocked(sql, violations)

        statement = statements[0]
        query_type = self._query_type(statement)
        if query_type not in {"SELECT", "WITH"}:
            violations.append(GuardrailViolation("non_select_query", "Only read-only SELECT queries are allowed."))

        forbidden = self._forbidden_keywords(statement)
        if forbidden:
            violations.append(
                GuardrailViolation(
                    "forbidden_keyword",
                    f"Query contains blocked keyword(s): {', '.join(sorted(forbidden))}.",
                )
            )

        depth = self._subquery_depth(statement)
        if depth > self.config.max_subquery_depth:
            violations.append(
                GuardrailViolation(
                    "subquery_depth",
                    f"Subquery depth {depth} exceeds limit {self.config.max_subquery_depth}.",
                )
            )

        if violations:
            return self._blocked(sql, violations)

        safe_sql = self._with_row_limit(sqlparse.format(str(statement).strip(), strip_comments=True).strip())
        warnings = ()
        if safe_sql != sql.strip():
            warnings = (f"Applied LIMIT {self.config.row_limit}.",)
        return GuardrailResult(allowed=True, sql=safe_sql, warnings=warnings)

    def _blocked(self, sql: str, violations: list[GuardrailViolation]) -> GuardrailResult:
        LOGGER.warning("Blocked SQL query", extra={"sql": sql, "violations": [violation.code for violation in violations]})
        return GuardrailResult(allowed=False, sql=None, violations=tuple(violations))

    def _has_code(self, statement: Statement) -> bool:
        return any(token.ttype not in Whitespace and not token.ttype in Comment for token in statement.flatten())

    def _query_type(self, statement: Statement) -> str:
        for token in statement.tokens:
            if token.ttype in Whitespace or token.ttype in Comment:
                continue
            value = token.normalized.upper()
            if value == "WITH":
                return "WITH"
            if token.ttype in DML:
                return value
            return value
        return "UNKNOWN"

    def _forbidden_keywords(self, statement: Statement) -> set[str]:
        forbidden: set[str] = set()
        for token in statement.flatten():
            if self._is_ignorable(token):
                continue
            value = token.normalized.upper()
            if value in FORBIDDEN_KEYWORDS and (token.ttype in Keyword or token.ttype in DDL or token.ttype in DML):
                forbidden.add(value)
        return forbidden

    def _subquery_depth(self, statement: Statement) -> int:
        paren_depth = 0
        select_depths: list[int] = []
        for token in statement.flatten():
            if self._is_ignorable(token):
                continue
            if token.ttype is Punctuation and token.value == "(":
                paren_depth += 1
                continue
            if token.ttype is Punctuation and token.value == ")":
                paren_depth = max(0, paren_depth - 1)
                continue
            if token.ttype in DML and token.normalized.upper() == "SELECT":
                select_depths.append(paren_depth)
        if not select_depths:
            return 0
        outer_depth = min(select_depths)
        return max(depth - outer_depth for depth in select_depths)

    def _with_row_limit(self, sql: str) -> str:
        cleaned = sql.rstrip().rstrip(";").strip()
        if not self.config.enforce_limit or self._has_limit(cleaned):
            return cleaned
        return f"{cleaned} LIMIT {self.config.row_limit}"

    def _has_limit(self, sql: str) -> bool:
        statements = sqlparse.parse(sql)
        if not statements:
            return False
        return any(token.ttype in Keyword and token.normalized.upper() == "LIMIT" for token in statements[0].flatten())

    def _is_ignorable(self, token: Token) -> bool:
        return token.ttype in Whitespace or token.ttype in Comment or token.ttype in Literal.String.Single or token.ttype in Name
