"""Tests for the result-set exporters."""

import datetime
import decimal
import json

from dbshell.exporters import to_csv, to_insert_sql, to_json, to_markdown, to_tsv

COLUMNS = ["id", "name", "score"]
ROWS = [
    (1, "alice", 9.5),
    (2, None, decimal.Decimal("1.25")),
]


def quoter(name: str) -> str:
    return f'"{name}"'


class TestToJson:
    def test_basic_records(self):
        records = json.loads(to_json(COLUMNS, ROWS))
        assert records == [
            {"id": 1, "name": "alice", "score": 9.5},
            {"id": 2, "name": None, "score": "1.25"},
        ]

    def test_special_types(self):
        columns = ["ts", "blob"]
        rows = [(datetime.datetime(2026, 1, 2, 3, 4, 5), b"\x00\xff")]
        records = json.loads(to_json(columns, rows))
        assert records == [{"ts": "2026-01-02T03:04:05", "blob": "00ff"}]


class TestToCsv:
    def test_header_and_rows(self):
        lines = to_csv(COLUMNS, ROWS).splitlines()
        assert lines[0] == "id,name,score"
        assert lines[1] == "1,alice,9.5"
        assert lines[2] == "2,,1.25"

    def test_quoting_of_delimiters(self):
        text = to_csv(["v"], [("a,b",), ('say "hi"',)])
        lines = text.splitlines()
        assert lines[1] == '"a,b"'
        assert lines[2] == '"say ""hi"""'


class TestToTsv:
    def test_uses_tabs(self):
        lines = to_tsv(COLUMNS, ROWS).splitlines()
        assert lines[0] == "id\tname\tscore"
        assert lines[1] == "1\talice\t9.5"


class TestToMarkdown:
    def test_table_shape(self):
        lines = to_markdown(COLUMNS, ROWS).splitlines()
        assert lines[0] == "| id | name | score |"
        assert lines[1] == "| --- | --- | --- |"
        assert lines[2] == "| 1 | alice | 9.5 |"
        assert lines[3] == "| 2 |  | 1.25 |"

    def test_escapes_pipes_and_newlines(self):
        lines = to_markdown(["v"], [("a|b\nc",)]).splitlines()
        assert lines[2] == "| a\\|b c |"


class TestToInsertSql:
    def test_statements(self):
        text = to_insert_sql(COLUMNS, ROWS, table="users", quoter=quoter)
        lines = text.splitlines()
        assert lines[0] == (
            'INSERT INTO "users" ("id", "name", "score") '
            "VALUES (1, 'alice', 9.5);"
        )
        assert lines[1] == (
            'INSERT INTO "users" ("id", "name", "score") '
            "VALUES (2, NULL, 1.25);"
        )

    def test_escapes_single_quotes(self):
        text = to_insert_sql(["name"], [("O'Hara",)], table="t", quoter=quoter)
        assert "VALUES ('O''Hara');" in text

    def test_requires_table(self):
        import pytest

        with pytest.raises(ValueError):
            to_insert_sql(["a"], [(1,)], table="", quoter=quoter)
