""" 
SQL Context Analysis Module.

This module provides context detection for SQL queries, identifying where
the cursor is and what type of suggestions are appropriate.
"""

import re
from dataclasses import dataclass, field
from enum import Enum, auto


class ContextType(Enum):
    """Types of SQL contexts for autocompletion."""
    
    UNKNOWN = auto()
    STATEMENT_START = auto()  # Beginning of statement, suggest keywords
    SELECT_COLUMNS = auto()   # After SELECT, before FROM
    FROM_TABLES = auto()      # After FROM/JOIN, suggest tables
    WHERE_CONDITION = auto()  # After WHERE, suggest columns
    ON_CONDITION = auto()     # After ON in JOIN, suggest columns
    ORDER_BY = auto()         # After ORDER BY, suggest columns
    GROUP_BY = auto()         # After GROUP BY, suggest columns
    HAVING = auto()           # After HAVING, suggest columns
    INSERT_TABLE = auto()     # After INSERT INTO, suggest tables
    INSERT_COLUMNS = auto()   # Inside INSERT column list
    INSERT_VALUES = auto()    # Inside VALUES clause - hide suggestions
    UPDATE_TABLE = auto()     # After UPDATE, suggest tables
    UPDATE_SET = auto()       # After SET in UPDATE, suggest columns
    DELETE_FROM = auto()      # After DELETE FROM, suggest tables
    QUALIFIED_COLUMN = auto() # After table.or alias. - suggest columns
    STRING_LITERAL = auto()   # Inside string - hide suggestions
    COMMENT = auto()          # Inside comment - hide suggestions
    AFTER_SEMICOLON = auto()  # After statement end - suggest keywords


@dataclass
class TableReference:
    """Represents a table reference with optional alias."""
    
    name: str
    alias: str | None = None
    
    @property
    def identifier(self) -> str:
        """Return the identifier to use (alias if available, else name)."""
        return self.alias if self.alias else self.name


@dataclass
class SQLContext:
    """Holds the parsed context of an SQL query at cursor position."""
    
    context_type: ContextType = ContextType.UNKNOWN
    tables: list[TableReference] = field(default_factory=list)
    current_table: str | None = None  # For qualified column context
    partial_text: str = ""  # Text being typed at cursor
    cursor_line: int = 0
    cursor_col: int = 0
    
    def get_table_by_ref(self, ref: str) -> str | None:
        """Get actual table name from a reference (table name or alias)."""
        for table in self.tables:
            if table.alias == ref or table.name == ref:
                return table.name
        return None
    
    def get_all_identifiers(self) -> list[str]:
        """Get all table identifiers (names and aliases)."""
        identifiers = []
        for table in self.tables:
            identifiers.append(table.name)
            if table.alias:
                identifiers.append(table.alias)
        return identifiers


