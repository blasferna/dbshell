"""
Suggestion Provider Module.

This module provides the main interface for getting SQL suggestions
based on the current context and database schema.
"""

from typing import Protocol

from .context import ContextType, SQLContext, SQLContextAnalyzer
from .keywords import (
    AGGREGATE_FUNCTIONS,
    ALL_KEYWORDS,
    LOGICAL_KEYWORDS,
    STATEMENT_STARTERS,
)


class DatabaseConnection(Protocol):
    """Protocol for database connection interface."""
    
    def get_tables(self) -> tuple[list[str], str]:
        """Return list of table names and a message."""
        ...
    
    def get_columns(self, table_name: str) -> list[str]:
        """Return list of column names for a table."""
        ...


class SuggestionProvider:
    """
    Provides intelligent SQL suggestions based on context.
    
    This class analyzes the current SQL text and cursor position to
    provide context-appropriate suggestions including keywords, tables,
    columns, and functions.
    """
    
    def __init__(self, db_connection: DatabaseConnection):
        """
        Initialize the suggestion provider.
        
        Args:
            db_connection: Database connection implementing the protocol
        """
        self.db_connection = db_connection
        self.analyzer = SQLContextAnalyzer()
        self._table_cache: list[str] | None = None
        self._column_cache: dict[str, list[str]] = {}
    
    def get_suggestions(
        self, 
        text: str, 
        cursor_position: tuple[int, int], 
        parser=None  # Tree-sitter parser, optional
    ) -> list[str]:
        """
        Get suggestions for the current cursor position.
        
        Args:
            text: The full SQL text
            cursor_position: (line, column) tuple
            parser: Optional tree-sitter parser (for backward compatibility)
            
        Returns:
            List of suggestion strings
        """
        # Analyze the context
        context = self.analyzer.analyze(text, cursor_position)
        
        # Get suggestions based on context type
        suggestions = self._get_suggestions_for_context(context)
        
        # Filter by partial text if present
        if context.partial_text and suggestions:
            partial_lower = context.partial_text.lower()
            filtered = [
                s for s in suggestions 
                if s.lower().startswith(partial_lower)
            ]
            # Return filtered if we have matches, otherwise return all
            if filtered:
                return filtered
        
        return suggestions
    
    def _get_suggestions_for_context(self, context: SQLContext) -> list[str]:
        """Get suggestions based on the context type."""
        ctx_type = context.context_type
        
        # Contexts where we should hide suggestions
        if ctx_type in (
            ContextType.STRING_LITERAL,
            ContextType.COMMENT,
            ContextType.INSERT_VALUES,
        ):
            return []
        
        # Statement start - suggest statement keywords
        if ctx_type == ContextType.STATEMENT_START:
            return STATEMENT_STARTERS
        
        # Table contexts
        if ctx_type in (
            ContextType.FROM_TABLES,
            ContextType.INSERT_TABLE,
            ContextType.UPDATE_TABLE,
            ContextType.DELETE_FROM,
        ):
            return self._get_tables()
        
        # Column contexts
        if ctx_type in (
            ContextType.SELECT_COLUMNS,
            ContextType.WHERE_CONDITION,
            ContextType.ON_CONDITION,
            ContextType.ORDER_BY,
            ContextType.GROUP_BY,
            ContextType.HAVING,
            ContextType.UPDATE_SET,
            ContextType.INSERT_COLUMNS,
        ):
            return self._get_columns_for_context(context)
        
        # Qualified column context (table.column)
        if ctx_type == ContextType.QUALIFIED_COLUMN:
            if context.current_table:
                return self._get_table_columns(context.current_table)
            return []
        
        # Unknown - return all keywords
        return ALL_KEYWORDS
    
    def _get_tables(self) -> list[str]:
        """Get list of available tables."""
        if self._table_cache is None:
            tables, _ = self.db_connection.get_tables()
            self._table_cache = tables or []
        return self._table_cache
    
    def _get_table_columns(self, table_name: str) -> list[str]:
        """Get columns for a specific table."""
        if table_name not in self._column_cache:
            columns = self.db_connection.get_columns(table_name)
            self._column_cache[table_name] = columns or []
        return self._column_cache[table_name]
    
    def _get_columns_for_context(self, context: SQLContext) -> list[str]:
        """Get columns available in the current context."""
        all_columns = []
        
        # Get columns from all referenced tables
        for table_ref in context.tables:
            columns = self._get_table_columns(table_ref.name)
            
            # Add unqualified column names
            all_columns.extend(columns)
            
            # Add qualified column names (table.column)
            for col in columns:
                all_columns.append(f"{table_ref.name}.{col}")
                # Also add alias-qualified if available
                if table_ref.alias:
                    all_columns.append(f"{table_ref.alias}.{col}")
        
        # Add aggregate functions for SELECT, HAVING contexts
        if context.context_type in (
            ContextType.SELECT_COLUMNS,
            ContextType.HAVING,
        ):
            all_columns.extend(AGGREGATE_FUNCTIONS)
        
        # Add logical keywords for WHERE, HAVING, ON contexts
        if context.context_type in (
            ContextType.WHERE_CONDITION,
            ContextType.HAVING,
            ContextType.ON_CONDITION,
        ):
            all_columns.extend(LOGICAL_KEYWORDS)
        
        # Add clause keywords that might follow
        if context.context_type == ContextType.SELECT_COLUMNS:
            all_columns.extend(['FROM', 'AS', 'DISTINCT'])
        elif context.context_type == ContextType.WHERE_CONDITION:
            all_columns.extend(['ORDER BY', 'GROUP BY', 'LIMIT'])
        if context.context_type == ContextType.FROM_TABLES:
            all_columns.extend([
                'WHERE', 'JOIN', 'LEFT JOIN', 'RIGHT JOIN', 
                'INNER JOIN', 'ON', 'AS'
            ])
        
        # Remove duplicates while preserving order
        seen = set()
        unique_columns = []
        for col in all_columns:
            if col not in seen:
                seen.add(col)
                unique_columns.append(col)
        
        return unique_columns
    
    def invalidate_cache(self):
        """Invalidate the cached table and column data."""
        self._table_cache = None
        self._column_cache.clear()
    
    def refresh_schema(self):
        """Refresh the schema cache from the database."""
        self.invalidate_cache()
        # Pre-populate table cache
        self._get_tables()
