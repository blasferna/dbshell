"""
Autocomplete UI Components.

This module provides the visual components for displaying
SQL suggestions in a clean, categorized manner.
"""

from dataclasses import dataclass
from enum import Enum, auto

from textual.app import ComposeResult
from textual.containers import Container
from textual.content import Content
from textual.widgets import OptionList
from textual.widgets.option_list import Option


class SuggestionCategory(Enum):
    """Categories for organizing suggestions."""
    
    KEYWORD = auto()
    TABLE = auto()
    COLUMN = auto()
    FUNCTION = auto()
    ALIAS = auto()
    OTHER = auto()


@dataclass
class SuggestionItem:
    """A single suggestion item with metadata."""
    
    text: str
    category: SuggestionCategory = SuggestionCategory.OTHER
    description: str | None = None
    icon: str = ""
    
    @property
    def display_icon(self) -> str:
        """Get the icon for this suggestion based on category."""
        if self.icon:
            return self.icon
        
        icons = {
            SuggestionCategory.KEYWORD: "⌨",
            SuggestionCategory.TABLE: "▤",
            SuggestionCategory.COLUMN: "│",
            SuggestionCategory.FUNCTION: "ƒ",
            SuggestionCategory.ALIAS: "→",
            SuggestionCategory.OTHER: "•",
        }
        return icons.get(self.category, "•")


class SuggestionOption(Option):
    """Custom option class for suggestion items."""
    
    def __init__(self, item: SuggestionItem):
        self.item = item
        # Create formatted display with icon and text
        icon_style = self._get_icon_style()
        display = Content.assemble(
            (f"{item.display_icon} ", icon_style),
            item.text
        )
        super().__init__(display)
    
    def _get_icon_style(self) -> str:
        """Get the style for the icon based on category."""
        styles = {
            SuggestionCategory.KEYWORD: "bold cyan",
            SuggestionCategory.TABLE: "bold green",
            SuggestionCategory.COLUMN: "yellow",
            SuggestionCategory.FUNCTION: "bold magenta",
            SuggestionCategory.ALIAS: "dim",
            SuggestionCategory.OTHER: "dim",
        }
        return styles.get(self.item.category, "dim")
    
    @property
    def value(self) -> str:
        """Return the suggestion text."""
        return self.item.text


