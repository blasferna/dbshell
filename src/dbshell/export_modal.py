from __future__ import annotations

import contextlib
import datetime as _dt
from collections.abc import Sequence
from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Select,
    Static,
)

_EXTENSIONS = {
    "JSON": "json",
    "CSV": "csv",
    "TSV": "tsv",
    "Markdown": "md",
    "INSERT SQL": "sql",
}


class ExportModal(ModalScreen[tuple[str, str | None] | None]):
    """Modal that asks the user for an export format and destination.

    Returns a ``(format, destination)`` tuple on submit, where ``destination``
    is ``None`` for "Copy to clipboard" or an absolute path string for
    "Save to file". Dismisses with ``None`` on cancel.
    """

    DEFAULT_CSS = """
    ExportModal {
        align: center middle;
    }

    .export-dialog {
        width: 60%;
        height: auto;
        max-height: 80%;
        border: round $primary;
        padding: 1 2;
    }

    .export-title {
        height: 1;
        content-align: center middle;
        text-style: bold;
    }

    .export-field {
        height: auto;
        margin-top: 1;
    }

    .export-label {
        height: 1;
        color: $text-muted;
    }

    #format_select {
        width: 100%;
    }

    #path_input {
        width: 100%;
    }

    .export-buttons {
        layout: horizontal;
        align: right middle;
        height: 3;
        margin-top: 1;
    }

    .export-buttons Button {
        margin-left: 1;
    }

    .export-hint {
        height: 1;
        content-align: center middle;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "submit", "Submit"),
    ]

    def __init__(self, formats: Sequence[str]):
        super().__init__()
        self.formats = list(formats)

    def compose(self) -> ComposeResult:
        with Container(classes="export-dialog"):
            yield Static("Export Results", classes="export-title")
            with Vertical(classes="export-field"):
                yield Label("Format:")
                yield Select(
                    [(fmt, fmt) for fmt in self.formats],
                    id="format_select",
                    value=self.formats[0],
                    allow_blank=False,
                )
            with Vertical(classes="export-field"):
                yield Label("Destination:")
                with RadioSet(id="destination_set"):
                    yield RadioButton(
                        "Copy to clipboard", id="dest_clipboard", value=True
                    )
                    yield RadioButton("Save to file", id="dest_file")
            with Vertical(classes="export-field", id="path_field"):
                yield Label("File path:")
                yield Input(
                    value=self._default_path(self.formats[0]),
                    placeholder="/path/to/export.<ext>",
                    id="path_input",
                )
            with Horizontal(classes="export-buttons"):
                yield Button("Cancel", id="cancel_btn", variant="default")
                yield Button("Export", id="submit_btn", variant="primary")
            yield Static(
                "Enter to export, Esc to cancel",
                classes="export-hint",
            )

    def on_mount(self) -> None:
        self.call_after_refresh(self._focus_format)

    def _focus_format(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#format_select", Select).focus()

    @staticmethod
    def _default_path(fmt: str) -> str:
        ext = _EXTENSIONS.get(fmt, "txt")
        timestamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        return str(Path.home() / f"dbshell_export_{timestamp}.{ext}")

    @on(Select.Changed, "#format_select")
    def on_format_changed(self, event: Select.Changed) -> None:
        fmt = event.value if isinstance(event.value, str) else None
        if not fmt:
            return
        path_input = self.query_one("#path_input", Input)
        current = path_input.value
        suffix = Path(current).suffix
        if suffix and suffix.lstrip(".") in _EXTENSIONS.values():
            new_suffix = "." + _EXTENSIONS[fmt]
            path_input.value = str(Path(current).with_suffix(new_suffix))
        else:
            path_input.value = self._default_path(fmt)

    @on(RadioSet.Changed, "#destination_set")
    def on_destination_changed(self, event: RadioSet.Changed) -> None:
        path_field = self.query_one("#path_field")
        path_field.display = event.pressed.id == "dest_file"

    @on(Button.Pressed, "#cancel_btn")
    def on_cancel_pressed(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#submit_btn")
    def on_submit_pressed(self) -> None:
        self._submit()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        self._submit()

    def _submit(self) -> None:
        select = self.query_one("#format_select", Select)
        fmt = select.value if isinstance(select.value, str) else None
        if not fmt:
            return

        destination_set = self.query_one("#destination_set", RadioSet)
        pressed = destination_set.pressed_button
        if pressed is None or pressed.id == "dest_clipboard":
            self.dismiss((fmt, None))
            return

        path = self.query_one("#path_input", Input).value.strip()
        if not path:
            return
        self.dismiss((fmt, path))
