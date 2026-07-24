"""
Suggestions module - Modular SQL autocomplete system.

This module provides intelligent SQL autocompletion with:
- Context-aware suggestions (SELECT, FROM, WHERE, etc.)
- Table and column completion
- SQL keyword suggestions
"""

from .completers import Completion, MemberCompleter, WordCompleter
from .context import ContextType, SQLContext

__all__ = [
    "Completion",
    "ContextType",
    "MemberCompleter",
    "SQLContext",
    "WordCompleter",
]
