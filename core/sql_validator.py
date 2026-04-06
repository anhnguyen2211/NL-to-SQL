import sqlglot
from sqlglot import expressions as exp


BLOCKED_TYPES = (
    exp.Insert, exp.Update, exp.Delete,
    exp.Drop, exp.Create, exp.Alter,
    exp.Merge, exp.Command,
)


def validate_and_enforce(sql: str, max_rows: int = 100) -> str:
    # Rule 1: Not empty
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        raise ValueError("Empty SQL query.")

    # Rule 2: Parseable
    try:
        statements = sqlglot.parse(sql)
    except sqlglot.errors.ParseError as e:
        raise ValueError(f"SQL parse error: {e}")

    # Rule 3: Single statement
    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise ValueError("Only a single SQL statement is allowed.")

    stmt = statements[0]

    # Rule 4: Only SELECT
    if not isinstance(stmt, exp.Select):
        raise ValueError("Only SELECT statements are allowed.")

    # Rule 5: Block DML/DDL in subqueries
    for node in stmt.walk():
        if isinstance(node, BLOCKED_TYPES):
            raise ValueError("Only SELECT statements are allowed.")

    # Rule 6: Enforce LIMIT
    limit_node = stmt.args.get("limit")
    if limit_node is None:
        stmt = stmt.limit(max_rows)
    else:
        current_limit = limit_node.expression
        if isinstance(current_limit, exp.Literal) and current_limit.is_int:
            if int(current_limit.this) > max_rows:
                stmt = stmt.limit(max_rows)

    return stmt.sql()
