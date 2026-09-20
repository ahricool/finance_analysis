"""Lightweight checks for obvious SQL writes and a few session/external side effects."""

from pglast import parse_sql

from .errors import ReadValidationError

MAX_RESULT_BYTES = 2 * 1024 * 1024
# Only obvious session/external side effects; ordinary and schema-qualified
# functions are allowed. Database permissions and read-only transactions govern SQL.
DENIED_FUNCTIONS = frozenset(
    {
        "pg_advisory_lock",
        "pg_advisory_xact_lock",
        "set_config",
        "pg_notify",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "lo_import",
        "lo_export",
    }
)


def validate_sql(sql: str) -> str:
    if not sql.strip() or len(sql.encode()) > 65536:
        raise ReadValidationError("SQL must contain 1–65536 bytes")
    try:
        statements = parse_sql(sql)
    except Exception:
        raise ReadValidationError("Invalid PostgreSQL SQL") from None
    if len(statements) != 1:
        raise ReadValidationError("Exactly one statement is required")
    root = statements[0].stmt
    if type(root).__name__ not in {"SelectStmt", "VariableShowStmt", "ExplainStmt"}:
        raise ReadValidationError("Only SELECT, SHOW and EXPLAIN SELECT are allowed")

    def walk(value):
        if isinstance(value, dict):
            kind = value.get("@", "")
            if kind.endswith("Stmt") and kind not in {"SelectStmt", "VariableShowStmt", "ExplainStmt"}:
                raise ReadValidationError("Nested write/utility statements are forbidden")
            if kind in {"IntoClause", "LockingClause"}:
                raise ReadValidationError("SELECT INTO and row locks are forbidden")
            if kind == "DefElem" and value.get("defname") == "analyze":
                raise ReadValidationError("EXPLAIN ANALYZE is forbidden")
            if kind == "FuncCall":
                name = value["funcname"][-1]["sval"]
                if name in DENIED_FUNCTIONS:
                    raise ReadValidationError(f"Function {name} has side effects and is not allowed")
            for child in value.values():
                walk(child)
        elif isinstance(value, (tuple, list)):
            for child in value:
                walk(child)

    walk(root())
    return type(root).__name__
