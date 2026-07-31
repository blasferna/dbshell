"""Smoke tests for the Textual application against an in-memory SQLite DB."""

from textual.widgets import Button, DataTable, Input, Select

from dbshell import DBShellApp, ResultViewer
from dbshell.database import DatabaseFactory
from dbshell.explorer import ObjectAction


def make_app(**params) -> DBShellApp:
    adapter = DatabaseFactory().create_adapter(
        "sqlite", {"database": ":memory:", **params}
    )
    return DBShellApp(adapter)


async def test_multi_statement_script_shows_last_result_set():
    app = make_app()
    async with app.run_test() as pilot:
        editor = app.get_current_editor()
        editor.text = (
            "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT);\n"
            "INSERT INTO t (name) VALUES ('alpha');\n"
            "INSERT INTO t (name) VALUES ('beta');\n"
            "SELECT * FROM t;"
        )
        await app.execute_query()
        await pilot.pause()

        assert app.current_columns == ["id", "name"]
        assert app.current_rows == [(1, "alpha"), (2, "beta")]
        assert app.source_table == "t"

        table = app.query_one("#results_table", DataTable)
        assert table.row_count == 2

        viewer = app.query_one(ResultViewer)
        assert "2 rows" in viewer.border_title


async def test_select_gets_limit_appended_by_default():
    app = make_app(max_rows=3)
    async with app.run_test() as pilot:
        editor = app.get_current_editor()
        script = ["CREATE TABLE n (v INTEGER);"]
        script += [f"INSERT INTO n VALUES ({i});" for i in range(10)]
        script.append("SELECT * FROM n;")
        editor.text = "\n".join(script)

        await app.execute_query()
        await pilot.pause()

        # LIMIT is applied at execution time; the editor text stays as written.
        assert "LIMIT" not in editor.text.split("SELECT * FROM n;")[-1]
        assert len(app.current_rows) == 3
        assert app.last_select_query == "SELECT * FROM n\nLIMIT 3"
        viewer = app.query_one(ResultViewer)
        assert "3 rows" in viewer.border_title


async def test_existing_limit_in_query_is_respected():
    app = make_app(max_rows=1000)
    async with app.run_test() as pilot:
        editor = app.get_current_editor()
        editor.text = (
            "CREATE TABLE n (v INTEGER);"
            + "".join(f"INSERT INTO n VALUES ({i});" for i in range(10))
            + "SELECT * FROM n LIMIT 2;"
        )
        await app.execute_query()
        await pilot.pause()
        assert len(app.current_rows) == 2
        assert app.last_select_query == "SELECT * FROM n LIMIT 2"


async def test_row_limit_select_updates_adapter():
    app = make_app()
    async with app.run_test() as pilot:
        select = app.query_one("#row_limit_select", Select)
        # Defaults to the CLI/default limit.
        assert select.value == 1000
        assert app.adapter.max_rows == 1000

        select.value = 100
        await pilot.pause()
        assert app.adapter.max_rows == 100

        select.value = 0
        await pilot.pause()
        assert app.adapter.max_rows is None


async def test_row_limit_change_applies_to_next_query():
    app = make_app(max_rows=3)
    async with app.run_test() as pilot:
        editor = app.get_current_editor()
        script = ["CREATE TABLE n (v INTEGER);"]
        script += [f"INSERT INTO n VALUES ({i});" for i in range(10)]
        script.append("SELECT * FROM n;")
        editor.text = "\n".join(script)
        await app.execute_query()
        await pilot.pause()
        assert len(app.current_rows) == 3

        # The non-preset CLI value is offered in the dropdown.
        select = app.query_one("#row_limit_select", Select)
        assert select.value == 3

        select.value = 0
        await pilot.pause()
        editor.text = "SELECT * FROM n;"
        await app.execute_query()
        await pilot.pause()
        assert len(app.current_rows) == 10
        assert app.last_select_query == "SELECT * FROM n"
        viewer = app.query_one(ResultViewer)
        assert "truncated" not in viewer.border_title

        select.value = 100
        await pilot.pause()
        editor.text = "SELECT * FROM n;"
        await app.execute_query()
        await pilot.pause()
        assert len(app.current_rows) == 10  # table only has 10 rows
        assert app.last_select_query == "SELECT * FROM n\nLIMIT 100"


async def test_failing_statement_clears_results():
    app = make_app()
    async with app.run_test() as pilot:
        editor = app.get_current_editor()
        editor.text = "SELECT 1; SELEC oops;"

        await app.execute_query()
        await pilot.pause()

        assert app.current_rows == []
        table = app.query_one("#results_table", DataTable)
        assert table.row_count == 0


async def test_add_record_button_enabled_without_rows():
    app = make_app()
    async with app.run_test() as pilot:
        editor = app.get_current_editor()
        editor.text = (
            "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT);\nSELECT * FROM t;"
        )
        await app.execute_query()
        await pilot.pause()

        # An empty table still has a known source table, so adding is fine
        # even though there is nothing to edit yet.
        assert app.current_rows == []
        assert app.source_table == "t"

        add_btn = app.query_one("#add_record_btn", Button)
        edit_btn = app.query_one("#edit_record_btn", Button)
        assert add_btn.disabled is False
        assert edit_btn.disabled is True


async def test_add_record_inserts_row_via_modal():
    app = make_app()
    async with app.run_test() as pilot:
        editor = app.get_current_editor()
        editor.text = (
            "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT);\nSELECT * FROM t;"
        )
        await app.execute_query()
        await pilot.pause()
        assert app.current_rows == []

        await app.action_add_record()
        await pilot.pause()

        modal = app.screen
        name_input = modal.query_one("#input_name", Input)
        name_input.value = "alpha"

        modal.action_save()
        await pilot.pause()
        await pilot.pause()

        assert app.current_rows == [(1, "alpha")]
        assert app.current_record_index == 0

        add_btn = app.query_one("#add_record_btn", Button)
        edit_btn = app.query_one("#edit_record_btn", Button)
        assert add_btn.disabled is False
        assert edit_btn.disabled is False


async def test_add_record_from_explorer_leaves_other_results_untouched():
    app = make_app()
    async with app.run_test() as pilot:
        editor = app.get_current_editor()
        editor.text = (
            "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT);\n"
            "CREATE TABLE other (id INTEGER PRIMARY KEY, label TEXT);\n"
            "INSERT INTO other (label) VALUES ('keep');\n"
            "SELECT * FROM other;"
        )
        await app.execute_query()
        await pilot.pause()
        assert app.source_table == "other"
        previous_rows = app.current_rows

        # Trigger the Explorer's "Add Record" action for a *different* table.
        await app._handle_object_action("t", "tables", ObjectAction.ADD_RECORD)
        await pilot.pause()

        modal = app.screen
        name_input = modal.query_one("#input_name", Input)
        name_input.value = "beta"
        modal.action_save()
        await pilot.pause()
        await pilot.pause()

        # The currently-loaded results (a different table) are untouched.
        assert app.current_rows == previous_rows
        assert app.source_table == "other"

        # But the row really was inserted into "t".
        success, _, _, rows = app.adapter.execute_query("SELECT name FROM t")
        assert success
        assert rows == [("beta",)]