class AutoCompleteWidget(Container):
    """
    Modern autocomplete dropdown widget.
    
    Features:
    - Categorized suggestions with icons
    - Smooth scrolling
    - Keyboard navigation
    - Dynamic positioning
    """
    
    DEFAULT_CSS = """
    AutoCompleteWidget {
        layer: tooltips;
        display: none;
        width: auto;
        min-width: 20;
        max-width: 50;
        height: auto;
        max-height: 12;
        background: $surface;
        border: tall $primary;
        border-title-color: $text-muted;
        padding: 0;
    }
    
    AutoCompleteWidget:focus-within {
        border: tall $accent;
    }
    
    AutoCompleteWidget OptionList {
        border: none;
        background: transparent;
        height: auto;
        max-height: 10;
        scrollbar-size: 1 1;
        scrollbar-background: $surface;
        scrollbar-color: $primary-darken-2;
        scrollbar-color-hover: $primary;
        scrollbar-color-active: $primary-lighten-1;
        padding: 0;
    }
    
    AutoCompleteWidget OptionList:focus {
        border: none;
    }
    
    AutoCompleteWidget OptionList > .option-list--option {
        padding: 0 1;
    }
    
    AutoCompleteWidget OptionList > .option-list--option-highlighted {
        background: $primary 30%;
        color: $text;
    }
    
    AutoCompleteWidget .autocomplete-header {
        height: 1;
        background: $primary-background;
        color: $text-muted;
        text-style: italic;
        padding: 0 1;
    }
    """
    
    def __init__(self, id: str = "autocomplete"):
        super().__init__(id=id)
        self._option_list = OptionList()
        self._option_list.can_focus = False
        self._suggestions: list[SuggestionItem] = []
        self._target_text = ""
        self._target_cursor = (0, 0)
    
    def compose(self) -> ComposeResult:
        """Create the autocomplete layout."""
        yield self._option_list
    
    def show_suggestions(
        self, 
        suggestions: list[str], 
        position: tuple[int, int] | None = None,
        categorize: bool = True
    ) -> None:
        """
        Show suggestions in the dropdown.
        
        Args:
            suggestions: List of suggestion strings
            position: Optional (x, y) offset position
            categorize: Whether to auto-categorize suggestions
        """
        if not suggestions:
            self.hide()
            return
        
        # Reset position
        self.styles.offset = (0, 0)
        
        # Set position if provided
        if position:
            self.styles.offset = position
        
        # Convert strings to SuggestionItems with categories
        items = self._categorize_suggestions(suggestions) if categorize else [
            SuggestionItem(text=s) for s in suggestions
        ]
        
        self._suggestions = items
        
        # Clear and populate option list
        self._option_list.clear_options()
        
        for item in items:
            self._option_list.add_option(SuggestionOption(item))
        
        self.display = True
        
        if self._option_list.option_count > 0:
            self._option_list.highlighted = 0
    
    def _categorize_suggestions(self, suggestions: list[str]) -> list[SuggestionItem]:
        """Auto-categorize suggestions based on patterns."""
        from .keywords import AGGREGATE_FUNCTIONS, ALL_KEYWORDS
        
        items = []
        keywords_upper = {k.upper() for k in ALL_KEYWORDS}
        functions_upper = {f.upper() for f in AGGREGATE_FUNCTIONS}
        
        for suggestion in suggestions:
            upper = suggestion.upper()
            
            # Determine category
            if upper in functions_upper or '(' in suggestion:
                category = SuggestionCategory.FUNCTION
            elif upper in keywords_upper:
                category = SuggestionCategory.KEYWORD
            elif '.' in suggestion:
                # Qualified column (table.column)
                category = SuggestionCategory.COLUMN
            elif suggestion.startswith('t_') or suggestion.endswith('_table'):
                # Heuristic for table names
                category = SuggestionCategory.TABLE
            else:
                # Default to column for most schema objects
                category = SuggestionCategory.COLUMN
            
            items.append(SuggestionItem(text=suggestion, category=category))
        
        # Sort: keywords first, then tables, then columns, then others
        category_order = {
            SuggestionCategory.KEYWORD: 0,
            SuggestionCategory.TABLE: 1,
            SuggestionCategory.FUNCTION: 2,
            SuggestionCategory.COLUMN: 3,
            SuggestionCategory.ALIAS: 4,
            SuggestionCategory.OTHER: 5,
        }
        
        items.sort(key=lambda x: (category_order.get(x.category, 99), x.text.lower()))
        
        return items
    
    def hide(self) -> None:
        """Hide the autocomplete dropdown."""
        self.display = False
        self.styles.offset = (0, 0)
    
    def move_cursor(self, down: bool = True) -> None:
        """
        Move the highlight cursor up or down.
        
        Args:
            down: True to move down, False to move up
        """
        if not self.display or self._option_list.option_count == 0:
            return
        
        current = self._option_list.highlighted or 0
        
        if down:
            new_index = min(current + 1, self._option_list.option_count - 1)
        else:
            new_index = max(current - 1, 0)
        
        self._option_list.highlighted = new_index
    
    def get_selected_suggestion(self) -> str:
        """Get the currently highlighted suggestion text."""
        if not self.display or self._option_list.option_count == 0:
            return ""
        
        current = self._option_list.highlighted
        if current is None or current >= self._option_list.option_count:
            return ""
        
        try:
            option = self._option_list.get_option_at_index(current)
            if isinstance(option, SuggestionOption):
                return option.value
            return str(option.prompt) if option else ""
        except Exception:
            return ""
    
    def update_target_state(self, text: str, cursor_position: tuple[int, int]) -> None:
        """Update the cached target state for word boundary detection."""
        self._target_text = text
        self._target_cursor = cursor_position
    
    def get_current_word_bounds(self) -> tuple[tuple[int, int], tuple[int, int]]:
        """
        Get the start and end positions of the word at cursor.
        
        Returns:
            Tuple of ((start_line, start_col), (end_line, end_col))
        """
        cursor_line, cursor_col = self._target_cursor
        lines = self._target_text.split('\n')
        
        if cursor_line >= len(lines):
            return (cursor_line, cursor_col), (cursor_line, cursor_col)
        
        line = lines[cursor_line]
        
        # Find word start
        start_col = cursor_col
        while start_col > 0:
            char = line[start_col - 1]
            if char.isalnum() or char == '_':
                start_col -= 1
            else:
                break
        
        # Find word end
        end_col = cursor_col
        while end_col < len(line) and (line[end_col].isalnum() or line[end_col] == '_'):
            end_col += 1
        
        return (cursor_line, start_col), (cursor_line, end_col)
    
    @property
    def is_visible(self) -> bool:
        """Check if the autocomplete is currently visible."""
        return bool(self.display)
    
    @property
    def suggestion_count(self) -> int:
        """Get the number of suggestions currently shown."""
        return self._option_list.option_count
