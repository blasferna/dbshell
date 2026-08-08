import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import clipboard
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Select,
    Static,
)
from textual_textarea import TextEditor
from textual_textarea.messages import TextAreaClipboardError
from textual_textarea.text_editor import TextAreaPlus

from dbshell.database import DatabaseAdapter, DatabaseFactory
from dbshell.edit_modal import RecordEditModal
from dbshell.explorer import ExplorerModal, ExplorerMode, ObjectAction
from dbshell.export_modal import ExportModal
from dbshell.exporters import (
    to_csv,
    to_insert_sql,
    to_json,
    to_markdown,
    to_tsv,
)
from dbshell.sql_utils import (
    apply_row_limit,
    extract_source_table,
    split_statements,
)
from dbshell.suggestions import MemberCompleter, WordCompleter
from dbshell.suggestions.completers import SEPARATOR_PROG
from dbshell.suggestions.context import SQLContextAnalyzer


class QueryEditor(TextEditor):
    """SQL query editor powered by textual-textarea."""

    BINDINGS = [
        Binding("ctrl+e", "show_explorer", "Show Explorer"),
        Binding("ctrl+d", "select_database", "Select Database"),
        Binding("ctrl+r", "execute_query", "Execute Query"),
        Binding("f8", "execute_query", "Execute Query"),
    ]

    def __init__(
        self,
        word_completer: WordCompleter | None = None,
        member_completer: MemberCompleter | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            language="sql",
            theme="css",
            word_completer=word_completer,
            member_completer=member_completer,
            **kwargs,
        )

    def on_mount(self) -> None:
        """Increase the completion list width to reduce truncation."""
        super().on_mount()
        self.completion_list.INNER_CONTENT_WIDTH = 60

    def _resolve_member_prefix(self, prefix: str) -> str:
        """Resolve table aliases in member completion prefixes."""
        if self.text_input is None or "." not in prefix:
            return prefix
        parts = SEPARATOR_PROG.split(prefix)
        if len(parts) < 2:
            return prefix
        alias = parts[-2].strip('"\'`')
        item = parts[-1]
        try:
            # Analyze the whole query to resolve aliases.
            context = SQLContextAnalyzer().analyze(self.text, (0, 0))
        except Exception:
            return prefix
        table_name = context.get_table_by_ref(alias)
        if table_name:
            return f"{table_name}.{item}"
        return prefix

    def _member_completer_with_alias(self, prefix: str) -> list[tuple[str, str]]:
        """Return member completions with values prefixed by the user's alias/table."""
        resolved_prefix = self._resolve_member_prefix(prefix)
        alias = prefix.rsplit(".", 1)[0] if "." in prefix else prefix
        matches = self.member_completer(resolved_prefix)
        return [(prompt, f"{alias}.{value}") for prompt, value in matches]

    @on(TextAreaPlus.ShowCompletionList)
    def update_completers_and_completion_list_offset(
        self, event: TextAreaPlus.ShowCompletionList
    ) -> None:
        """Show completions, resolving table aliases for member access."""
        event.stop()
        assert self.text_input is not None
        prefix = event.prefix
        active = self.text_input.completer_active
        # textual-textarea sometimes reports active=None for member prefixes,
        # so detect member completion from the prefix itself and ensure the
        # editor state is updated so keybindings for selecting completions work.
        if active == "member" or (prefix and prefix[-1] == "."):
            active = "member"
            self.text_input.completer_active = "member"
        region_x, region_y, _, _ = self.text_input.region
        self.completion_list.cursor_offset = self.text_input.cursor_screen_offset - (
            region_x,
            region_y,
        )
        if active == "path":
            self.completion_list.show_completions(prefix, self.path_completer)
        elif active == "member":
            self.completion_list.show_completions(
                prefix, self._member_completer_with_alias
            )
        elif active == "word":
            self.completion_list.show_completions(prefix, self.word_completer)

    async def action_execute_query(self) -> None:
        """Handle execute query shortcut."""
        await self.app.action_execute_query()

    async def action_show_explorer(self) -> None:
        """Handle show explorer shortcut."""
        await self.app.action_show_explorer()

    async def action_select_database(self) -> None:
        """Handle select database shortcut."""
        await self.app.action_select_database()


# Prevent TextEditor's inherited completion handler from also running.
_inherited_handlers = dict(TextEditor._decorated_handlers)
_inherited_handlers.pop(TextAreaPlus.ShowCompletionList, None)
TextEditor._decorated_handlers = _inherited_handlers


