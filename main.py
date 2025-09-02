#!/usr/bin/env python3
"""
DBShell - A TUI SQL Query Editor and Executor
A modern database shell with advanced query editing and result viewing capabilities.
"""

import argparse
import sys
from typing import Optional, List, Tuple

import mysql.connector
from mysql.connector import Error as MySQLError
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, Container
from textual.widgets import Button, DataTable, Footer, Header, TextArea


class QueryEditor(TextArea):
    BINDINGS = [
        ("ctrl+e", "execute_query", "Execute Query"),
        ("ctrl+a", "select_all", "Select All"),
    ]

    async def action_execute_query(self) -> None:
        """Handle Ctrl+E keyboard shortcut."""
        await self.app.action_execute_query()

    async def action_select_all(self) -> None:
        """Handle Ctrl+A to select all text in the editor."""
        self.select_all()


class ResultViewer(Container):
    """Simple result viewer."""

    DEFAULT_CSS = """
    ResultViewer {
        height: 1fr;
    }
    
    ResultViewer DataTable {
        height: 1fr;
        border: none;
    }
    """

    def compose(self) -> ComposeResult:
        """Create result viewer layout."""
        yield DataTable(id="results_table", zebra_stripes=True, cursor_type="row")


class DatabaseConnection:
    """Manages database connection and query execution."""
    
    def __init__(self, host: str, user: str, password: str, database: str, port: int = 3306):
        self.host = host
        self.user = user
        self.password = password
        self.database = database
        self.port = port
        self.connection: Optional[mysql.connector.MySQLConnection] = None
        self.cursor: Optional[mysql.connector.cursor.MySQLCursor] = None
    
    def connect(self) -> Tuple[bool, str]:
        """
        Establish database connection.
        Returns: (success: bool, message: str)
        """
        try:
            self.connection = mysql.connector.connect(
                host=self.host,
                user=self.user,
                password=self.password,
                database=self.database,
                port=self.port,
                autocommit=True
            )
            self.cursor = self.connection.cursor()
            return True, f"Connected to {self.database} on {self.host}:{self.port}"
        except MySQLError as e:
            return False, f"Connection failed: {str(e)}"
    
    def execute_query(self, query: str) -> Tuple[bool, str, Optional[List], Optional[List]]:
        """
        Execute SQL query.
        Returns: (success: bool, message: str, columns: Optional[List], rows: Optional[List])
        """
        if not self.connection or not self.cursor:
            return False, "No database connection", None, None
        
        try:
            # Strip whitespace and check if query is empty
            query = query.strip()
            if not query:
                return False, "Empty query", None, None
            
            self.cursor.execute(query)
            
            # Check if this is a SELECT query (has results)
            if self.cursor.description:
                columns = [desc[0] for desc in self.cursor.description]
                rows = self.cursor.fetchall()
                row_count = len(rows)
                return True, f"Query successful. {row_count} rows returned.", columns, rows
            else:
                # For INSERT, UPDATE, DELETE, etc.
                row_count = self.cursor.rowcount
                return True, f"Query executed successfully. {row_count} rows affected.", None, None
                
        except MySQLError as e:
            return False, f"Query error: {str(e)}", None, None
    
    def close(self):
        """Close database connection."""
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()


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
    
    .editor-panel {
        height: 30%;
    }
    
    .execute-panel {
        height: auto;
        layout: horizontal;
        align: right middle;
        margin: 0 0;
        padding: 0 1;
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
        ("ctrl+e", "execute_query", "Execute Query"),
        ("ctrl+v", "toggle_view", "Toggle View"),
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
    ]
    
    def __init__(self, db_connection: DatabaseConnection, **kwargs):
        super().__init__(**kwargs)
        self.db_connection = db_connection
        self.connected = False
        self.is_vertical_view = False
        self.current_columns = []
        self.current_rows = []
        self.current_record_index = 0
        self.selected_record_index = None
    
    def compose(self) -> ComposeResult:
        """Create the main modern application layout."""
        yield Header()
        with Vertical(classes="main-container"):
            with Container(classes="editor-panel"):
                yield QueryEditor(
                    id="query_editor",
                    show_line_numbers=True,
                    language="sql",
                )
            with Horizontal(classes="execute-panel"):
                yield Button("◀ Previous", id="prev_record_btn", variant="default", flat=True, disabled=True)
                yield Button("Next ▶", id="next_record_btn", variant="default", flat=True, disabled=True)
                yield Button("Vertical View", id="toggle_view_btn", variant="default", flat=True)
                yield Button("Execute", id="execute_btn", variant="primary", flat=True)
            with Container(classes="results-panel"):
                yield ResultViewer()
        yield Footer()
    
    async def on_mount(self) -> None:
        """Initialize the application after mounting."""
        # Try to connect to database
        success, message = self.db_connection.connect()
        if success:
            self.connected = True
        else:
            self.connected = False
            self.notify(message, severity="error")
        
    
    def get_current_editor(self) -> TextArea:
        """Get the query editor."""
        return self.query_one("#query_editor", TextArea)
    
    def update_results_info(self, message: str) -> None:
        """Update results info silently."""
        pass
    
    @on(Button.Pressed, "#execute_btn")
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
        """Handle Ctrl+E keyboard shortcut."""
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
        
        # Get query text from current editor
        current_editor = self.get_current_editor()
        query = current_editor.selected_text or current_editor.text
        
        if not query.strip():
            return
        
        # Execute query
        success, message, columns, rows = self.db_connection.execute_query(query)
        
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
        else:
            self.notify(message, severity="error")
            # Clear stored data and table on error
            self.current_columns = []
            self.current_rows = []
            self.current_record_index = 0
            self.selected_record_index = None
            results_table = self.query_one("#results_table", DataTable)
            results_table.clear(columns=True)
    
    async def update_results_table(self, columns: List[str], rows: List[Tuple]) -> None:
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
    
    async def update_horizontal_view(self, results_table: DataTable, columns: List[str], rows: List[Tuple]) -> None:
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
    
    async def update_vertical_view(self, results_table: DataTable, columns: List[str], rows: List[Tuple]) -> None:
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
                "[bold]Record {} of {}[/bold]".format(self.current_record_index + 1, len(rows)), 
                ""
            )
            results_table.add_row("", "")
        
        # Show the current record in vertical format
        for i, (column_name, value) in enumerate(zip(columns, current_row)):
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
        self.db_connection.close()
        self.exit()


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="DBShell - A TUI SQL Query Editor and Executor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --host localhost --user root --password mypass --database testdb
  %(prog)s --host 192.168.1.100 --user admin --password secret --database production --port 3307
        """
    )
    
    parser.add_argument(
        "--host",
        required=True,
        help="Database host (required)"
    )
    
    parser.add_argument(
        "--user", "-u",
        required=True,
        help="Database username (required)"
    )
    
    parser.add_argument(
        "--password", "-p",
        required=True,
        help="Database password (required)"
    )
    
    parser.add_argument(
        "--database", "-d",
        required=True,
        help="Database name (required)"
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=3306,
        help="Database port (default: 3306)"
    )
    
    return parser.parse_args()


def main():
    """Main entry point."""
    try:
        args = parse_arguments()
        
        # Create database connection
        db_connection = DatabaseConnection(
            host=args.host,
            user=args.user,
            password=args.password,
            database=args.database,
            port=args.port
        )
        
        # Create and run the application
        app = DBShellApp(db_connection)
        app.run()
        
    except KeyboardInterrupt:
        print("\nApplication interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
