import argparse
import sys
from dataclasses import dataclass
from typing import cast

from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.content import Content
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    OptionList,
    TextArea,
)
from textual.widgets.option_list import Option
from tree_sitter import Parser

from dbshell.database import DatabaseAdapter, DatabaseFactory
from dbshell.explorer import ExplorerModal, ExplorerMode
from dbshell.suggestion_provider import SuggestionProvider


@dataclass
class TargetState:
    text: str
    """The content in the target widget."""

    cursor_position: tuple[int, int]
    """The cursor position in the target widget (line, column)."""


class DropdownItem(Option):
    def __init__(
        self,
        main: str | Content,
        prefix: str | Content | None = None,
        id: str | None = None,
        disabled: bool = False,
    ) -> None:
        self.main = Content(main) if isinstance(main, str) else main
        self.prefix = Content(prefix) if isinstance(prefix, str) else prefix
        left = self.prefix
        prompt = self.main
        if left:
            prompt = Content.assemble(left, self.main)

        super().__init__(prompt, id, disabled)

    @property
    def value(self) -> str:
        return self.main.plain


class AutoComplete(Container):
    DEFAULT_CSS = """
    AutoComplete {
        layer: tooltips;
        display: none;
        width: 30;
        height: auto;
        max-height: 10;
        background: $surface;
        border: solid $accent;
    }
    AutoComplete OptionList {
        border: none;
        background: $surface;
        height: auto;
        scrollbar-size-vertical: 1;
    }
    """

    def __init__(self):
        super().__init__()
        self._option_list = OptionList()
        self._target_state = TargetState("", (0, 0))

    def compose(self) -> ComposeResult:
        self._option_list.can_focus = False
        yield self._option_list

    def show_suggestions(self, suggestions: list[str], position: tuple = None):
        if not suggestions:
            self.display = False
            return

        # Reset offset first to avoid accumulation
        self.styles.offset = (0, 0)

        # Set position if provided
        if position:
            self.styles.offset = position

        # Convert suggestions to DropdownItem objects
        dropdown_items = [DropdownItem(main=suggestion) for suggestion in suggestions]

        self._option_list.clear_options()
        self._option_list.add_options(dropdown_items)

        self.display = True
        if self._option_list.option_count > 0:
            self._option_list.highlighted = 0

    def hide(self):
        self.display = False
        # Reset offset when hiding
        self.styles.offset = (0, 0)

    def move_cursor(self, down: bool = True):
        """Move cursor up or down in the suggestion list."""
        if not self.display or self._option_list.option_count == 0:
            return

        current_index = self._option_list.highlighted or 0

        if down:
            new_index = min(current_index + 1, self._option_list.option_count - 1)
        else:
            new_index = max(current_index - 1, 0)

        self._option_list.highlighted = new_index

    def get_selected_suggestion(self) -> str:
        """Get the currently selected suggestion."""
        if not self.display or self._option_list.option_count == 0:
            return ""

        current_index = self._option_list.highlighted
        if current_index is None or current_index >= self._option_list.option_count:
            return ""

        try:
            option = cast(
                DropdownItem, self._option_list.get_option_at_index(current_index)
            )
            return option.value
        except:
            return ""

    def update_target_state(self, text: str, cursor_position: tuple[int, int]):
        """Update the cached target state."""
        self._target_state = TargetState(text, cursor_position)

    def get_current_word_bounds(self) -> tuple[tuple[int, int], tuple[int, int]]:
        """Get the start and end positions of the current word being typed."""
        cursor_line, cursor_col = self._target_state.cursor_position
        text_lines = self._target_state.text.split("\n")

        if cursor_line >= len(text_lines):
            return (cursor_line, cursor_col), (cursor_line, cursor_col)

        current_line = text_lines[cursor_line]

        # Find start of current word
        start_col = cursor_col
        while start_col > 0 and current_line[start_col - 1].isalnum():
            start_col -= 1

        # Find end of current word
        end_col = cursor_col
        while end_col < len(current_line) and current_line[end_col].isalnum():
            end_col += 1

        return (cursor_line, start_col), (cursor_line, end_col)


