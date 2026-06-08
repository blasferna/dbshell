
import contextlib
from collections.abc import Callable
from enum import Enum

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Input,
    OptionList,
    Static,
    TextArea,
)
from textual.widgets.option_list import Option

from dbshell.database import DatabaseAdapter


class ExplorerMode(Enum):
    """Explorer mode constants."""
    OBJECTS = "objects"
    DATABASES = "databases"


class ObjectAction(Enum):
    """Actions available for a database object."""

    VIEW_DATA = "View Data"
    INSERT_TEMPLATE = "Insert Template"
    UPDATE_TEMPLATE = "Update Template"
    DELETE_TEMPLATE = "Delete Template"
    COPY_NAME = "Copy Name"
    COPY_CREATE_SQL = "Copy CREATE SQL"


_OBJECT_TYPE_LABELS = {
    "tables": "Table",
    "views": "View",
    "procedures": "Procedure",
    "functions": "Function",
}


def get_available_actions(obj_type: str) -> list[ObjectAction]:
    """Return the list of valid actions for the given object type."""
    if obj_type == "tables":
        return [
            ObjectAction.VIEW_DATA,
            ObjectAction.INSERT_TEMPLATE,
            ObjectAction.UPDATE_TEMPLATE,
            ObjectAction.DELETE_TEMPLATE,
            ObjectAction.COPY_NAME,
            ObjectAction.COPY_CREATE_SQL,
        ]
    if obj_type == "views":
        return [
            ObjectAction.VIEW_DATA,
            ObjectAction.COPY_NAME,
            ObjectAction.COPY_CREATE_SQL,
        ]
    if obj_type in ("procedures", "functions"):
        return [
            ObjectAction.COPY_NAME,
            ObjectAction.COPY_CREATE_SQL,
        ]
    return [ObjectAction.COPY_NAME]


class ObjectOption(Option):
    """Custom option class that stores object name and type."""

    def __init__(self, display_text: str, obj_name: str, obj_type: str):
        super().__init__(display_text)
        self.obj_name = obj_name
        self.obj_type = obj_type

    @property
    def value(self) -> str:
        """Return the value in format 'name|type' for compatibility."""
        return f"{self.obj_name}|{self.obj_type}"


