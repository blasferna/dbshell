"""
Suggestions module - Modular SQL autocomplete system.

This module provides intelligent SQL autocompletion with:
- Context-aware suggestions (SELECT, FROM, WHERE, etc.)
- Table and column completion
- SQL keyword suggestions
- Configurable and extensible architecture
"""

from .provider import SuggestionProvider
from .context import SQLContext, ContextType
from .ui import AutoCompleteWidget, SuggestionItem, SuggestionCategory

__all__ = [
    "SuggestionProvider",
    "SQLContext",
    "ContextType",
    "AutoCompleteWidget",
    "SuggestionItem",
    "SuggestionCategory",
]
