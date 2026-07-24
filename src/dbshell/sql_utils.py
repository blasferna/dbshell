"""Helpers for parsing simple SQL SELECT statements.

Used by the record-edit feature to detect the source table of the
currently displayed result set. Only the common case is supported:

    SELECT <columns> FROM <table> [WHERE ...] [GROUP BY ...]
        [ORDER BY ...] [LIMIT ...];

Any query containing joins, unions, subqueries or multiple FROM
targets returns ``None`` so the caller can refuse to edit.
"""

from __future__ import annotations

import re

# Forbid-list of keywords that make a SELECT unsafe to treat as a single
# table source. Matched as whole words anywhere in the (upper-cased) query.
_FORBIDDEN_KEYWORDS = (
    "JOIN",
    "UNION",
    "INTERSECT",
    "EXCEPT",
    "INTO",
    "FROM",
)

# Pattern that captures the table name after the first FROM keyword.
# Accepts an optional schema prefix (db.table) with or without quotes,
# and the table identifier itself may be quoted with backticks,
# double quotes, or square brackets (the three flavors in MySQL, SQLite,
# standard SQL and SQL Server respectively).
_ID_QUOTED = r"(`[^`]+`|\"[^\"]+\"|\[[^\]]+\]|[A-Za-z_]\w*)"
_FROM_PATTERN = re.compile(
    rf"""
    \bFROM\s+
    (?:
        (?P<schema>{_ID_QUOTED}\.)?
        (?P<table>{_ID_QUOTED})
    )
    (?:\s+(?:AS\s+)?{_ID_QUOTED})?   # alias
    """,
    re.IGNORECASE | re.VERBOSE,
)

_QUOTED_RE = re.compile(r"^(?:`([^`]+)`|\"([^\"]+)\"|\[([^\]]+)\])$")

# A second FROM (after a comma) is also forbidden.
_MULTI_FROM_PATTERN = re.compile(
    r"\bFROM\b.*\bFROM\b",
    re.IGNORECASE | re.DOTALL,
)

# Clauses that terminate the FROM section.
_FROM_TERMINATORS = (
    "WHERE",
    "GROUP BY",
    "ORDER BY",
    "HAVING",
    "LIMIT",
    "OFFSET",
    "UNION",
    "INTERSECT",
    "EXCEPT",
    "FETCH",
)


def extract_source_table(query: str) -> str | None:
    """Return the source table for a simple SELECT, or ``None`` if unsupported.

    The check is intentionally strict: anything that smells like a join,
    a union, a subquery, or a multi-table query yields ``None`` so the
    caller can refuse the edit action safely.
    """
    if query is None:
        return None

    stripped = query.strip().rstrip(";").strip()
    if not stripped:
        return None

    # Must start with SELECT (or WITH ... SELECT) — reject anything else.
    head_match = re.match(
        r"^(?:WITH\s+.+?\)\s+)?SELECT\b",
        stripped,
        re.IGNORECASE | re.DOTALL,
    )
    if not head_match:
        return None

    upper = stripped.upper()

    # Reject SELECT INTO (still matches the SELECT head above).
    if re.search(r"\bSELECT\s+.*\bINTO\b", upper):
        return None

    # Reject any forbidden clause keyword (JOIN, UNION, ...).
    for keyword in _FORBIDDEN_KEYWORDS:
        # FROM is matched separately below to capture the table name.
        if keyword == "FROM":
            continue
        if re.search(rf"\b{keyword}\b", upper):
            return None

    # Reject obvious subqueries: a SELECT keyword after the first FROM.
    first_from = _FROM_PATTERN.search(stripped)
    if first_from is None:
        return None
    after_from = stripped[first_from.end():]
    if re.search(r"\bSELECT\b", after_from, re.IGNORECASE):
        return None

    # Reject comma-separated additional table sources.
    if _MULTI_FROM_PATTERN.search(stripped):
        return None

    # Reject a comma-separated table list inside the FROM clause, e.g.
    # ``FROM users, orders`` or ``FROM users JOIN orders`` is already
    # rejected by the JOIN keyword check above, but plain comma lists
    # need this extra check.
    from_section = after_from
    upper_section = from_section.upper()
    cut_positions = [len(from_section)]
    for term in _FROM_TERMINATORS:
        idx = upper_section.find(term)
        if idx != -1:
            cut_positions.append(idx)
    from_section = from_section[: min(cut_positions)]
    if "," in from_section:
        return None

    return _strip_quotes(first_from.group("table"))


