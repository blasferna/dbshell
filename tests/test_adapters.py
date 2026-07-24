"""Tests for the database adapters (SQLite end-to-end, MySQL pure parts)."""

import sqlite3

import pytest

from dbshell.database.mysql_adapter import MySQLAdapter
from dbshell.database.sqlite_adapter import SQLiteAdapter

RETURNING_SUPPORTED = sqlite3.sqlite_version_info >= (3, 35)


def make_sqlite(database=":memory:", **params) -> SQLiteAdapter:
    adapter = SQLiteAdapter({"database": database, **params})
    success, message = adapter.connect()
    assert success, message
    return adapter


class TestSQLiteAdapter:
    def test_select_returns_rows(self):
        adapter = make_sqlite()
        success, message, columns, rows = adapter.execute_query(
            "SELECT 1 AS one, 'x' AS two"
        )
        assert success, message
        assert columns == ["one", "two"]
        assert rows == [(1, "x")]

    def test_empty_query_fails(self):
        adapter = make_sqlite()
        success, message, _, _ = adapter.execute_query("   ")
        assert not success
        assert message == "Empty query"

    def test_error_is_reported(self):
        adapter = make_sqlite()
        success, message, _, _ = adapter.execute_query("SELEC oops")
        assert not success
        assert "Query error" in message

    def test_params_preserve_special_characters(self):
        adapter = make_sqlite()
        adapter.execute_query("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        # Backslashes and quotes must survive a parameterized round-trip.
        value = "O'Hara \\ C:\\temp \\' end"
        success, message, _, _ = adapter.execute_query(
            "INSERT INTO t (v) VALUES (?)", (value,)
        )
        assert success, message
        _, _, _, rows = adapter.execute_query("SELECT v FROM t")
        assert rows == [(value,)]

    def test_row_cap_truncates_results(self):
        adapter = make_sqlite(max_rows=5)
        adapter.execute_query("CREATE TABLE n (v INTEGER)")
        for i in range(10):
            adapter.execute_query("INSERT INTO n VALUES (?)", (i,))

        success, message, _, rows = adapter.execute_query("SELECT * FROM n")
        assert success
        assert len(rows) == 5
        assert adapter.last_result_truncated is True
        assert "first 5" in message

        # The flag resets for the next, smaller result.
        _, _, _, rows = adapter.execute_query("SELECT * FROM n LIMIT 2")
        assert len(rows) == 2
        assert adapter.last_result_truncated is False

    def test_zero_max_rows_disables_cap(self):
        adapter = make_sqlite(max_rows=0)
        assert adapter.max_rows is None
        adapter.execute_query("CREATE TABLE n (v INTEGER)")
        for i in range(10):
            adapter.execute_query("INSERT INTO n VALUES (?)", (i,))

        success, message, _, rows = adapter.execute_query("SELECT * FROM n")
        assert success
        assert len(rows) == 10
        assert adapter.last_result_truncated is False
        assert "10 rows" in message

    def test_max_rows_can_change_at_runtime(self):
        adapter = make_sqlite(max_rows=5)
        adapter.execute_query("CREATE TABLE n (v INTEGER)")
        for i in range(10):
            adapter.execute_query("INSERT INTO n VALUES (?)", (i,))

        adapter.max_rows = None
        _, _, _, rows = adapter.execute_query("SELECT * FROM n")
        assert len(rows) == 10

        adapter.max_rows = 3
        _, _, _, rows = adapter.execute_query("SELECT * FROM n")
        assert len(rows) == 3
        assert adapter.last_result_truncated is True

    def test_dml_persists_across_connections(self, tmp_path):
        db_file = str(tmp_path / "data.db")
        first = make_sqlite(db_file)
        first.execute_query("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        first.execute_query("INSERT INTO t (v) VALUES (?)", ("kept",))
        first.close()

        second = make_sqlite(db_file)
        _, _, _, rows = second.execute_query("SELECT v FROM t")
        assert rows == [("kept",)]
        second.close()

    @pytest.mark.skipif(
        not RETURNING_SUPPORTED, reason="requires SQLite >= 3.35"
    )
    def test_insert_returning_persists(self, tmp_path):
        # Regression: statements that return rows used to skip the commit,
        # silently losing the write when the app closed.
        db_file = str(tmp_path / "data.db")
        first = make_sqlite(db_file)
        first.execute_query("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        success, message, columns, rows = first.execute_query(
            "INSERT INTO t (v) VALUES (?) RETURNING id", ("kept",)
        )
        assert success, message
        assert rows == [(1,)]
        first.close()

        second = make_sqlite(db_file)
        _, _, _, rows = second.execute_query("SELECT v FROM t")
        assert rows == [("kept",)]
        second.close()

    def test_quote_identifier_escapes_quotes(self):
        adapter = make_sqlite()
        assert adapter.quote_identifier("plain") == '"plain"'
        assert adapter.quote_identifier('we"ird') == '"we""ird"'

    def test_hostile_identifier_roundtrip(self):
        adapter = make_sqlite()
        table = 'we"ird name'
        quoted = adapter.quote_identifier(table)
        success, message, _, _ = adapter.execute_query(
            f"CREATE TABLE {quoted} (id INTEGER PRIMARY KEY, v TEXT)"
        )
        assert success, message

        assert adapter.get_columns(table) == ["id", "v"]

        ok, message, pks = adapter.get_primary_keys(table)
        assert ok, message
        assert pks == ["id"]

        ok, message, count = adapter.get_row_count(table)
        assert ok, message
        assert count == 0

    def test_primary_keys_composite_order(self):
        adapter = make_sqlite()
        adapter.execute_query(
            "CREATE TABLE c (a INTEGER, b INTEGER, v TEXT, PRIMARY KEY (a, b))"
        )
        ok, _, pks = adapter.get_primary_keys("c")
        assert ok
        assert pks == ["a", "b"]

    def test_view_has_no_primary_keys(self):
        adapter = make_sqlite()
        adapter.execute_query("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        adapter.execute_query("CREATE VIEW v AS SELECT * FROM t")
        ok, _, pks = adapter.get_primary_keys("v")
        assert ok
        assert pks == []

    def test_multiple_statements_rejected_at_adapter_level(self):
        # Scripts are split by the app; a single adapter call must be a
        # single statement.
        adapter = make_sqlite()
        success, _, _, _ = adapter.execute_query("SELECT 1; SELECT 2")
        assert not success

    def test_param_placeholder(self):
        adapter = make_sqlite()
        assert adapter.param_placeholder == "?"


class TestMySQLAdapterPureParts:
    def make(self) -> MySQLAdapter:
        return MySQLAdapter({"host": "example", "user": "u", "password": "p"})

    def test_quote_identifier_escapes_backticks(self):
        adapter = self.make()
        assert adapter.quote_identifier("plain") == "`plain`"
        assert adapter.quote_identifier("we`ird") == "`we``ird`"

    def test_param_placeholder(self):
        adapter = self.make()
        assert adapter.param_placeholder == "%s"

    def test_execute_without_connection_fails_cleanly(self):
        adapter = self.make()
        success, message, columns, rows = adapter.execute_query("SELECT 1")
        assert not success
        assert message == "No database connection"
        assert columns is None and rows is None
