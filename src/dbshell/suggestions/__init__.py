"""
Suggestions module - Modular SQL autocomplete system.

This module provides intelligent SQL autocompletion with:
- Context-aware suggestions (SELECT, FROM, WHERE, etc.)
- Table and column completion
- SQL keyword suggestions
- Configurable and extensible architecture
"""

from .completers import Completion, MemberCompleter, WordCompleter
from .context import ContextType, SQLContext
from .provider import SuggestionProvider
from .ui import SuggestionCategory, SuggestionItem

__all__ = [
    "Completion",
    "ContextType",
    "MemberCompleter",
    "SQLContext",
    "SuggestionCategory",
    "SuggestionItem",
    "SuggestionProvider",
    "WordCompleter",
]
