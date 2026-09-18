"""PostgreSQL AST validation and bounded JSON output."""

import json

from pglast import ast, parse_sql
from pglast.stream import RawStream
from pglast.visitors import Visitor

MAX_RESULT_BYTES = 2 * 1024 * 1024
# Deliberately conservative: arbitrary functions may mutate state or invoke external code.
SAFE_FUNCTIONS = frozenset("""
abs avg count sum min max round ceil ceiling floor trunc mod power sqrt sign
lower upper length char_length octet_length substring substr left right trim btrim ltrim rtrim
replace split_part concat concat_ws string_agg array_agg array_length cardinality unnest
coalesce nullif greatest least date_trunc date_part extract to_char to_date to_timestamp
now age timezone current_date generate_series row_number rank dense_rank lag lead
first_value last_value ntile percent_rank cume_dist bool_and bool_or every
json_agg jsonb_agg json_build_object jsonb_build_object json_object_agg jsonb_object_agg
json_array_length jsonb_array_length json_extract_path_text jsonb_extract_path_text
pg_size_pretty pg_relation_size pg_total_relation_size pg_table_size pg_indexes_size
pg_database_size pg_get_viewdef pg_get_indexdef pg_get_constraintdef pg_typeof format_type
current_setting version
""".split())


def validate_sql(sql: str) -> str:
    if not sql.strip() or len(sql.encode()) > 65536:
        raise ValueError("SQL must contain 1–65536 bytes")
    try:
        statements = parse_sql(sql)
    except Exception:
        raise ValueError("Invalid PostgreSQL SQL") from None
    if len(statements) != 1:
        raise ValueError("Exactly one statement is required")
    root = statements[0].stmt
    if type(root).__name__ not in {"SelectStmt", "VariableShowStmt", "ExplainStmt"}:
        raise ValueError("Only SELECT, SHOW and EXPLAIN SELECT are allowed")

    def walk(value):
        if isinstance(value, dict):
            kind = value.get("@", "")
            if kind.endswith("Stmt") and kind not in {"SelectStmt", "VariableShowStmt", "ExplainStmt"}:
                raise ValueError("Nested write/utility statements are forbidden")
            if kind in {"IntoClause", "LockingClause"}:
                raise ValueError("SELECT INTO and row locks are forbidden")
            if kind == "DefElem" and value.get("defname") == "analyze":
                raise ValueError("EXPLAIN ANALYZE is forbidden")
            if kind == "FuncCall":
                name = [part["sval"] for part in value["funcname"]]
                if len(name) > 2 or (len(name) == 2 and name[0] != "pg_catalog") or name[-1] not in SAFE_FUNCTIONS:
                    raise ValueError("Function is outside the diagnostic read-only allowlist")
            for child in value.values():
                walk(child)
        elif isinstance(value, (tuple, list)):
            for child in value:
                walk(child)

    walk(root())
    return type(root).__name__


def encoded(value) -> bytes:
    return json.dumps(value, ensure_ascii=True, default=str, separators=(",", ":")).encode()


class _CatalogFunctions(Visitor):
    def visit_FuncCall(self, ancestors, node):
        if len(node.funcname) == 1:
            node.funcname = (ast.String(sval="pg_catalog"), *node.funcname)


def qualify_functions(sql: str) -> str:
    """After validation, prevent overload resolution into public user functions."""
    tree = parse_sql(sql)
    _CatalogFunctions()(tree)
    return RawStream()(tree)