class QueryEditor(TextArea):
    BINDINGS = [
        Binding("ctrl+e", "show_explorer", "Show Explorer"),
        Binding("ctrl+d", "select_database", "Select Database"),
        Binding("ctrl+r", "execute_query", "Execute Query"),
        Binding("f8", "execute_query", "Execute Query"),
        Binding("ctrl+a", "select_all", "Select All"),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.suggestion_provider = None

    async def action_execute_query(self) -> None:
        """Handle f8 keyboard shortcut."""
        await self.app.action_execute_query()
        
    async def action_show_explorer(self) -> None:
        """Handle Ctrl+E to show database explorer."""
        await self.app.action_show_explorer()
        
    async def action_select_database(self) -> None:
        """Handle Ctrl+D to select database."""
        await self.app.action_select_database()

    async def action_select_all(self) -> None:
        """Handle Ctrl+A to select all text in the editor."""
        self.select_all()

    @property
    def parser(self) -> Parser:
        return self.document._parser

    def action_accept_suggestion(self) -> None:
        autocomplete = self.app.query_one(AutoComplete)
        if autocomplete.display:
            suggestion = autocomplete.get_selected_suggestion()
            if suggestion:
                self._apply_suggestion(suggestion)
                autocomplete.hide()

    def _apply_suggestion(self, suggestion: str) -> None:
        """Apply the selected suggestion to the text area."""
        # Get current cursor position
        cursor_line, cursor_col = self.cursor_location
        text_lines = self.text.split("\n")

        if cursor_line < len(text_lines):
            current_line = text_lines[cursor_line]

            # Parse to find what we're replacing using tree-sitter
            tree = self.parser.parse(bytes(self.text, "utf8"))
            point = (cursor_line, cursor_col)
            leaf = tree.root_node.descendant_for_point_range(point, point)

            if leaf and leaf.type == "identifier":
                # Replace the identifier
                start_line, start_col = leaf.start_point
                end_line, end_col = leaf.end_point

                # Replace the text
                self.replace(suggestion, (start_line, start_col), (end_line, end_col))
            else:
                # Find word boundaries for partial completion
                start_col = cursor_col
                end_col = cursor_col

                # Find start of current word (look for word characters)
                while start_col > 0 and (
                    current_line[start_col - 1].isalnum()
                    or current_line[start_col - 1] == "_"
                ):
                    start_col -= 1

                # Find end of current word
                while end_col < len(current_line) and (
                    current_line[end_col].isalnum() or current_line[end_col] == "_"
                ):
                    end_col += 1

                # Replace the word or insert at cursor
                if start_col < end_col:
                    # There's a partial word to replace
                    self.replace(
                        suggestion, (cursor_line, start_col), (cursor_line, end_col)
                    )
                else:
                    # No word to replace, just insert
                    self.insert(suggestion, (cursor_line, cursor_col))

    @on(events.Key)
    def on_key(self, event: events.Key) -> None:
        autocomplete = self.app.query_one(AutoComplete)

        if autocomplete.display:
            if event.key == "escape":
                autocomplete.hide()
                event.prevent_default()
            elif event.key == "up":
                autocomplete.move_cursor(down=False)
                event.prevent_default()
                event.stop()  # Stop event propagation
            elif event.key == "down":
                autocomplete.move_cursor(down=True)
                event.prevent_default()
                event.stop()  # Stop event propagation
            elif event.key == "enter":
                self.action_accept_suggestion()
                event.prevent_default()
                event.stop()  # Stop event propagation
            elif event.key == "space":
                # Hide autocomplete on space
                autocomplete.hide()
        elif event.key == "escape":
            autocomplete.hide()


class EditorPanel(Container):
    """Container for the query editor."""

    def compose(self) -> ComposeResult:
        """Create editor panel layout."""
        self.border_title = "Query Editor"
        yield QueryEditor(
            id="query_editor",
            show_line_numbers=True,
            language="sql",
        )
        yield AutoComplete()


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


class DBShellApp(App):
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
        width: 70%;
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
        width: 30%;
        margin-left: 1;
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
    """

    BINDINGS = [
        ("ctrl+r", "execute_query", "Execute Query"),
        ("f8", "execute_query", "Execute Query"),
        ("ctrl+v", "toggle_view", "Toggle View"),
        ("ctrl+e", "show_explorer", "Database Explorer"),
        ("ctrl+d", "select_database", "Select Database"),
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
    ]

    def __init__(self, adapter: DatabaseAdapter, **kwargs):
        super().__init__(**kwargs)
        self.adapter = adapter
        self.connected = False
        self.is_vertical_view = False
        self.current_columns = []
        self.current_rows = []
        self.current_record_index = 0
        self.selected_record_index = None
        self.title = "Dbshell"
        self.suggestion_provider = SuggestionProvider(self.adapter)

    def compose(self) -> ComposeResult:
        """Create the main modern application layout."""
        with Vertical(classes="main-container"):
            yield EditorPanel()
            with Horizontal(classes="action-panel"):
                with Container(classes="select-database-container"):
                    yield Button(
                        "No database selected",
                        id="database_selector",
                        variant="default",
                    )
                with Horizontal(classes="button-group"):
                    yield Button(
                        "◀ Previous",
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
                        "Vertical View",
                        id="toggle_view_btn",
                        variant="default",
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
        editor = self.query_one(QueryEditor)
        editor.suggestion_provider = self.suggestion_provider

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
        """Update the database selector button text"""
        if not self.connected:
            return

        database_selector = self.query_one("#database_selector", Button)
        
        # If we have a current database, show it
        if self.adapter.database:
            database_selector.label = self.adapter.database
        else:
            database_selector.label = "Select Database"


    @on(TextArea.Changed, "#query_editor")
    async def on_text_area_changed(self, event: TextArea.Changed) -> None:
        autocomplete = self.query_one(AutoComplete)

        text = event.text_area.text
        cursor_pos = event.text_area.cursor_location

        # Get the current word being typed
        current_word = self._get_current_word(text, cursor_pos)

        # Get suggestions from the provider
        suggestions = self.suggestion_provider.get_suggestions(
            text, cursor_pos, event.text_area.parser
        )

        # Filter suggestions based on current word if there is one
        if current_word and suggestions:
            filtered_suggestions = [
                s for s in suggestions if s.lower().startswith(current_word.lower())
            ]
            suggestions = filtered_suggestions if filtered_suggestions else suggestions

        if suggestions:
            # Calculate the position relative to the TextArea
            row, col = cursor_pos

            # Get the TextArea widget
            text_area = event.text_area

            # Calculate absolute position based on TextArea's position
            text_area_region = text_area.region

            # Position it below the cursor line, accounting for TextArea's position
            absolute_row = text_area_region.y + row + 1
            absolute_col = text_area_region.x + col

            # If line numbers are shown, add offset for line number column
            if text_area.show_line_numbers:
                absolute_col += 4

            autocomplete.show_suggestions(suggestions, (absolute_col, absolute_row))
        else:
            autocomplete.hide()

    def _get_current_word(self, text: str, cursor_pos: tuple) -> str:
        """Get the current word being typed at cursor position."""
        row, col = cursor_pos
        lines = text.split("\n")

        if row >= len(lines):
            return ""

        current_line = lines[row]

        # Find the start of the current word
        start = col
        while start > 0 and (
            current_line[start - 1].isalnum() or current_line[start - 1] == "_"
        ):
            start -= 1

        # Find the end of the current word
        end = col
        while end < len(current_line) and (
            current_line[end].isalnum() or current_line[end] == "_"
        ):
            end += 1

        return current_line[start:col] if start < col else ""

    @on(Button.Pressed, "#database_selector")
    async def on_database_selector_pressed(self) -> None:
        """Handle database selector button press."""
        await self.action_select_database()

    def get_current_editor(self) -> TextArea:
        """Get the query editor."""
        return self.query_one("#query_editor", TextArea)

    def update_results_info(self, message: str) -> None:
        """Update results info silently."""
        pass

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

    @on(DataTable.RowSelected)
    async def on_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection in horizontal view."""
        if not self.is_vertical_view and self.current_rows:
            # Store the selected record index but don't change view
            self.selected_record_index = event.cursor_row

    async def action_execute_query(self) -> None:
        """Handle f8 keyboard shortcut."""
        await self.execute_query()

    async def action_toggle_view(self) -> None:
        """Handle Ctrl+V keyboard shortcut to toggle view."""
        self.is_vertical_view = not self.is_vertical_view

        # Update button text
        toggle_btn = self.query_one("#toggle_view_btn", Button)
        if self.is_vertical_view:
            toggle_btn.label = "Horizontal View"
            # When switching to vertical view, use the selected record if available
            if self.selected_record_index is not None and self.current_rows:
                self.current_record_index = self.selected_record_index
            elif self.current_rows:
                # If no record was selected, show the first one
                self.current_record_index = 0
        else:
            toggle_btn.label = "Vertical View"

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

        success, message = self.adapter.change_database(database)
        if success:
            self.notify(message, severity="information")
            # Update the database selector button
            database_selector = self.query_one("#database_selector", Button)
            database_selector.label = database
            # Clear current results when changing database
            self.current_columns = []
            self.current_rows = []
            self.current_record_index = 0
            self.selected_record_index = None
            results_table = self.query_one("#results_table", DataTable)
            results_table.clear(columns=True)
        else:
            self.notify(message, severity="error")

    async def action_show_explorer(self) -> None:
        """Handle Ctrl+E keyboard shortcut to show database explorer."""
        # Check if database is selected
        if not self.adapter.database:
            self.notify("Please select a database first", severity="warning")
            return
        
        # Create and show the explorer modal
        explorer_modal = ExplorerModal(self.adapter, mode=ExplorerMode.OBJECTS)
        await self.push_screen(explorer_modal)

    async def navigate_record(self, direction: int) -> None:
        """Navigate to previous (-1) or next (1) record in vertical view."""
        if not self.is_vertical_view or not self.current_rows:
            return

        new_index = self.current_record_index + direction

        # Check bounds
        if 0 <= new_index < len(self.current_rows):
            self.current_record_index = new_index
            await self.update_results_table(self.current_columns, self.current_rows)

    async def execute_query(self) -> None:
        """Execute the SQL query from the current editor."""
        if not self.connected:
            self.notify("No database connection", severity="error")
            return

        # Check if a database is selected (unless it's a query that doesn't require one)
        current_editor = self.get_current_editor()
        query = current_editor.selected_text or current_editor.text
        query_upper = query.strip().upper()

        # These queries don't require a database to be selected
        database_independent_queries = [
            "SHOW DATABASES",
            "CREATE DATABASE",
            "DROP DATABASE",
        ]
        requires_database = not any(
            query_upper.startswith(cmd) for cmd in database_independent_queries
        )

        if requires_database and not self.adapter.database:
            self.notify("Please select a database first", severity="error")
            return

        if not query.strip():
            return

        # Execute query
        success, message, columns, rows = self.adapter.execute_query(query)

        if success:
            # Update results table if we have data
            if columns and rows is not None:
                # Store current data for view toggling
                self.current_columns = columns
                self.current_rows = rows
                self.current_record_index = 0
                self.selected_record_index = None
                # Reset to horizontal view for new queries
                self.is_vertical_view = False
                toggle_btn = self.query_one("#toggle_view_btn", Button)
                toggle_btn.label = "Vertical View"
                await self.update_results_table(columns, rows)
            else:
                # Clear stored data and table for non-SELECT queries
                self.current_columns = []
                self.current_rows = []
                self.current_record_index = 0
                self.selected_record_index = None
                results_table = self.query_one("#results_table", DataTable)
                results_table.clear(columns=True)

                # Check if this was a database-related query and refresh the database list
                query_upper = query.strip().upper()
                if any(
                    cmd in query_upper for cmd in ["CREATE DATABASE", "DROP DATABASE"]
                ):
                    await self.refresh_database()
            results_viewer = self.query_one("ResultViewer")
            results_viewer.border_title = f"Results ({len(rows) if rows else 0} rows)"

        else:
            self.notify(message, severity="error")
            # Clear stored data and table on error
            self.current_columns = []
            self.current_rows = []
            self.current_record_index = 0
            self.selected_record_index = None
            results_table = self.query_one("#results_table", DataTable)
            results_table.clear(columns=True)

    async def update_results_table(self, columns: list[str], rows: list[tuple]) -> None:
        """Update the results table with query results."""
        results_table = self.query_one("#results_table", DataTable)

        # Clear existing data
        results_table.clear(columns=True)

        if not columns:
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
                elif isinstance(value, (int, float)):
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
        for i, (column_name, value) in enumerate(
            zip(columns, current_row, strict=False)
        ):
            # Format the value
            if value is None:
                formatted_value = "[dim]NULL[/dim]"
            elif isinstance(value, (int, float)):
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
        "--password", "-p", help="Database password"
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

    args = parser.parse_args()
    
    if args.database_file:
        if any([args.host, args.user, args.password]):
            parser.error(
                "SQLite mode cannot be used with MySQL arguments "
                "(--host, --user, --password)"
            )
    else:
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