def _strip_quotes(name: str) -> str:
    """Remove a matching pair of surrounding quotes/brackets from an identifier."""
    match = _QUOTED_RE.match(name)
    if match is None:
        return name
    return next(group for group in match.groups() if group is not None)


_SELECT_HEAD_RE = re.compile(
    r"^(?:WITH\s+.+?\)\s+)?SELECT\b",
    re.IGNORECASE | re.DOTALL,
)
_LIMIT_KEYWORD_RE = re.compile(r"\b(?:LIMIT|OFFSET|FETCH)\b", re.IGNORECASE)


def _strip_strings_and_comments(sql: str) -> str:
    """Replace string/comment content with spaces so keyword scans stay safe."""
    out: list[str] = []
    i = 0
    length = len(sql)
    while i < length:
        char = sql[i]
        pair = sql[i : i + 2]

        if pair == "--":
            end = sql.find("\n", i)
            end = length if end == -1 else end
            out.append(" " * (end - i))
            i = end
            continue

        if pair == "/*":
            end = sql.find("*/", i + 2)
            end = length if end == -1 else end + 2
            out.append(" " * (end - i))
            i = end
            continue

        if char in "'\"`[":
            closing = "]" if char == "[" else char
            j = i + 1
            while j < length:
                if char in "'\"" and sql[j] == "\\":
                    j += 2
                    continue
                if sql[j] == closing:
                    break
                j += 1
            end = min(j + 1, length)
            out.append(" " * (end - i))
            i = end
            continue

        out.append(char)
        i += 1
    return "".join(out)


def apply_row_limit(sql: str, max_rows: int | None) -> str:
    """Append ``LIMIT N`` to a SELECT that does not already limit its rows.

    Non-SELECT statements, queries that already contain LIMIT/OFFSET/FETCH,
    and calls with ``max_rows`` unset are returned unchanged. The editor
    text is never modified — callers apply this only for execution.
    """
    if max_rows is None or max_rows <= 0:
        return sql

    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        return sql

    if not _SELECT_HEAD_RE.match(stripped):
        return sql

    searchable = _strip_strings_and_comments(stripped)
    if _LIMIT_KEYWORD_RE.search(searchable):
        return sql

    # Newline keeps a trailing `--` comment from swallowing the LIMIT.
    return f"{stripped}\nLIMIT {int(max_rows)}"


def split_statements(sql: str) -> list[str]:
    """Split a SQL script into individual executable statements.

    Statements are separated by semicolons. Semicolons inside string
    literals (``'...'``, ``"..."``), quoted identifiers (`` `...` ``,
    ``[...]``) and comments (``-- ...``, ``/* ... */``) are ignored.
    Backslash escapes are honored inside single- and double-quoted
    strings (MySQL style). Statements that contain only whitespace and
    comments are dropped.
    """
    statements: list[str] = []
    current: list[str] = []
    has_content = False

    def flush() -> None:
        nonlocal current, has_content
        statement = "".join(current).strip()
        if statement and has_content:
            statements.append(statement)
        current = []
        has_content = False

    i = 0
    length = len(sql)
    while i < length:
        char = sql[i]
        pair = sql[i : i + 2]

        if pair == "--":
            end = sql.find("\n", i)
            end = length if end == -1 else end + 1
            current.append(sql[i:end])
            i = end
            continue

        if pair == "/*":
            end = sql.find("*/", i + 2)
            end = length if end == -1 else end + 2
            current.append(sql[i:end])
            i = end
            continue

        if char in "'\"`[":
            closing = "]" if char == "[" else char
            j = i + 1
            while j < length:
                if char in "'\"" and sql[j] == "\\":
                    j += 2
                    continue
                if sql[j] == closing:
                    break
                j += 1
            end = min(j + 1, length)
            current.append(sql[i:end])
            has_content = True
            i = end
            continue

        if char == ";":
            flush()
            i += 1
            continue

        current.append(char)
        if not char.isspace():
            has_content = True
        i += 1

    flush()
    return statements
