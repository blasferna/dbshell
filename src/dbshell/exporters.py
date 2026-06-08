from __future__ import annotations

import csv
import datetime as _dt
import decimal
import io
import json
import uuid
from collections.abc import Callable, Iterable, Sequence
from typing import Any


class _ExportJSONEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, decimal.Decimal):
            return str(o)
        if isinstance(o, _dt.datetime | _dt.date | _dt.time):
            return o.isoformat()
        if isinstance(o, _dt.timedelta):
            return str(o)
        if isinstance(o, bytes | bytearray | memoryview):
            return bytes(o).hex()
        if isinstance(o, uuid.UUID):
            return str(o)
        return str(o)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, _dt.datetime | _dt.date | _dt.time | _dt.timedelta):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value).hex()
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


def to_json(
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    *,
    indent: int | None = 2,
) -> str:
    records: list[dict[str, Any]] = []
    for row in rows:
        record: dict[str, Any] = {}
        for column, value in zip(columns, row, strict=False):
            record[column] = value
        records.append(record)
    return json.dumps(records, indent=indent, cls=_ExportJSONEncoder)


def to_csv(
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    *,
    delimiter: str = ",",
) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n")
    writer.writerow(list(columns))
    for row in rows:
        writer.writerow([_stringify(v) for v in row])
    return buffer.getvalue()


def to_tsv(columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    return to_csv(columns, rows, delimiter="\t")


def _md_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def to_markdown(columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    headers = [str(c) for c in columns]
    lines: list[str] = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        cells = []
        for v in row:
            if v is None:
                cells.append("")
            else:
                cells.append(_md_escape(_stringify(v)))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def to_insert_sql(
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    *,
    table: str,
    quoter: Callable[[str], str],
) -> str:
    if not table:
        raise ValueError("A source table is required for INSERT SQL export.")
    quoted_table = quoter(table)
    quoted_columns = ", ".join(quoter(c) for c in columns)
    statements: list[str] = []
    for row in rows:
        values: list[str] = []
        for v in row:
            if v is None:
                values.append("NULL")
            elif isinstance(v, bool):
                values.append("TRUE" if v else "FALSE")
            elif isinstance(v, int | float | decimal.Decimal):
                values.append(str(v))
            else:
                text = _stringify(v).replace("'", "''")
                values.append(f"'{text}'")
        prefix = f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ("
        statements.append(f"{prefix}{', '.join(values)});")
    return "\n".join(statements)