class Explorer(Container):
    """Explorer for database objects."""

    DEFAULT_CSS = """
    Explorer {
        height: 1fr;
        border: round $primary;
        border-title-align: left;
    }

    .explorer-left {
        width: 40%;
        layout: vertical;
    }

    .explorer-right {
        width: 60%;
        layout: vertical;
    }

    /* When in databases mode, make the left panel full width */
    Explorer.databases-mode .explorer-left {
        width: 100%;
    }

    .search-input {
        height: 3;
        margin: 1;
    }

    .objects-list {
        height: 1fr;
        margin: 0 1 1 1;
    }

    .details-area {
        height: 1fr;
        margin: 1;
    }

    #objects_list {
        scrollbar-size: 1 1;
    }

    """

    def __init__(
        self,
        db_adapter: DatabaseAdapter | None = None,
        mode: ExplorerMode = ExplorerMode.OBJECTS,
    ):
        super().__init__()
        self.db_adapter = db_adapter
        self.mode = mode
        self.objects_data: dict[str, list[str]] = {}
        self.all_objects: list[tuple[str, str]] = []
        self.filtered_objects: list[tuple[str, str]] = []

    def compose(self) -> ComposeResult:
        """Create explorer layout."""
        title = (" Database Explorer " if self.mode == ExplorerMode.OBJECTS
                else " Database Selector ")
        self.border_title = title

        # Add CSS class for databases mode
        if self.mode == ExplorerMode.DATABASES:
            self.add_class("databases-mode")

        with Horizontal():
            with Vertical(classes="explorer-left"):
                yield OptionList(id="objects_list", classes="objects-list")
                placeholder = ("Search objects..." if self.mode == ExplorerMode.OBJECTS
                             else "Search databases...")
                yield Input(
                    placeholder=placeholder,
                    id="search_input",
                    classes="search-input"
                )

            if self.mode == ExplorerMode.OBJECTS:
                # Only show details area in objects mode
                with Vertical(classes="explorer-right"):
                    yield TextArea(
                        id="details_area",
                        classes="details-area",
                        read_only=True,
                        language="sql",
                        show_line_numbers=False
                    )

    def on_mount(self) -> None:
        """Initialize the explorer."""
        if self.db_adapter:
            self._refresh()
        # Set focus to the search input when explorer opens
        search_input = self.query_one("#search_input", Input)
        search_input.focus()

    def set_adapter(self, adapter: DatabaseAdapter) -> None:
        """Set the database adapter and refresh objects."""
        self.db_adapter = adapter
        self._refresh()

    def _refresh(self) -> None:
        """Refresh the explorer based on current mode."""
        if self.mode == ExplorerMode.OBJECTS:
            self._refresh_objects()
        elif self.mode == ExplorerMode.DATABASES:
            self._refresh_databases()

    def _refresh_databases(self) -> None:
        """Refresh the list of databases."""
        if not self.db_adapter:
            return

        success, message, databases = self.db_adapter.get_databases()
        if success and databases:
            # Use all_objects and filtered_objects for databases too
            self.all_objects = [(db_name, "database") for db_name in databases]
            self.filtered_objects = self.all_objects.copy()
            self.update_objects_list()
        else:
            self.all_objects = []
            self.filtered_objects = []

        # No details area in database mode, so no need to update it

    def _refresh_objects(self) -> None:
        """Refresh the list of database objects."""
        if not self.db_adapter:
            if self.mode == ExplorerMode.OBJECTS:
                details_area = self.query_one("#details_area", TextArea)
                details_area.text = "No database adapter available"
            return

        success, message, objects = self.db_adapter.get_database_objects()
        if success and objects:
            self.objects_data = objects
            self.all_objects = []

            for obj_type, obj_list in objects.items():
                for obj_name in obj_list:
                    self.all_objects.append((obj_name, obj_type))

            self.filtered_objects = self.all_objects.copy()
            self.update_objects_list()
        else:
            self.objects_data = {}
            self.all_objects = []
            self.filtered_objects = []

        if self.mode == ExplorerMode.OBJECTS:
            details_area = self.query_one("#details_area", TextArea)
            if success:
                details_area.text = (f"Database objects loaded successfully.\n"
                                   f"{message}")
            else:
                details_area.text = f"Failed to load objects: {message}"

    def update_objects_list(self) -> None:
        """Update the objects list display."""
        objects_list = self.query_one("#objects_list", OptionList)
        objects_list.clear_options()

        for obj_name, obj_type in self.filtered_objects:
            if self.mode == ExplorerMode.DATABASES:
                # Simple display for databases
                display_text = obj_name
            else:
                # Create a formatted display string with type prefix in dim color
                type_prefix = {
                    "tables": "t",
                    "views": "v",
                    "procedures": "p",
                    "functions": "f",
                }.get(obj_type, "?")

                # Use rich markup to dim the type prefix
                display_text = f"[dim]{type_prefix}[/dim] {obj_name}"

            objects_list.add_option(
                ObjectOption(display_text, obj_name, obj_type)
            )

        # Show static info for the first item if available (objects mode only)
        if self.filtered_objects and self.mode == ExplorerMode.OBJECTS:
            first_obj_name, first_obj_type = self.filtered_objects[0]
            self.show_static_info(first_obj_name, first_obj_type)

    @on(Input.Changed, "#search_input")
    def filter_objects(self, event: Input.Changed) -> None:
        """Filter objects based on search input."""
        search_term = event.value.lower()

        if not search_term:
            self.filtered_objects = self.all_objects.copy()
        else:
            self.filtered_objects = [
                (name, obj_type) for name, obj_type in self.all_objects
                if search_term in name.lower()
            ]

        self.update_objects_list()

    @on(Input.Submitted, "#search_input")
    def on_search_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in search input - move focus to list."""
        objects_list = self.query_one("#objects_list", OptionList)
        if self.filtered_objects:
            objects_list.focus()

    def on_key(self, event) -> None:
        """Handle key events for navigation."""
        # Check if the search input is focused
        search_input = self.query_one("#search_input", Input)
        objects_list = self.query_one("#objects_list", OptionList)

        # Handle Ctrl+J (down) and Ctrl+K (up) navigation
        if event.key == "ctrl+j" or event.key == "ctrl+k":
            # Ensure objects list is focused for navigation
            if not objects_list.has_focus and self.filtered_objects:
                objects_list.focus()
                if event.key == "ctrl+j" and len(objects_list.options) > 0:
                    objects_list.highlighted = 0
                elif event.key == "ctrl+k" and len(objects_list.options) > 0:
                    objects_list.highlighted = len(objects_list.options) - 1
            elif objects_list.has_focus and self.filtered_objects:
                # Navigate within the list
                current_index = objects_list.highlighted or 0
                if event.key == "ctrl+j":
                    # Move down (Ctrl+J)
                    new_index = min(current_index + 1, len(objects_list.options) - 1)
                    objects_list.highlighted = new_index
                elif event.key == "ctrl+k":
                    # Move up (Ctrl+K)
                    new_index = max(current_index - 1, 0)
                    objects_list.highlighted = new_index
            event.prevent_default()
        elif search_input.has_focus and event.key in ("down", "up"):
            # Move focus to objects list for navigation
            if self.filtered_objects:
                objects_list.focus()
                # If pressed down, ensure first item is highlighted
                if event.key == "down" and len(objects_list.options) > 0:
                    objects_list.highlighted = 0
            event.prevent_default()
        elif objects_list.has_focus:
            # Check if user is typing regular characters - move to search input
            if (len(event.key) == 1 and event.key.isprintable() and
                not event.key.isspace()):
                # Store the character to type
                char_to_type = event.key

                # Clear search and focus on input
                search_input.value = ""
                search_input.focus()

                # Use set_timer to add character after focus is fully processed
                self.set_timer(0.01, lambda: self._add_char_to_search(char_to_type))
                event.prevent_default()
            elif event.key == "backspace":
                # Move focus to search input for backspace (edit search)
                search_input.focus()
                # Remove last character if there's content
                if search_input.value:
                    search_input.value = search_input.value[:-1]
                    search_input.cursor_position = len(search_input.value)
                event.prevent_default()

    def _add_char_to_search(self, char: str) -> None:
        """Helper method to add character to search input after focus is set."""
        search_input = self.query_one("#search_input", Input)
        search_input.insert_text_at_cursor(char)

    @on(OptionList.OptionSelected, "#objects_list")
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection - push the action menu in objects mode."""
        if self.mode != ExplorerMode.OBJECTS:
            return
        if not event.option or not event.option.value:
            return

        obj_name, obj_type = event.option.value.split("|", 1)
        self._open_action_menu(obj_name, obj_type)

    @on(OptionList.OptionHighlighted, "#objects_list")
    def show_object_details_on_highlight(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Show static info of the highlighted object (navigation with arrow keys)."""
        if self.mode != ExplorerMode.OBJECTS:
            return
        if not event.option or not event.option.value:
            return

        obj_name, obj_type = event.option.value.split("|", 1)
        self.show_static_info(obj_name, obj_type)

    def show_static_info(self, obj_name: str, obj_type: str) -> None:
        """Show static info (type, columns, row count) for the object."""
        if not self.db_adapter or self.mode != ExplorerMode.OBJECTS:
            return

        details_area = self.query_one("#details_area", TextArea)
        type_label = _OBJECT_TYPE_LABELS.get(obj_type, obj_type)
        lines: list[str] = [
            f"[bold]{type_label}[/bold]: {obj_name}",
            "",
        ]

        if obj_type in ("tables", "views"):
            success, message, columns = self.db_adapter.get_object_columns_detailed(
                obj_name
            )
            if success and columns:
                lines.append(f"[bold]Columns[/bold] ({len(columns)}):")
                for col_name, col_type in columns:
                    lines.append(f"  - {col_name}  [dim]{col_type}[/dim]")
            else:
                lines.append(f"[dim]Columns unavailable: {message}[/dim]")

            if obj_type == "tables":
                success, message, count = self.db_adapter.get_row_count(obj_name)
                if success and count is not None:
                    lines.append("")
                    lines.append(f"[bold]Rows[/bold]: {count}")
                else:
                    lines.append("")
                    lines.append(f"[dim]Row count unavailable: {message}[/dim]")
        else:
            # Procedures / functions: show creation SQL as static info
            success, message, creation_sql = (
                self.db_adapter.get_object_creation_sql(obj_name, obj_type)
            )
            if success and creation_sql:
                lines.append("[bold]Definition[/bold]:")
                lines.append(creation_sql)
            else:
                lines.append(f"[dim]Definition unavailable: {message}[/dim]")

        details_area.text = "\n".join(lines)

    def _open_action_menu(self, obj_name: str, obj_type: str) -> None:
        """Push the action menu modal for the given object."""
        actions = get_available_actions(obj_type)
        modal = ObjectActionModal(obj_name, obj_type, actions)

        def _on_action(result: ObjectAction | None) -> None:
            if result is None:
                return
            # Delegate to the parent modal via the app
            parent_modal = self.app.screen
            if isinstance(parent_modal, ExplorerModal):
                parent_modal._dispatch_action(obj_name, obj_type, result)

        self.app.push_screen(modal, _on_action)


class ObjectActionModal(ModalScreen[ObjectAction | None]):
    """Modal that shows the available actions for a database object."""

    DEFAULT_CSS = """
    ObjectActionModal {
        align: center middle;
    }

    .action-dialog {
        width: 50%;
        height: auto;
        max-height: 70%;
        border: round $primary;
        padding: 1 2;
    }

    .action-dialog > OptionList {
        height: auto;
        margin: 1 0 0 0;
    }

    .action-title {
        height: 1;
        content-align: center middle;
        text-style: bold;
    }

    .action-hint {
        height: 1;
        content-align: center middle;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        obj_name: str,
        obj_type: str,
        actions: list[ObjectAction],
    ):
        super().__init__()
        self.obj_name = obj_name
        self.obj_type = obj_type
        self.actions = actions

    def compose(self) -> ComposeResult:
        """Create modal layout."""
        type_label = _OBJECT_TYPE_LABELS.get(self.obj_type, self.obj_type)
        with Container(classes="action-dialog"):
            yield Static(
                f"{type_label}: {self.obj_name}",
                id="action_title",
                classes="action-title",
            )
            yield OptionList(
                *[Option(action.value) for action in self.actions],
                id="action_list",
            )
            yield Static(
                "Enter to select, Esc to cancel",
                id="action_hint",
                classes="action-hint",
            )

    def on_mount(self) -> None:
        """Focus the action list when the modal opens."""
        action_list = self.query_one("#action_list", OptionList)
        if self.actions:
            action_list.focus()

    @on(OptionList.OptionSelected, "#action_list")
    def on_action_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        """Handle selection of an action."""
        if event.option is None:
            return
        index = event.option_list.highlighted
        if index is None or index < 0 or index >= len(self.actions):
            return
        self.dismiss(self.actions[index])

    def on_key(self, event) -> None:
        """Handle Enter and Escape keys."""
        if event.key == "escape":
            event.prevent_default()
            event.stop()
            self.dismiss(None)
        elif event.key == "enter":
            action_list = self.query_one("#action_list", OptionList)
            index = action_list.highlighted
            if index is not None and 0 <= index < len(self.actions):
                event.prevent_default()
                event.stop()
                self.dismiss(self.actions[index])


class ExplorerModal(ModalScreen[str | None]):
    """Simple modal wrapper for the database explorer."""

    DEFAULT_CSS = """
    ExplorerModal {
        align: center middle;
    }

    .explorer-dialog {
        width: 90%;
        height: 80%;
    }
    """

    def __init__(
        self,
        db_adapter: DatabaseAdapter | None = None,
        mode: ExplorerMode = ExplorerMode.OBJECTS,
        on_action: Callable[[str, str, ObjectAction], None] | None = None,
    ):
        super().__init__()
        self.db_adapter = db_adapter
        self._mode = mode
        self._on_action = on_action

    def compose(self) -> ComposeResult:
        """Create modal layout."""
        with Container(classes="explorer-dialog"):
            self.explorer = Explorer(self.db_adapter, self._mode)
            yield self.explorer

    def on_mount(self) -> None:
        """Initialize the modal when mounted."""
        if self.db_adapter:
            self.explorer.set_adapter(self.db_adapter)

    def set_adapter(self, adapter: DatabaseAdapter | None) -> None:
        """Set the database adapter and refresh objects."""
        self.db_adapter = adapter
        if adapter:
            self.explorer.set_adapter(adapter)

    def _dispatch_action(
        self, obj_name: str, obj_type: str, action: ObjectAction
    ) -> None:
        """Forward a chosen action to the caller and close the modal."""
        if self._on_action is not None:
            with contextlib.suppress(Exception):
                # Defensive: never let a callback error break the modal stack
                self._on_action(obj_name, obj_type, action)
        self.dismiss(None)

    def on_key(self, event) -> None:
        """Handle key events."""
        if event.key == "escape":
            event.prevent_default()
            self.dismiss()
        elif event.key == "enter" and self._mode == ExplorerMode.DATABASES:
            # Return selected database on Enter
            event.prevent_default()
            event.stop()
            selected_db = self.selected_database
            if selected_db:
                self.dismiss(selected_db)

    @property
    def selected_database(self) -> str | None:
        """Get the currently selected database name (for databases mode)."""
        if self._mode != ExplorerMode.DATABASES:
            return None

        objects_list = self.explorer.query_one("#objects_list", OptionList)
        if objects_list.highlighted is not None and objects_list.options:
            selected_option = objects_list.options[objects_list.highlighted]
            if selected_option and selected_option.value:
                db_name, _ = selected_option.value.split("|", 1)
                return db_name
        return None

    @property
    def mode(self) -> ExplorerMode:
        """Get the current mode."""
        return self._mode

    @on(OptionList.OptionSelected, "#objects_list")
    def on_database_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle database selection in databases mode."""
        if self._mode == ExplorerMode.DATABASES and event.option and event.option.value:
            db_name, _ = event.option.value.split("|", 1)
            self.dismiss(db_name)
