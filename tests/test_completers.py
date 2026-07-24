"""Tests for the autocomplete completers."""

from dbshell.suggestions.completers import MemberCompleter, WordCompleter


class StubAdapter:
    """Minimal duck-typed adapter exposing the schema-introspection API."""

    def get_tables(self, database=None):
        return ["orders", "users"], None

    def get_columns(self, table, database=None):
        return {
            "users": ["id", "name", "email"],
            "orders": ["id", "user_id", "total"],
        }[table]


def values(matches):
    return [value for _, value in matches]


class TestWordCompleter:
    def test_keywords_without_schema(self):
        completer = WordCompleter()
        assert "SELECT" in values(completer("sel"))

    def test_schema_tables_and_columns(self):
        completer = WordCompleter(StubAdapter())
        completer.update_schema()
        assert "users" in values(completer("use"))
        assert "email" in values(completer("ema"))

    def test_clear_schema_removes_tables(self):
        completer = WordCompleter(StubAdapter())
        completer.update_schema()
        completer.clear_schema()
        assert "users" not in values(completer("use"))

    def test_build_and_set_schema_roundtrip(self):
        completer = WordCompleter(StubAdapter())
        completions = completer.build_schema_completions()
        assert completions
        completer.set_schema(completions)
        assert "orders" in values(completer("ord"))


class TestMemberCompleter:
    def make(self):
        completer = MemberCompleter(StubAdapter())
        completer.update_schema()
        return completer

    def test_columns_for_table_prefix(self):
        completer = self.make()
        assert values(completer("users.na")) == ["name"]

    def test_all_columns_on_bare_dot(self):
        completer = self.make()
        assert set(values(completer("users."))) == {"id", "name", "email"}

    def test_unknown_table_yields_nothing(self):
        completer = self.make()
        assert values(completer("ghosts.")) == []

    def test_shared_schema_from_word_completer(self):
        word = WordCompleter(StubAdapter())
        member = MemberCompleter(StubAdapter())
        completions = word.build_schema_completions()
        member.set_schema(list(completions))
        assert "user_id" in values(member("orders."))
