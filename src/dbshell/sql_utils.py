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
