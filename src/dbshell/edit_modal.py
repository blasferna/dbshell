"""Modal screen for editing an existing record or adding a new one."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Static

from dbshell.database import DatabaseAdapter


def _format_value_for_input(value: object) -> str:
    """Render a cell value for editing in an Input widget."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


class RecordEditModal(ModalScreen[bool | None]):
    """Edit an existing record, or add a new one, one Input per column.

    Each editable column has an Input plus a "NULL" Checkbox so the user
    can explicitly choose to write the value as ``NULL`` (the input is
    disabled while the box is checked). In edit mode (the default),
    primary key columns are shown read-only and used to build the
    ``WHERE`` clause of an ``UPDATE``. In add mode (``is_new=True``),
    every column - including primary keys - is editable, and the form
    builds an ``INSERT`` instead; primary-key columns start with NULL
    ticked so auto-increment columns can generate their own value.
    Returns ``True`` on a successful save, ``False`` if the user
    cancelled, or ``None`` if the modal was dismissed without an
    explicit choice.
    """

    DEFAULT_CSS = """
    RecordEditModal {
        align: center middle;
    }

    .edit-dialog {
        width: 60%;
        height: 80%;
        min-height: 12;
        max-height: 40;
        border: round $primary;
        padding: 0 1;
    }

    .edit-title {
        height: 1;
        content-align: center middle;
        text-style: bold;
        margin: 0;
    }

    .edit-subtitle {
        height: 1;
        content-align: center middle;
        color: $text-muted;
        margin: 0 0 1 0;
    }

    .edit-form {
        height: 1fr;
        min-height: 3;
        padding: 0 1;
    }

    .field-row {
        height: 1;
        layout: horizontal;
        margin: 0;
    }

    .field-label {
        width: auto;
        min-width: 18;
        content-align: right middle;
        padding-right: 1;
        color: $text;
        text-style: bold;
    }

    .field-input {
        width: 1fr;
        height: 1;
    }

    .field-null {
        width: auto;
        height: 1;
        margin: 0 0 0 1;
    }

    .field-null Checkbox {
        background: $boost;
    }

    .field-readonly {
        width: 1fr;
        height: 1;
        content-align: left middle;
        color: $text-muted;
        padding: 0 1;
        background: $boost;
    }

    .pk-marker {
        color: $warning;
    }

    .status-row {
        height: 0;
        margin: 0;
        padding: 0;
    }

    .edit-status {
        height: 1;
        color: $error;
        margin: 0;
        padding: 0 1;
    }

    .edit-status.success {
        color: $success;
    }

    .button-row {
        height: 1;
        align-horizontal: center;
        margin: 1 0 0 0;
        padding: 0;
    }

    .button-row > Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    def __init__(
        self,
        adapter: DatabaseAdapter,
        table: str,
        columns: list[str],
        values: list[object],
        primary_keys: list[str],
        *,
        is_new: bool = False,
    ) -> None:
        super().__init__()
        self.adapter = adapter
        self.table = table
        self.columns = columns
        self.values = values
        self.primary_keys = primary_keys
        self.is_new = is_new

        self._inputs: dict[str, Input] = {}
        self._null_boxes: dict[str, Checkbox] = {}
        self._read_only: dict[str, str] = {}
        self._labels: list[Static] = []
        self._status_widget: Static | None = None

    def compose(self) -> ComposeResult:
        with Vertical(classes="edit-dialog"):
            quoted = self.adapter.quote_identifier(self.table)
            title = "Add record" if self.is_new else "Edit record"
            yield Static(f"{title} — {quoted}", classes="edit-title")
            if self.is_new:
                subtitle = (
                    "Tick NULL to use the column's default or auto-increment; "
                    "leave unticked to set a value (empty string is a valid "
                    "value)."
                )
            else:
                subtitle = (
                    "Tick NULL to clear a field; leave unticked to set a value "
                    "(empty string is a valid value)."
                )
            yield Static(subtitle, classes="edit-subtitle")

            with VerticalScroll(classes="edit-form"):
                for column, value in zip(self.columns, self.values, strict=False):
                    with Horizontal(classes="field-row"):
                        is_pk = column in self.primary_keys
                        label = (
                            f"[bold]{column}[/bold] [dim](PK)[/dim]"
                            if is_pk
                            else column
                        )
                        label_widget = Static(label, classes="field-label")
                        self._labels.append(label_widget)
                        yield label_widget

                        if is_pk and not self.is_new:
                            yield Static(
                                _format_value_for_input(value) or "[dim]NULL[/dim]",
                                classes="field-readonly",
                            )
                            self._read_only[column] = _format_value_for_input(value)
                        else:
                            is_null = is_pk if self.is_new else value is None
                            input_widget = Input(
                                value="" if is_null else _format_value_for_input(value),
                                id=f"input_{column}",
                                classes="field-input",
                                compact=True,
                                disabled=is_null,
                            )
                            self._inputs[column] = input_widget
                            yield input_widget
                            null_box = Checkbox(
                                "NULL",
                                value=is_null,
                                id=f"null_{column}",
                                classes="field-null",
                                compact=True,
                            )
                            self._null_boxes[column] = null_box
                            yield null_box

            with Horizontal(classes="status-row"):
                self._status_widget = Static(
                    "", classes="edit-status", id="edit_status"
                )
                yield self._status_widget

            with Horizontal(classes="button-row"):
                yield Button("Cancel", id="edit_cancel_btn", variant="default")
                save_label = "Insert" if self.is_new else "Save"
                yield Button(save_label, id="edit_save_btn", variant="primary")

    def on_mount(self) -> None:
        """Focus the first editable input and align all field labels."""
        max_text_len = 0
        for column in self.columns:
            if column in self.primary_keys:
                text_len = len(column) + len(" (PK)")
            else:
                text_len = len(column)
            if text_len > max_text_len:
                max_text_len = text_len

        # +1 accounts for the padding-right on .field-label.
        label_width = max(18, max_text_len + 1)
        for label in self._labels:
            label.styles.width = label_width

        for widget in self._inputs.values():
            if not widget.disabled:
                widget.focus()
                return

    @on(Button.Pressed, "#edit_cancel_btn")
    def on_cancel_pressed(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#edit_save_btn")
    def on_save_pressed(self) -> None:
        self.action_save()

    @on(Checkbox.Changed)
    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Toggle the corresponding input when its NULL checkbox flips."""
        checkbox = event.checkbox
        if checkbox.id is None or not checkbox.id.startswith("null_"):
            return
        column = checkbox.id[len("null_"):]
        input_widget = self._inputs.get(column)
        if input_widget is not None:
            input_widget.disabled = checkbox.value

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_save(self) -> None:
        """Validate the form and execute the INSERT or UPDATE."""
        if not self._inputs:
            self._show_status("No editable fields.", success=False)
            return

        if not self.is_new and not self.primary_keys:
            self._show_status(
                "Cannot edit: no primary key on this table.", success=False
            )
            return

        if self._status_widget is not None:
            self._status_widget.update("")
            self._status_widget.set_class(False, "success")

        placeholder = self.adapter.param_placeholder

        if self.is_new:
            self._save_insert(placeholder)
            return

        # Read edited values (use original for PKs).
        new_values: dict[str, object] = dict(
            zip(self.columns, self.values, strict=False)
        )

        # Build a parameterized UPDATE: NULL is decided by the checkbox, and
        # the input content is bound as-is otherwise (so an empty string
        # stays an empty string, distinct from NULL).
        assignments: list[str] = []
        params: list[object] = []
        for column, input_widget in self._inputs.items():
            null_box = self._null_boxes.get(column)
            is_null = null_box.value if null_box is not None else False
            quoted_col = self.adapter.quote_identifier(column)
            if is_null:
                assignments.append(f"{quoted_col} = NULL")
                new_values[column] = None
            else:
                raw = input_widget.value
                assignments.append(f"{quoted_col} = {placeholder}")
                params.append(raw)
                new_values[column] = raw

        where_parts: list[str] = []
        for pk in self.primary_keys:
            quoted_pk = self.adapter.quote_identifier(pk)
            original = new_values.get(pk)
            if original is None or original == "":
                self._show_status(
                    f"Primary key '{pk}' has no value; cannot build WHERE.",
                    success=False,
                )
                return
            where_parts.append(f"{quoted_pk} = {placeholder}")
            params.append(original)

        quoted_table = self.adapter.quote_identifier(self.table)
        sql = (
            f"UPDATE {quoted_table} SET {', '.join(assignments)} "
            f"WHERE {' AND '.join(where_parts)};"
        )

        # Execute via the adapter so behaviour matches the manual F8 path.
        success, message, _, _ = self.adapter.execute_query(sql, params)
        if not success:
            self._show_status(message, success=False)
            return

        self._show_status("Row updated successfully.", success=True)
        self.dismiss(True)

    def _save_insert(self, placeholder: str) -> None:
        """Build and execute a parameterized INSERT from the form inputs."""
        quoted_columns: list[str] = []
        params: list[object] = []
        for column, input_widget in self._inputs.items():
            null_box = self._null_boxes.get(column)
            is_null = null_box.value if null_box is not None else False
            quoted_columns.append(self.adapter.quote_identifier(column))
            params.append(None if is_null else input_widget.value)

        quoted_table = self.adapter.quote_identifier(self.table)
        placeholders = ", ".join([placeholder] * len(quoted_columns))
        sql = (
            f"INSERT INTO {quoted_table} ({', '.join(quoted_columns)}) "
            f"VALUES ({placeholders});"
        )

        success, message, _, _ = self.adapter.execute_query(sql, params)
        if not success:
            self._show_status(message, success=False)
            return

        self._show_status("Row inserted successfully.", success=True)
        self.dismiss(True)

    def _show_status(self, text: str, *, success: bool) -> None:
        if self._status_widget is None:
            return
        self._status_widget.update(text)
        self._status_widget.set_class(success, "success")
        status_row = self._status_widget.parent
        if status_row is not None:
            status_row.styles.height = 1 if text else 0