class EditorPanel(Container):
    """Container for the query editor."""

    def __init__(
        self,
        word_completer: WordCompleter | None = None,
        member_completer: MemberCompleter | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.word_completer = word_completer
        self.member_completer = member_completer

    def compose(self) -> ComposeResult:
        """Create editor panel layout."""
        self.border_title = "Query Editor"
        yield QueryEditor(
            id="query_editor",
            word_completer=self.word_completer,
            member_completer=self.member_completer,
        )


class ResultViewer(Container):
    """Simple result viewer."""

    DEFAULT_CSS = """
    ResultViewer {
        height: 1fr;
        border: solid $secondary;
        border-title-align: left;
    }
    
    ResultViewer:focus-within {
        border: solid $primary;
    }
    
    ResultViewer DataTable {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        """Create result viewer layout."""
        self.border_title = "Results"
        yield DataTable(id="results_table", zebra_stripes=True, cursor_type="row")


class DeleteConfirmModal(ModalScreen[bool]):
    """Confirmation modal shown before deleting a record."""

    DEFAULT_CSS = """
    DeleteConfirmModal {
        align: center middle;
    }

    .delete-dialog {
        width: 50%;
        height: auto;
        border: round $error;
        padding: 1 2;
    }

    .delete-title {
        height: 1;
        content-align: center middle;
        text-style: bold;
        color: $error;
    }

    .delete-message {
        height: auto;
        margin: 1 0;
    }

    .delete-button-row {
        height: 1;
        align-horizontal: center;
        margin: 1 0 0 0;
    }

    .delete-button-row > Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, table: str, pk_values: dict[str, object]) -> None:
        super().__init__()
        self.table = table
        self.pk_values = pk_values

    def compose(self) -> ComposeResult:
        with Container(classes="delete-dialog"):
            yield Static("Delete record", classes="delete-title")
            pk_desc = ", ".join(
                f"{col}={val!r}" for col, val in self.pk_values.items()
            )
            message = (
                f"Are you sure you want to delete this record from "
                f"'{self.table}'?\n\nMatching: {pk_desc}"
            )
            yield Static(message, classes="delete-message")
            with Horizontal(classes="delete-button-row"):
                yield Button("Cancel", id="delete_cancel_btn", variant="default")
                yield Button("Delete", id="delete_confirm_btn", variant="error")

    @on(Button.Pressed, "#delete_cancel_btn")
    def on_cancel_pressed(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#delete_confirm_btn")
    def on_confirm_pressed(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class DBShellApp(App, inherit_bindings=False):
    """Main TUI application for database shell with modern layout."""

    CSS = """
    /* Simple styling */
    Screen {
        layout: vertical;
        background: $background;
    }
    
    .main-container {
        layout: vertical;
        height: 1fr;
    }
    
    EditorPanel {
        height: 37%;
        border: solid $secondary;
        border-title-align: left;
    }
    
    EditorPanel:focus-within {
        border: solid $primary;
    }

    .button-group {
        layout: horizontal;
        align: right middle;
        width: 1fr;
    }
    
    .action-panel {
        height: 1;
    }
    
    Button {
        padding: 0 1;
        height: 1;
        border: none;
        text-style: none;
        min-width: 0;
        width: auto;
        margin: 0 1;
    }
    
    .select-database-container {
        layout: horizontal;
        align: left middle;
        width: auto;
        margin-left: 1;
    }
    
    #database_selector {
        width: auto;
        min-width: 30;
    }

    #row_limit_select {
        width: 15;
        margin: 0 1;
    }

    /* Record navigation only works in vertical view; hidden otherwise. */
    #prev_record_btn, #next_record_btn {
        display: none;
        margin: 0;
    }

    /* Fixed width fitting both labels: Button doesn't re-layout its
       auto width when the label changes at runtime. */
    #toggle_view_btn {
        width: 12;
    }
    
    .results-panel {
        height: 60%;
    }
    
    /* Simple DataTable */
    DataTable {
        background: $surface;
    }
    
    /* TextArea without border and fixed focus issues */
    TextArea {
        background: $surface;
        border: none !important;
        margin: 0;
        padding: 0;
    }

    TextArea:focus {
        border: none !important;
        margin: 0;
        padding: 0;
    }

    /* Autocomplete dropdown styling to match the original DBShell look */
    QueryEditor CompletionList {
        layer: tooltips;
        background: $surface;
        border: tall $primary;
        width: auto;
        min-width: 20;
        max-width: 70;
        max-height: 12;
        padding: 0;
    }

    QueryEditor CompletionList.open {
        display: block;
    }

    QueryEditor CompletionList > .option-list--option {
        padding: 0 1;
    }

    QueryEditor CompletionList > .option-list--option-highlighted {
        background: $primary 30%;
        color: $text;
        text-style: bold;
    }

    QueryEditor CompletionList .completion-list--type-label {
        color: $text-muted;
    }

    QueryEditor CompletionList .completion-list--type-label-highlighted {
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("ctrl+r", "execute_query", "Execute Query"),
        ("f8", "execute_query", "Execute Query"),
        ("ctrl+t", "toggle_view", "Toggle View"),
        ("ctrl+e", "show_explorer", "Database Explorer"),
        ("ctrl+d", "select_database", "Select Database"),
        ("ctrl+u", "edit_record", "Edit Record"),
        ("ctrl+n", "add_record", "Add Record"),
        ("ctrl+shift+d", "delete_record", "Delete Record"),
        ("ctrl+j", "copy_row_json", "Copy Row as JSON"),
        ("ctrl+shift+e", "export_data", "Export Data"),
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
    ]

    EXPORT_FORMATS = ("JSON", "CSV", "TSV", "Markdown", "INSERT SQL")

    def __init__(self, adapter: DatabaseAdapter, **kwargs):
        super().__init__(**kwargs)
        self.adapter = adapter
        self.connected = False
        self.is_vertical_view = False
        self.current_columns = []
        self.current_rows = []
        self.current_record_index = 0
        self.selected_record_index = None
        self.last_select_query: str | None = None
        self.source_table: str | None = None
        self._query_running = False
        self.title = "Dbshell"
        self.word_completer = WordCompleter(self.adapter)
        self.member_completer = MemberCompleter(self.adapter)

    ROW_LIMIT_PRESETS = (100, 500, 1000, 5000, 10000)

    def _row_limit_options(self) -> list[tuple[str, int]]:
        """Build the row-limit choices, including the current adapter value."""
        values = set(self.ROW_LIMIT_PRESETS)
        if self.adapter.max_rows:
            values.add(self.adapter.max_rows)
        options = [(f"LIMIT {value}", value) for value in sorted(values)]
        options.append(("No LIMIT", 0))
        return options

    @on(Select.Changed, "#row_limit_select")
    def on_row_limit_changed(self, event: Select.Changed) -> None:
        """Apply the selected SELECT row limit (0 means no LIMIT)."""
        if event.value is Select.BLANK:
            return
        # 0 = "No LIMIT" in the dropdown; adapters treat None as uncapped.
        self.adapter.max_rows = int(event.value) or None

    def compose(self) -> ComposeResult:
        """Create the main modern application layout."""
        with Vertical(classes="main-container"):
            yield EditorPanel(
                word_completer=self.word_completer,
                member_completer=self.member_completer,
            )
            with Horizontal(classes="action-panel"):
                with Container(classes="select-database-container"):
                    yield Button(
                        "No database selected",
                        id="database_selector",
                        variant="default",
                    )
                with Horizontal(classes="button-group"):
                    yield Select(
                        self._row_limit_options(),
                        value=self.adapter.max_rows or 0,
                        allow_blank=False,
                        compact=True,
                        id="row_limit_select",
                    )
                    yield Button(
                        "◀ Prev",
                        id="prev_record_btn",
                        variant="default",
                        disabled=True,
                    )
                    yield Button(
                        "Next ▶",
                        id="next_record_btn",
                        variant="default",
                        disabled=True,
                    )
                    yield Button(
                        "Edit Record",
                        id="edit_record_btn",
                        variant="default",
                        disabled=True,
                    )
                    yield Button(
                        "Add Record",
                        id="add_record_btn",
                        variant="default",
                        disabled=True,
                    )
                    yield Button(
                        "Delete Record",
                        id="delete_record_btn",
                        variant="error",
                        disabled=True,
                    )
                    yield Button(
                        "Vertical",
                        id="toggle_view_btn",
                        variant="default",
                    )
                    yield Button(
                        "Export",
                        id="export_btn",
                        variant="default",
                        disabled=True,
                    )
                    yield Button(
                        "Run",
                        id="run_btn",
                        variant="primary",
                    )
            with Container(classes="results-panel"):
                yield ResultViewer()
        yield Footer()

    async def on_mount(self) -> None:
        """Initialize the application after mounting."""
        # Try to connect to database (without selecting a specific database first)
        success, message = self.adapter.connect()
        if success:
            self.connected = True
            # If a database was specified in args, notify user
            if self.adapter.database:
                self.notify(message, severity="information")
            await self.refresh_database()
        else:
            self.connected = False
            self.notify(message, severity="error")

    async def refresh_database(self) -> None:
        """Update the database selector button and refresh autocomplete schema."""
        if not self.connected:
            return

        database_selector = self.query_one("#database_selector", Button)

        # If we have a current database, show it and load schema completions
        if self.adapter.database:
            database_selector.label = self.adapter.database
            await self._refresh_schema_completions()
        else:
            database_selector.label = "Select Database"
            self.word_completer.clear_schema()
            self.member_completer.clear_schema()

    async def _refresh_schema_completions(self) -> None:
        """Load table/column completions in a thread so the UI stays responsive."""
        completions = await asyncio.to_thread(
            self.word_completer.build_schema_completions
        )
        self.word_completer.set_schema(completions)
        self.member_completer.set_schema(list(completions))

    @on(TextAreaClipboardError)
    def on_text_area_clipboard_error(self) -> None:
        """Notify the user when the editor cannot access the system clipboard."""
        self.notify(
            "Could not access the system clipboard. "
            "Copy/paste may still work inside the editor.",
            severity="warning",
        )

    @on(Button.Pressed, "#database_selector")
    async def on_database_selector_pressed(self) -> None:
        """Handle database selector button press."""
        await self.action_select_database()

    def get_current_editor(self) -> QueryEditor:
        """Get the query editor."""
        return self.query_one("#query_editor", QueryEditor)

    @on(Button.Pressed, "#run_btn")
    async def execute_query_button(self) -> None:
        """Handle execute button press."""
        await self.execute_query()

    @on(Button.Pressed, "#toggle_view_btn")
    async def toggle_view_button(self) -> None:
        """Handle view toggle button press."""
        await self.action_toggle_view()

    @on(Button.Pressed, "#prev_record_btn")
    async def prev_record_button(self) -> None:
        """Handle previous record button press."""
        await self.navigate_record(-1)

    @on(Button.Pressed, "#next_record_btn")
    async def next_record_button(self) -> None:
        """Handle next record button press."""
        await self.navigate_record(1)

    @on(Button.Pressed, "#edit_record_btn")
    async def edit_record_button(self) -> None:
        """Handle edit record button press."""
        await self.action_edit_record()

    @on(Button.Pressed, "#add_record_btn")
    async def add_record_button(self) -> None:
        """Handle add record button press."""
        await self.action_add_record()

    @on(Button.Pressed, "#delete_record_btn")
    async def delete_record_button(self) -> None:
        """Handle delete record button press."""
        await self.action_delete_record()

    @on(Button.Pressed, "#export_btn")
    async def export_button(self) -> None:
        """Handle export button press."""
        await self.action_export_data()

    @on(DataTable.RowSelected)
    async def on_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection in horizontal view."""
        if not self.is_vertical_view and self.current_rows:
            # Store the selected record index but don't change view
            self.selected_record_index = event.cursor_row

    async def action_execute_query(self) -> None:
        """Handle f8 keyboard shortcut."""
        await self.execute_query()

    def _update_nav_buttons_visibility(self) -> None:
        """Show Previous/Next only in vertical view, where they work."""
        for button_id in ("#prev_record_btn", "#next_record_btn"):
            self.query_one(button_id, Button).display = self.is_vertical_view

    async def action_toggle_view(self) -> None:
        """Handle Ctrl+V keyboard shortcut to toggle view."""
        self.is_vertical_view = not self.is_vertical_view
        self._update_nav_buttons_visibility()

        # Update button text
        toggle_btn = self.query_one("#toggle_view_btn", Button)
        if self.is_vertical_view:
            toggle_btn.label = "Horizontal"
            # When switching to vertical view, use the selected record if available
            if self.selected_record_index is not None and self.current_rows:
                self.current_record_index = self.selected_record_index
            elif self.current_rows:
                # If no record was selected, show the first one
                self.current_record_index = 0
        else:
            toggle_btn.label = "Vertical"

        # Refresh the table with current data if available
        if self.current_columns and self.current_rows:
            await self.update_results_table(self.current_columns, self.current_rows)

    async def action_select_database(self) -> None:
        """Handle Ctrl+D keyboard shortcut to select database."""
        if not self.connected:
            self.notify("No database connection", severity="error")
            return
        
        explorer_modal = ExplorerModal(self.adapter, mode=ExplorerMode.DATABASES)
        
        def modal_callback(result):
            if result and isinstance(result, str):
                self.call_later(self.change_database, result)
                editor = self.query_one(QueryEditor)
                self.set_focus(editor)

        self.push_screen(explorer_modal, modal_callback)

    async def change_database(self, database: str) -> None:
        """Change to the specified database."""
        if not self.connected:
            self.notify("No database connection", severity="error")
            return

        success, message = await asyncio.to_thread(
            self.adapter.change_database, database
        )
        if success:
            self.notify(message, severity="information")
            # Update the database selector button
            database_selector = self.query_one("#database_selector", Button)
            database_selector.label = database
            # Refresh autocomplete schema for the new database
            await self._refresh_schema_completions()
            # Clear current results when changing database
            self._clear_results()
            await self._update_edit_button_state()
            await self._update_add_button_state()
            await self._update_delete_button_state()
            await self._update_export_button_state()
        else:
            self.notify(message, severity="error")

    def _clear_results(self) -> None:
        """Reset stored result state and empty the results table."""
        self.current_columns = []
        self.current_rows = []
        self.current_record_index = 0
        self.selected_record_index = None
        self.last_select_query = None
        self.source_table = None
        results_table = self.query_one("#results_table", DataTable)
        results_table.clear(columns=True)

    async def action_show_explorer(self) -> None:
        """Handle Ctrl+E keyboard shortcut to show database explorer."""
        # Check if database is selected
        if not self.adapter.database:
            self.notify("Please select a database first", severity="warning")
            return

        # Create and show the explorer modal with an action callback
        explorer_modal = ExplorerModal(
            self.adapter,
            mode=ExplorerMode.OBJECTS,
            on_action=self._on_explorer_action,
        )
        await self.push_screen(explorer_modal)

    def _on_explorer_action(
        self, obj_name: str, obj_type: str, action: ObjectAction
    ) -> None:
        """Handle the action chosen from the explorer's object action menu."""
        self.call_later(self._handle_object_action, obj_name, obj_type, action)

    async def _handle_object_action(
        self, obj_name: str, obj_type: str, action: ObjectAction
    ) -> None:
        """Apply the chosen explorer action to the editor or clipboard."""
        if not self.connected:
            self.notify("No database connection", severity="error")
            return

        quoted = self.adapter.quote_identifier(obj_name)

        if action == ObjectAction.VIEW_DATA:
            sql = f"SELECT * FROM {quoted}"
            if self.adapter.max_rows:
                sql = f"{sql} LIMIT {self.adapter.max_rows}"
            self._replace_editor_text(f"{sql};")
            return

        if action == ObjectAction.ADD_RECORD:
            await self._open_add_record_modal(obj_name)
            return

        if action in (
            ObjectAction.INSERT_TEMPLATE,
            ObjectAction.UPDATE_TEMPLATE,
            ObjectAction.DELETE_TEMPLATE,
        ):
            success, message, columns = (
                self.adapter.get_object_columns_detailed(obj_name)
            )
            if not success or not columns:
                self.notify(
                    f"Cannot build template: {message}",
                    severity="error",
                )
                return
            column_names = [c[0] for c in columns]
            placeholders = ", ".join("?" for _ in column_names)
            quoted_columns = ", ".join(
                self.adapter.quote_identifier(c) for c in column_names
            )
            if action == ObjectAction.INSERT_TEMPLATE:
                sql = (
                    f"INSERT INTO {quoted} ({quoted_columns}) "
                    f"VALUES ({placeholders});"
                )
            elif action == ObjectAction.UPDATE_TEMPLATE:
                assignments = ", ".join(
                    f"{self.adapter.quote_identifier(c)} = ?"
                    for c in column_names
                )
                sql = (
                    f"UPDATE {quoted} SET {assignments} WHERE ...;"
                )
            else:
                sql = f"DELETE FROM {quoted} WHERE ...;"
            self._replace_editor_text(sql)
            return

        if action == ObjectAction.COPY_NAME:
            try:
                clipboard.copy(obj_name)
                self.notify(f"Copied name '{obj_name}' to clipboard")
            except Exception as exc:
                self.notify(f"Copy failed: {exc}", severity="error")
            return

        if action == ObjectAction.COPY_CREATE_SQL:
            success, message, creation_sql = (
                self.adapter.get_object_creation_sql(obj_name, obj_type)
            )
            if not success or not creation_sql:
                self.notify(
                    f"Cannot copy CREATE SQL: {message}",
                    severity="error",
                )
                return
            try:
                clipboard.copy(creation_sql)
                self.notify("Copied CREATE SQL to clipboard")
            except Exception as exc:
                self.notify(f"Copy failed: {exc}", severity="error")
            return

    def _replace_editor_text(self, text: str) -> None:
        """Replace the editor text with the given SQL and return focus to it."""
        editor = self.query_one(QueryEditor)
        editor.text = text
        self.set_focus(editor)
        self.notify("SQL inserted into editor — press F8 to run")

    async def navigate_record(self, direction: int) -> None:
        """Navigate to previous (-1) or next (1) record in vertical view."""
        if not self.is_vertical_view or not self.current_rows:
            return

        new_index = self.current_record_index + direction

        # Check bounds
        if 0 <= new_index < len(self.current_rows):
            self.current_record_index = new_index
            await self.update_results_table(self.current_columns, self.current_rows)

    def _get_active_record_index(self) -> int | None:
        """Return the index of the row that should be edited."""
        if not self.current_rows:
            return None
        if self.is_vertical_view:
            idx = self.current_record_index
        else:
            idx = (
                self.selected_record_index
                if self.selected_record_index is not None
                else 0
            )
        if 0 <= idx < len(self.current_rows):
            return idx
        return None

    async def _update_edit_button_state(self) -> None:
        """Enable the Edit Record button only when editing is possible."""
        try:
            edit_btn = self.query_one("#edit_record_btn", Button)
        except Exception:
            return
        edit_btn.disabled = self.source_table is None or not self.current_rows

    async def _update_add_button_state(self) -> None:
        """Enable the Add Record button whenever a source table is known.

        Unlike editing, adding a row does not require any existing rows -
        an empty table is a perfectly valid target for a new record.
        """
        try:
            add_btn = self.query_one("#add_record_btn", Button)
        except Exception:
            return
        add_btn.disabled = self.source_table is None

    async def _update_export_button_state(self) -> None:
        """Enable the Export button only when there are results."""
        try:
            export_btn = self.query_one("#export_btn", Button)
        except Exception:
            return
        export_btn.disabled = not self.current_rows

    async def _update_delete_button_state(self) -> None:
        """Enable the Delete Record button only when deletion is possible."""
        try:
            delete_btn = self.query_one("#delete_record_btn", Button)
        except Exception:
            return
        delete_btn.disabled = self.source_table is None or not self.current_rows

    async def action_edit_record(self) -> None:
        """Open the edit modal for the currently selected/active record."""
        if not self.connected:
            self.notify("No database connection", severity="error")
            return

        if not self.current_rows or not self.current_columns:
            self.notify("Run a SELECT first to load a record", severity="warning")
            return

        if not self.source_table:
            self.notify(
                "Cannot determine source table for the current results. "
                "Use a simple 'SELECT ... FROM <table>' query.",
                severity="warning",
            )
            return

        index = self._get_active_record_index()
        if index is None:
            self.notify("No record selected", severity="warning")
            return

        ok, message, primary_keys = self.adapter.get_primary_keys(self.source_table)
        if not ok:
            self.notify(f"Cannot edit: {message}", severity="error")
            return
        if not primary_keys:
            self.notify(
                f"Table '{self.source_table}' has no primary key; cannot edit safely.",
                severity="warning",
            )
            return

        row = self.current_rows[index]
        modal = RecordEditModal(
            self.adapter,
            self.source_table,
            list(self.current_columns),
            list(row),
            primary_keys,
        )

        def _on_close(result: bool | None) -> None:
            if result is True:
                self.call_later(self._refresh_after_edit, index)

        self.push_screen(modal, _on_close)

    async def _refresh_after_edit(self, previous_index: int) -> None:
        """Re-run the last SELECT after a successful edit and reposition the view."""
        if not self.last_select_query:
            return

        success, message, columns, rows = await asyncio.to_thread(
            self.adapter.execute_query, self.last_select_query
        )
        if not success:
            self.notify(f"Refresh failed: {message}", severity="error")
            return

        if columns and rows is not None:
            self.current_columns = columns
            self.current_rows = rows
            # Try to keep the same row in view; clamp to the new bounds.
            if rows:
                self.current_record_index = min(previous_index, len(rows) - 1)
                self.selected_record_index = self.current_record_index
            else:
                self.current_record_index = 0
                self.selected_record_index = None
            await self.update_results_table(columns, rows)
            self.notify("Row updated", severity="information")

        results_viewer = self.query_one("ResultViewer")
        results_viewer.border_title = f"Results ({len(rows) if rows else 0} rows)"

    async def action_add_record(self) -> None:
        """Open the add-record modal for the current source table (Ctrl+N)."""
        if not self.connected:
            self.notify("No database connection", severity="error")
            return

        if not self.source_table:
            self.notify(
                "Run a SELECT first (or use the Explorer) to choose a table",
                severity="warning",
            )
            return

        await self._open_add_record_modal(self.source_table)

    async def _open_add_record_modal(self, table: str) -> None:
        """Open a blank RecordEditModal to insert a new row into ``table``."""
        if not self.connected:
            self.notify("No database connection", severity="error")
            return

        success, message, columns = self.adapter.get_object_columns_detailed(table)
        if not success or not columns:
            self.notify(f"Cannot add record: {message}", severity="error")
            return

        ok, _, primary_keys = self.adapter.get_primary_keys(table)
        if not ok or primary_keys is None:
            # Non-fatal: PK info is only a display/default hint when adding.
            primary_keys = []

        column_names = [c[0] for c in columns]
        modal = RecordEditModal(
            self.adapter,
            table,
            column_names,
            [None] * len(column_names),
            primary_keys,
            is_new=True,
        )

        def _on_close(result: bool | None) -> None:
            if result is True:
                if table == self.source_table:
                    self.call_later(self._refresh_after_add)
                else:
                    self.notify(f"Row inserted into '{table}'")

        self.push_screen(modal, _on_close)

    async def _refresh_after_add(self) -> None:
        """Re-run the last SELECT after an insert and jump to the new row."""
        if not self.last_select_query:
            return

        success, message, columns, rows = await asyncio.to_thread(
            self.adapter.execute_query, self.last_select_query
        )
        if not success:
            self.notify(f"Refresh failed: {message}", severity="error")
            return

        if columns and rows is not None:
            self.current_columns = columns
            self.current_rows = rows
            # A newly inserted row is expected to land at the end.
            if rows:
                self.current_record_index = len(rows) - 1
                self.selected_record_index = self.current_record_index
            else:
                self.current_record_index = 0
                self.selected_record_index = None
            await self.update_results_table(columns, rows)
            self.notify("Row inserted", severity="information")

        results_viewer = self.query_one("ResultViewer")
        results_viewer.border_title = f"Results ({len(rows) if rows else 0} rows)"
        # Row count changed (e.g. 0 -> 1), so Edit/Add/Delete availability can too.
        await self._update_edit_button_state()
        await self._update_add_button_state()
        await self._update_delete_button_state()

    async def action_delete_record(self) -> None:
        """Open the delete confirmation modal for the active record."""
        if not self.connected:
            self.notify("No database connection", severity="error")
            return

        if not self.current_rows or not self.current_columns:
            self.notify("Run a SELECT first to load a record", severity="warning")
            return

        if not self.source_table:
            self.notify(
                "Cannot determine source table for the current results. "
                "Use a simple 'SELECT ... FROM <table>' query.",
                severity="warning",
            )
            return

        index = self._get_active_record_index()
        if index is None:
            self.notify("No record selected", severity="warning")
            return

        ok, message, primary_keys = self.adapter.get_primary_keys(self.source_table)
        if not ok:
            self.notify(f"Cannot delete: {message}", severity="error")
            return
        if not primary_keys:
            self.notify(
                f"Table '{self.source_table}' has no primary key; "
                "cannot delete safely.",
                severity="warning",
            )
            return

        row = self.current_rows[index]
        pk_values = {
            pk: row[self.current_columns.index(pk)]
            for pk in primary_keys
            if pk in self.current_columns
        }
        if not pk_values or len(pk_values) != len(primary_keys):
            self.notify(
                "Primary key columns are not present in the current result set; "
                "cannot build DELETE condition.",
                severity="warning",
            )
            return

        modal = DeleteConfirmModal(self.source_table, pk_values)

        def _on_close(confirmed: bool) -> None:
            if confirmed:
                self.call_later(self._perform_delete, index, primary_keys, pk_values)

        self.push_screen(modal, _on_close)

    async def _perform_delete(
        self,
        previous_index: int,
        primary_keys: list[str],
        pk_values: dict[str, object],
    ) -> None:
        """Execute the DELETE for the active record and refresh results."""
        quoted_table = self.adapter.quote_identifier(self.source_table)
        where_parts: list[str] = []
        params: list[object] = []
        for pk in primary_keys:
            quoted_pk = self.adapter.quote_identifier(pk)
            where_parts.append(f"{quoted_pk} = {self.adapter.param_placeholder}")
            params.append(pk_values[pk])

        sql = f"DELETE FROM {quoted_table} WHERE {' AND '.join(where_parts)};"
        success, message, _, _ = await asyncio.to_thread(
            self.adapter.execute_query, sql, params
        )
        if not success:
            self.notify(f"Delete failed: {message}", severity="error")
            return

        self.notify("Row deleted", severity="information")
        await self._refresh_after_delete(previous_index)

    async def _refresh_after_delete(self, previous_index: int) -> None:
        """Re-run the last SELECT after a delete and update the view."""
        if not self.last_select_query:
            return

        success, message, columns, rows = await asyncio.to_thread(
            self.adapter.execute_query, self.last_select_query
        )
        if not success:
            self.notify(f"Refresh failed: {message}", severity="error")
            return

        if columns and rows is not None:
            self.current_columns = columns
            self.current_rows = rows
            if rows:
                self.current_record_index = min(previous_index, len(rows) - 1)
                self.selected_record_index = self.current_record_index
            else:
                self.current_record_index = 0
                self.selected_record_index = None
            await self.update_results_table(columns, rows)

        results_viewer = self.query_one("ResultViewer")
        results_viewer.border_title = f"Results ({len(rows) if rows else 0} rows)"
        await self._update_edit_button_state()
        await self._update_add_button_state()
        await self._update_delete_button_state()

    async def action_copy_row_json(self) -> None:
        """Copy the currently active row as a JSON object to the clipboard."""
        if not self.current_rows or not self.current_columns:
            self.notify("Run a query first", severity="warning")
            return

        index = self._get_active_record_index()
        if index is None:
            self.notify("No row selected", severity="warning")
            return

        row = self.current_rows[index]
        payload = json.dumps(
            dict(zip(list(self.current_columns), list(row), strict=False)),
            indent=2,
            default=str,
        )
        try:
            clipboard.copy(payload)
        except Exception as exc:
            self.notify(f"Copy failed: {exc}", severity="error")
            return
        self.notify("Row copied as JSON to clipboard")

    async def action_export_data(self) -> None:
        """Open the export modal and write the current result set."""
        if not self.current_columns or not self.current_rows:
            self.notify("Run a query first", severity="warning")
            return

        formats = list(self.EXPORT_FORMATS)
        if not self.source_table and "INSERT SQL" in formats:
            formats.remove("INSERT SQL")

        def _on_close(result: tuple[str, str | None] | None) -> None:
            if result is None:
                return
            fmt, destination = result
            self.call_later(self._perform_export, fmt, destination)

        self.push_screen(ExportModal(formats=formats), _on_close)

    async def _perform_export(self, fmt: str, destination: str | None) -> None:
        """Render the result set in the chosen format and send it to its destination."""
        if not self.current_columns or not self.current_rows:
            return

        columns = list(self.current_columns)
        rows = [tuple(r) for r in self.current_rows]

        try:
            if fmt == "JSON":
                text = to_json(columns, rows)
            elif fmt == "CSV":
                text = to_csv(columns, rows)
            elif fmt == "TSV":
                text = to_tsv(columns, rows)
            elif fmt == "Markdown":
                text = to_markdown(columns, rows)
            elif fmt == "INSERT SQL":
                if not self.source_table:
                    self.notify(
                        "INSERT SQL export needs a single source table",
                        severity="error",
                    )
                    return
                text = to_insert_sql(
                    columns,
                    rows,
                    table=self.source_table,
                    quoter=self.adapter.quote_identifier,
                )
            else:
                self.notify(f"Unknown format: {fmt}", severity="error")
                return
        except Exception as exc:
            self.notify(f"Export failed: {exc}", severity="error")
            return

        row_count = len(self.current_rows)
        if destination is None:
            try:
                clipboard.copy(text)
            except Exception as exc:
                self.notify(f"Copy failed: {exc}", severity="error")
                return
            self.notify(
                f"Exported {row_count} row(s) as {fmt} to clipboard"
            )
        else:
            try:
                path = Path(destination).expanduser()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            except OSError as exc:
                self.notify(f"Write failed: {exc}", severity="error")
                return
            self.notify(f"Exported {row_count} row(s) as {fmt} to {path}")

    async def execute_query(self) -> None:
        """Execute the SQL from the current editor without blocking the UI."""
        if not self.connected:
            self.notify("No database connection", severity="error")
            return

        if self._query_running:
            self.notify("A query is already running", severity="warning")
            return

        current_editor = self.get_current_editor()
        query = current_editor.selected_text or current_editor.text
        statements = split_statements(query)
        if not statements:
            return

        # These queries don't require a database to be selected.
        database_independent_queries = (
            "SHOW DATABASES",
            "CREATE DATABASE",
            "DROP DATABASE",
        )
        requires_database = not all(
            statement.upper().startswith(database_independent_queries)
            for statement in statements
        )

        if requires_database and not self.adapter.database:
            self.notify("Please select a database first", severity="error")
            return

        run_btn = self.query_one("#run_btn", Button)
        results_viewer = self.query_one(ResultViewer)
        self._query_running = True
        run_btn.disabled = True
        results_viewer.border_title = "Results — running…"

        last_columns: list | None = None
        last_rows: list | None = None
        last_result_statement: str | None = None
        last_truncated = False
        last_message = ""
        error_message: str | None = None
        ran_database_statement = False
        start = time.monotonic()

        try:
            for index, statement in enumerate(statements):
                # Apply the UI/CLI row limit as a SELECT LIMIT when the
                # statement does not already have one. The editor text is
                # left untouched; only the statement sent to the DB changes.
                executable = apply_row_limit(statement, self.adapter.max_rows)
                success, message, columns, rows = await asyncio.to_thread(
                    self.adapter.execute_query, executable
                )
                if not success:
                    error_message = message
                    if len(statements) > 1:
                        error_message = (
                            f"Statement {index + 1} of {len(statements)} "
                            f"failed: {message}"
                        )
                    break

                last_message = message
                if columns and rows is not None:
                    last_columns = columns
                    last_rows = rows
                    # Keep the executed form (with LIMIT) so Edit Record
                    # refresh uses the same capped query.
                    last_result_statement = executable
                    last_truncated = self.adapter.last_result_truncated

                statement_upper = statement.upper()
                if "CREATE DATABASE" in statement_upper or (
                    "DROP DATABASE" in statement_upper
                ):
                    ran_database_statement = True
        finally:
            self._query_running = False
            run_btn.disabled = False

        elapsed = time.monotonic() - start

        if error_message is not None:
            self.notify(error_message, severity="error")
            self._clear_results()
            results_viewer.border_title = "Results"
        elif last_columns and last_rows is not None:
            # Store current data for view toggling
            self.current_columns = last_columns
            self.current_rows = last_rows
            self.current_record_index = 0
            self.selected_record_index = None
            # Track the last statement that produced results and its source
            # table so the Edit Record action can build an UPDATE statement.
            self.last_select_query = last_result_statement
            self.source_table = extract_source_table(last_result_statement)
            # Reset to horizontal view for new queries
            self.is_vertical_view = False
            self._update_nav_buttons_visibility()
            toggle_btn = self.query_one("#toggle_view_btn", Button)
            toggle_btn.label = "Vertical"
            await self.update_results_table(last_columns, last_rows)

            row_count = len(last_rows)
            if last_truncated:
                results_viewer.border_title = (
                    f"Results (first {row_count} rows, truncated — {elapsed:.2f}s)"
                )
                self.notify(
                    f"Result truncated to the first {row_count} rows",
                    severity="warning",
                )
            else:
                results_viewer.border_title = (
                    f"Results ({row_count} rows in {elapsed:.2f}s)"
                )
        else:
            # No result set: clear the table and report what happened.
            self._clear_results()
            if ran_database_statement:
                await self.refresh_database()
            results_viewer.border_title = f"Results (0 rows in {elapsed:.2f}s)"
            summary = last_message or "Query executed."
            if len(statements) > 1:
                summary = f"Executed {len(statements)} statements. {summary}"
            self.notify(summary)

        await self._update_edit_button_state()
        await self._update_add_button_state()
        await self._update_delete_button_state()
        await self._update_export_button_state()

    async def update_results_table(self, columns: list[str], rows: list[tuple]) -> None:
        """Update the results table with query results."""
        results_table = self.query_one("#results_table", DataTable)

        # Clear existing data
        results_table.clear(columns=True)

        if not columns:
            await self._update_export_button_state()
            return

        if self.is_vertical_view:
            # Vertical view: show records as Column/Value pairs
            await self.update_vertical_view(results_table, columns, rows)
        else:
            # Horizontal view: traditional table format
            await self.update_horizontal_view(results_table, columns, rows)

        # Update navigation buttons state
        if self.is_vertical_view and rows:
            await self.update_navigation_buttons()

        await self._update_export_button_state()

    async def update_horizontal_view(
        self, results_table: DataTable, columns: list[str], rows: list[tuple]
    ) -> None:
        """Update table in traditional horizontal view."""
        # Add columns with enhanced styling
        for column in columns:
            results_table.add_column(column, key=column)

        # Add rows with proper formatting
        for row in rows:
            # Convert all values to strings for display, handle various data types
            str_row = []
            for value in row:
                if value is None:
                    str_row.append("[dim]NULL[/dim]")
                elif isinstance(value, int | float):
                    str_row.append(str(value))
                elif isinstance(value, str):
                    # Truncate very long strings for display
                    if len(value) > 100:
                        str_row.append(f"{value[:97]}...")
                    else:
                        str_row.append(value)
                else:
                    str_row.append(str(value))
            results_table.add_row(*str_row)

    async def update_vertical_view(
        self, results_table: DataTable, columns: list[str], rows: list[tuple]
    ) -> None:
        """Update table in vertical view showing each record as Column/Value pairs."""
        # Add two columns: Column and Value
        results_table.add_column("Column", key="column")
        results_table.add_column("Value", key="value")

        if not rows:
            return

        # Ensure current_record_index is within bounds
        if self.current_record_index >= len(rows):
            self.current_record_index = 0

        # Show the current record in vertical format
        current_row = rows[self.current_record_index]

        # Add header showing current record info
        if len(rows) > 1:
            results_table.add_row(
                f"[bold]Record {self.current_record_index + 1} of {len(rows)}[/bold]",
                "",
            )
            results_table.add_row("", "")

        # Show the current record in vertical format
        for column_name, value in zip(
            columns, current_row, strict=False
        ):
            # Format the value
            if value is None:
                formatted_value = "[dim]NULL[/dim]"
            elif isinstance(value, int | float):
                formatted_value = str(value)
            elif isinstance(value, str):
                # Don't truncate in vertical view as we have more space
                formatted_value = value
            else:
                formatted_value = str(value)

            results_table.add_row(column_name, formatted_value)

    async def update_navigation_buttons(self) -> None:
        """Update the state of navigation buttons."""
        if not self.current_rows:
            return

        prev_btn = self.query_one("#prev_record_btn", Button)
        next_btn = self.query_one("#next_record_btn", Button)

        # Enable/disable buttons based on current position
        prev_btn.disabled = self.current_record_index <= 0
        next_btn.disabled = self.current_record_index >= len(self.current_rows) - 1

    async def action_quit(self) -> None:
        """Handle quit action."""
        self.adapter.close()
        self.exit()


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="DBShell - A TUI SQL Query Editor and Executor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
        epilog="""
Examples:
  SQLite:
    %(prog)s /path/to/database.db
    %(prog)s :memory:  # In-memory database
    
  MySQL/MariaDB:
    %(prog)s --host localhost --user root --password mypass --database testdb
    %(prog)s --host localhost --user root --password mypass
    %(prog)s --host 192.168.1.100 --user admin --password secret \\
             --database production --port 3307
    %(prog)s -h localhost -u user -p pass -d mydb -P 3306
        """,
    )

    # Add manual help argument
    parser.add_argument("--help", action="help", help="Show this help message and exit")

    # Positional argument for SQLite database file
    parser.add_argument(
        "database_file", 
        nargs="?",
        help="SQLite database file path (use ':memory:' for in-memory database)"
    )

    # MySQL/MariaDB options
    parser.add_argument("--host", "-h", help="Database host")

    parser.add_argument(
        "--user", "-u", help="Database username"
    )

    parser.add_argument(
        "--password", "-p",
        nargs="?",
        const=None,
        help="Database password (if omitted, will prompt if -p is used)"
    )

    parser.add_argument(
        "--database",
        "-d",
        required=False,
        help="Database name (optional - can be selected interactively)",
    )

    parser.add_argument(
        "--port", "-P", type=int, default=3306, help="Database port (default: 3306)"
    )

    parser.add_argument(
        "--ssl-disabled",
        action="store_true",
        help="Disable SSL for MySQL",
    )

    parser.add_argument(
        "--max-rows",
        type=int,
        default=1000,
        help=(
            "Maximum number of rows fetched per query "
            "(default: 1000, 0 disables the limit; "
            "can also be changed from the UI)"
        ),
    )

    args = parser.parse_args()

    if args.database_file:
        if any([args.host, args.user, args.password]):
            parser.error(
                "SQLite mode cannot be used with MySQL arguments "
                "(--host, --user, --password)"
            )
    else:
        # Prompt for password if -p/--password is used without a value
        if hasattr(args, "password") and args.password is None:
            import getpass
            args.password = getpass.getpass("Enter database password: ")

        if not all([args.host, args.user, args.password]):
            parser.error(
                "MySQL mode requires --host, --user, and --password arguments "
                "(or provide a database file for SQLite)"
            )

    return args


def main():
    """Main entry point."""
    try:
        args = parse_arguments()

        database_factory = DatabaseFactory()
        
        if args.database_file:
            adapter = database_factory.create_adapter(
                "sqlite",
                {
                    "database": args.database_file,
                    "max_rows": args.max_rows,
                },
            )
        else:
            adapter = database_factory.create_adapter(
                "mysql",
                {
                    "host": args.host,
                    "user": args.user,
                    "password": args.password,
                    "database": args.database,
                    "port": args.port,
                    "ssl_disabled": args.ssl_disabled,
                    "max_rows": args.max_rows,
                },
            )
        
        # Create and run the application
        app = DBShellApp(adapter)
        app.run()

    except KeyboardInterrupt:
        print("\nApplication interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
