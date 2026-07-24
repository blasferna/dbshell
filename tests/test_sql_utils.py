"""Tests for SQL parsing helpers."""

import pytest

from dbshell.sql_utils import (
    apply_row_limit,
    extract_source_table,
    split_statements,
)


class TestExtractSourceTable:
    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("SELECT * FROM users", "users"),
            ("SELECT * FROM users;", "users"),
            ("select id, name from users where id = 1", "users"),
            ("SELECT * FROM `my table` WHERE x = 1", "my table"),
            ('SELECT * FROM "users" AS u', "users"),
            ("SELECT * FROM [users] u ORDER BY id", "users"),
            ("SELECT * FROM mydb.users", "users"),
            ("SELECT * FROM users LIMIT 10", "users"),
        ],
    )
    def test_simple_selects(self, query, expected):
        assert extract_source_table(query) == expected

    @pytest.mark.parametrize(
        "query",
        [
            None,
            "",
            "   ",
            "INSERT INTO users VALUES (1)",
            "UPDATE users SET name = 'x'",
            "SELECT * FROM users JOIN orders ON users.id = orders.user_id",
            "SELECT * FROM users, orders",
            "SELECT * FROM (SELECT 1) AS sub",
            "SELECT * FROM users UNION SELECT * FROM admins",
            "SELECT id INTO new_table FROM users",
            "SELECT * FROM users WHERE id IN (SELECT user_id FROM orders)",
        ],
    )
    def test_unsupported_queries(self, query):
        assert extract_source_table(query) is None


class TestApplyRowLimit:
    def test_appends_limit_to_select(self):
        assert apply_row_limit("SELECT * FROM users", 100) == (
            "SELECT * FROM users\nLIMIT 100"
        )

    def test_strips_trailing_semicolon(self):
        assert apply_row_limit("SELECT * FROM users;", 50) == (
            "SELECT * FROM users\nLIMIT 50"
        )

    def test_leaves_existing_limit_alone(self):
        assert apply_row_limit("SELECT * FROM users LIMIT 10", 100) == (
            "SELECT * FROM users LIMIT 10"
        )

    def test_leaves_offset_alone(self):
        sql = "SELECT * FROM users OFFSET 5"
        assert apply_row_limit(sql, 100) == sql

    def test_ignores_limit_inside_string(self):
        assert apply_row_limit("SELECT 'LIMIT 1' AS v FROM users", 100) == (
            "SELECT 'LIMIT 1' AS v FROM users\nLIMIT 100"
        )

    def test_ignores_limit_inside_comment(self):
        assert apply_row_limit(
            "SELECT * FROM users -- LIMIT 1\n", 100
        ) == ("SELECT * FROM users -- LIMIT 1\nLIMIT 100")

    def test_skips_non_select(self):
        assert apply_row_limit("UPDATE users SET x = 1", 100) == (
            "UPDATE users SET x = 1"
        )
        assert apply_row_limit("INSERT INTO t VALUES (1)", 100) == (
            "INSERT INTO t VALUES (1)"
        )

    def test_none_or_zero_is_noop(self):
        assert apply_row_limit("SELECT 1", None) == "SELECT 1"
        assert apply_row_limit("SELECT 1", 0) == "SELECT 1"

    def test_with_cte(self):
        sql = "WITH x AS (SELECT 1 AS n) SELECT * FROM x"
        assert apply_row_limit(sql, 5) == f"{sql}\nLIMIT 5"


class TestSplitStatements:
    def test_single_statement(self):
        assert split_statements("SELECT 1") == ["SELECT 1"]

    def test_trailing_semicolon_produces_no_empty_statement(self):
        assert split_statements("SELECT 1;") == ["SELECT 1"]

    def test_multiple_statements(self):
        assert split_statements("SELECT 1; SELECT 2;\nSELECT 3") == [
            "SELECT 1",
            "SELECT 2",
            "SELECT 3",
        ]

    def test_semicolon_inside_string_literal(self):
        assert split_statements("SELECT 'a;b'; SELECT 2") == [
            "SELECT 'a;b'",
            "SELECT 2",
        ]

    def test_semicolon_inside_double_quoted_identifier(self):
        assert split_statements('SELECT "a;b" FROM t; SELECT 2') == [
            'SELECT "a;b" FROM t',
            "SELECT 2",
        ]

    def test_semicolon_inside_backtick_identifier(self):
        assert split_statements("SELECT `a;b`; SELECT 2") == [
            "SELECT `a;b`",
            "SELECT 2",
        ]

    def test_semicolon_inside_bracket_identifier(self):
        assert split_statements("SELECT [a;b] FROM t; SELECT 2") == [
            "SELECT [a;b] FROM t",
            "SELECT 2",
        ]

    def test_semicolon_inside_line_comment(self):
        statements = split_statements("SELECT 1 -- one; two\n; SELECT 2")
        assert len(statements) == 2
        assert statements[0].startswith("SELECT 1")
        assert statements[1] == "SELECT 2"

    def test_semicolon_inside_block_comment(self):
        assert split_statements("SELECT /* one; two */ 1; SELECT 2") == [
            "SELECT /* one; two */ 1",
            "SELECT 2",
        ]

    def test_backslash_escaped_quote(self):
        statements = split_statements(r"SELECT 'a\'; b'; SELECT 2")
        assert statements == [r"SELECT 'a\'; b'", "SELECT 2"]

    def test_comment_only_statements_are_dropped(self):
        assert split_statements("-- nothing here\n; SELECT 1") == ["SELECT 1"]
        assert split_statements("/* just a comment */;") == []

    def test_empty_input(self):
        assert split_statements("") == []
        assert split_statements("  \n\t ") == []
        assert split_statements(";;;") == []

    def test_unterminated_string_is_kept(self):
        # A broken statement is still passed through so the engine can
        # report a proper error.
        assert split_statements("SELECT 'oops") == ["SELECT 'oops"]