class SQLContextAnalyzer:
    """Analyzes SQL text to determine the current context at cursor position."""
    
    # Patterns for different SQL contexts
    _PATTERNS = {
        'from_join': re.compile(
            r'\b(?:FROM|JOIN)\s+(\w+)(?:\s+(?:AS\s+)?(\w+))?\s*',
            re.IGNORECASE
        ),
        'update': re.compile(
            r'\bUPDATE\s+(\w+)(?:\s+(?:AS\s+)?(\w+))?\s*',
            re.IGNORECASE
        ),
        'insert_into': re.compile(
            r'\bINSERT\s+INTO\s+(\w+)\s*',
            re.IGNORECASE
        ),
        'delete_from': re.compile(
            r'\bDELETE\s+FROM\s+(\w+)(?:\s+(?:AS\s+)?(\w+))?\s*',
            re.IGNORECASE
        ),
    }
    
    def analyze(self, text: str, cursor_position: tuple[int, int]) -> SQLContext:
        """
        Analyze the SQL text and determine context at cursor position.
        
        Args:
            text: The full SQL text
            cursor_position: (line, column) tuple for cursor position
            
        Returns:
            SQLContext with determined context type and relevant info
        """
        cursor_line, cursor_col = cursor_position
        
        context = SQLContext(
            cursor_line=cursor_line,
            cursor_col=cursor_col,
        )
        
        # Get text before cursor
        lines = text.split('\n')
        if cursor_line >= len(lines):
            return context
        
        text_before_cursor = (
            '\n'.join(lines[:cursor_line]) + '\n' + lines[cursor_line][:cursor_col]
        )
        current_line = lines[cursor_line]
        
        # Extract partial text being typed
        context.partial_text = self._get_partial_word(current_line, cursor_col)
        
        # Parse table references from the query
        context.tables = self._extract_tables(text)
        
        # Check for contexts that should hide suggestions first
        if self._is_in_string(text_before_cursor, current_line, cursor_col):
            context.context_type = ContextType.STRING_LITERAL
            return context
        
        if self._is_in_comment(text_before_cursor, current_line, cursor_col):
            context.context_type = ContextType.COMMENT
            return context
        
        if self._is_in_values_clause(text_before_cursor):
            context.context_type = ContextType.INSERT_VALUES
            return context
        
        # Check for qualified column context (table.column or alias.column)
        qualified = self._check_qualified_column(current_line, cursor_col, context)
        if qualified:
            context.context_type = ContextType.QUALIFIED_COLUMN
            context.current_table = qualified
            return context
        
        # Determine context based on SQL structure
        context.context_type = self._determine_context(text_before_cursor, text)
        
        return context
    
    def _get_partial_word(self, line: str, cursor_col: int) -> str:
        """Extract the partial word being typed at cursor."""
        if cursor_col > len(line):
            cursor_col = len(line)
        
        start = cursor_col
        while start > 0 and (line[start - 1].isalnum() or line[start - 1] == '_'):
            start -= 1
        
        return line[start:cursor_col]
    
    def _extract_tables(self, text: str) -> list[TableReference]:
        """Extract all table references from the SQL text."""
        tables = []
        seen = set()
        
        # Match FROM and JOIN tables
        for match in self._PATTERNS['from_join'].finditer(text):
            table_name = match.group(1)
            alias = match.group(2)
            if table_name not in seen:
                tables.append(TableReference(name=table_name, alias=alias))
                seen.add(table_name)
        
        # Match UPDATE tables
        for match in self._PATTERNS['update'].finditer(text):
            table_name = match.group(1)
            alias = match.group(2)
            if table_name not in seen:
                tables.append(TableReference(name=table_name, alias=alias))
                seen.add(table_name)
        
        # Match INSERT INTO tables
        for match in self._PATTERNS['insert_into'].finditer(text):
            table_name = match.group(1)
            if table_name not in seen:
                tables.append(TableReference(name=table_name))
                seen.add(table_name)
        
        # Match DELETE FROM tables
        for match in self._PATTERNS['delete_from'].finditer(text):
            table_name = match.group(1)
            alias = match.group(2)
            if table_name not in seen:
                tables.append(TableReference(name=table_name, alias=alias))
                seen.add(table_name)
        
        return tables
    
    def _is_in_string(
        self, text_before: str, current_line: str, cursor_col: int
    ) -> bool:
        """Check if cursor is inside a string literal."""
        # Count quotes on current line before cursor
        line_before = current_line[:cursor_col]
        single_quotes = 0
        double_quotes = 0
        
        i = 0
        while i < len(line_before):
            char = line_before[i]
            # Check for escape sequences
            if char == '\\' and i + 1 < len(line_before):
                i += 2
                continue
            if char == "'" :
                single_quotes += 1
            elif char == '"':
                double_quotes += 1
            i += 1
        
        return (single_quotes % 2 == 1) or (double_quotes % 2 == 1)
    
    def _is_in_comment(
        self, text_before: str, current_line: str, cursor_col: int
    ) -> bool:
        """Check if cursor is inside a comment."""
        line_before = current_line[:cursor_col]
        
        # Check for single-line comment (--)
        if '--' in line_before:
            comment_pos = line_before.find('--')
            if cursor_col > comment_pos:
                return True
        
        # Check for multi-line comment (/* */)
        last_open = text_before.rfind('/*')
        last_close = text_before.rfind('*/')
        
        return last_open > last_close
    
    def _is_in_values_clause(self, text_before: str) -> bool:
        """Check if cursor is inside a VALUES clause."""
        upper_text = text_before.upper()
        
        if 'INSERT' not in upper_text or 'VALUES' not in upper_text:
            return False
        
        values_pos = upper_text.rfind('VALUES')
        after_values = text_before[values_pos + 6:]
        
        # Count parentheses
        paren_count = 0
        for char in after_values:
            if char == '(':
                paren_count += 1
            elif char == ')':
                paren_count -= 1
        
        return paren_count > 0
    
    def _check_qualified_column(
        self, 
        line: str, 
        cursor_col: int, 
        context: SQLContext
    ) -> str | None:
        """
        Check if cursor is after a table.or alias. prefix.
        
        Returns the actual table name if in qualified column context, None otherwise.
        """
        if cursor_col < 2:
            return None
        
        # Look backwards for a dot
        col = cursor_col - 1
        while col >= 0 and (line[col].isalnum() or line[col] == '_'):
            col -= 1
        
        if col < 1 or line[col] != '.':
            return None
        
        # Find the table/alias name before the dot
        dot_pos = col
        col -= 1
        while col >= 0 and (line[col].isalnum() or line[col] == '_'):
            col -= 1
        
        table_ref = line[col + 1:dot_pos]
        
        if not table_ref:
            return None
        
        # Resolve to actual table name
        return context.get_table_by_ref(table_ref)
    
    def _determine_context(self, text_before: str, full_text: str) -> ContextType:
        """Determine the SQL context based on text before cursor."""
        upper_text = text_before.upper().strip()
        
        # Empty or just whitespace
        if not upper_text:
            return ContextType.STATEMENT_START
        
        # Check if after semicolon with no new statement
        if ';' in text_before:
            after_semi = text_before[text_before.rfind(';') + 1:].strip()
            if not after_semi:
                return ContextType.STATEMENT_START
            # There's content after semicolon, analyze that instead
            upper_text = after_semi.upper().strip()
            if not upper_text:
                return ContextType.STATEMENT_START
        
        # Find the last significant keyword
        keywords_positions = []
        
        for keyword, ctx_type in [
            ('SELECT', ContextType.SELECT_COLUMNS),
            ('FROM', ContextType.FROM_TABLES),
            ('JOIN', ContextType.FROM_TABLES),
            ('WHERE', ContextType.WHERE_CONDITION),
            ('AND', ContextType.WHERE_CONDITION),
            ('OR', ContextType.WHERE_CONDITION),
            ('ON', ContextType.ON_CONDITION),
            ('ORDER BY', ContextType.ORDER_BY),
            ('GROUP BY', ContextType.GROUP_BY),
            ('HAVING', ContextType.HAVING),
            ('SET', ContextType.UPDATE_SET),
            ('INSERT INTO', ContextType.INSERT_TABLE),
            ('UPDATE', ContextType.UPDATE_TABLE),
            ('DELETE FROM', ContextType.DELETE_FROM),
        ]:
            # Find all occurrences
            pos = upper_text.rfind(keyword)
            if pos != -1:
                keywords_positions.append((pos + len(keyword), keyword, ctx_type))
        
        if not keywords_positions:
            return ContextType.STATEMENT_START
        
        # Get the most recent keyword (highest position)
        keywords_positions.sort(reverse=True)
        _, last_keyword, initial_ctx = keywords_positions[0]
        
        # Special handling for context transitions
        if initial_ctx == ContextType.SELECT_COLUMNS and (
            'FROM' in upper_text[upper_text.rfind('SELECT'):]
        ):
            # We're past the SELECT columns, check what context we're in
            from_pos = upper_text.rfind('FROM')
            remaining = upper_text[from_pos + 4:].strip()

            if not remaining:
                return ContextType.FROM_TABLES

            # Check for subsequent clauses
            for kw, ctx in [
                ('WHERE', ContextType.WHERE_CONDITION),
                ('ORDER BY', ContextType.ORDER_BY),
                ('GROUP BY', ContextType.GROUP_BY),
                ('HAVING', ContextType.HAVING),
                ('JOIN', ContextType.FROM_TABLES),
                ('ON', ContextType.ON_CONDITION),
            ]:
                if kw in remaining.upper():
                    kw_pos = remaining.upper().rfind(kw)
                    after_kw = remaining[kw_pos + len(kw):].strip()
                    if not after_kw or not self._looks_like_complete_clause(
                        after_kw, kw
                    ):
                        return ctx

            # Default: we're in FROM clause listing tables
            return ContextType.FROM_TABLES
        
        if initial_ctx == ContextType.INSERT_TABLE:
            # Check if we're past the table name into columns
            insert_pos = upper_text.rfind('INSERT INTO')
            after_insert = upper_text[insert_pos + 11:].strip()
            
            if '(' in after_insert:
                # Inside column list
                paren_depth = after_insert.count('(') - after_insert.count(')')
                if paren_depth > 0:
                    return ContextType.INSERT_COLUMNS
            elif after_insert:
                # Table name typed but no parens yet
                words = after_insert.split()
                if len(words) >= 1:
                    # Has table name, waiting for columns or VALUES
                    return ContextType.STATEMENT_START
            
            return ContextType.INSERT_TABLE
        
        if initial_ctx == ContextType.UPDATE_TABLE:
            # Check if we're past the table name into SET
            if 'SET' in upper_text[upper_text.rfind('UPDATE'):]:
                return ContextType.UPDATE_SET
            return ContextType.UPDATE_TABLE
        
        if initial_ctx == ContextType.DELETE_FROM:
            # Check if we're past the table into WHERE
            if 'WHERE' in upper_text[upper_text.rfind('DELETE'):]:
                return ContextType.WHERE_CONDITION
            return ContextType.DELETE_FROM
        
        return initial_ctx
    
    def _looks_like_complete_clause(self, text: str, clause_type: str) -> bool:
        """Check if text looks like a complete clause (has content after keyword)."""
        text = text.strip()
        if not text:
            return False
        
        # If there's meaningful content, the clause might be complete
        words = text.split()
        if len(words) >= 1:
            # Check if ends with operator or incomplete
            last_char = text[-1] if text else ''
            return last_char not in '=<>!,('

        return False
