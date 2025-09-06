import re

from tree_sitter import Parser

SQL_KEYWORDS = [
    "SELECT",
    "FROM",
    "WHERE",
    "INSERT",
    "INTO",
    "VALUES",
    "UPDATE",
    "SET",
    "DELETE",
    "CREATE",
    "TABLE",
    "DATABASE",
    "DROP",
    "ALTER",
    "ADD",
    "COLUMN",
    "INDEX",
    "JOIN",
    "INNER",
    "LEFT",
    "RIGHT",
    "OUTER",
    "ON",
    "GROUP",
    "BY",
    "ORDER",
    "HAVING",
    "LIMIT",
    "AS",
    "DISTINCT",
    "COUNT",
    "SUM",
    "AVG",
    "MIN",
    "MAX",
    "AND",
    "OR",
    "NOT",
    "NULL",
    "IS",
    "TRUE",
    "FALSE",
    "VARCHAR",
    "INT",
    "TEXT",
    "DATE",
    "DATETIME",
]


class SuggestionProvider:
    def __init__(self, db_connection):
        self.db_connection = db_connection

    def get_suggestions(self, text: str, cursor_position: tuple, parser: Parser) -> list[str]:
        # Check if we should hide autocomplete
        if self._should_hide_autocomplete(text, cursor_position):
            return []

        tree = parser.parse(bytes(text, "utf8"))
        point = (cursor_position[0], cursor_position[1])

        leaf = tree.root_node.descendant_for_point_range(point, point)

        if not leaf:
            return SQL_KEYWORDS

        # Parse the query to extract table aliases and identify context
        query_info = self._parse_query_context(text, tree)
        print(f"Query info: {query_info}")

        # Check for qualified column references (table.column or alias.column)
        qualified_column_suggestion = self._check_qualified_column_context(
            text, cursor_position, query_info
        )
        if qualified_column_suggestion:
            return qualified_column_suggestion

        insert_suggestion = self._check_insert_context(text, cursor_position)
        if insert_suggestion:
            return insert_suggestion

        update_suggestion = self._check_update_context(text, cursor_position)
        if update_suggestion:
            return update_suggestion

        delete_suggestion = self._check_delete_context(text, cursor_position)
        if delete_suggestion:
            return delete_suggestion

        # Handle the case where we get the root program node or statement node
        if leaf.type in ["program", "statement"]:
            # Check for WHERE, ON, ORDER BY, GROUP BY contexts first
            if self._is_in_where_context(text, cursor_position, tree):
                columns = self._get_available_columns(query_info["tables"])
                return columns

            # Check for SELECT context
            if self._is_in_select_context(text, cursor_position, tree):
                columns = self._get_available_columns(query_info["tables"])
                return columns

            # Check if we're after a FROM keyword for table suggestions
            if self._is_after_from_keyword(text, cursor_position):
                tables, _ = self.db_connection.get_tables()
                return tables

            return SQL_KEYWORDS

        parent = leaf.parent

        # Check for column suggestions after SELECT or after comma in SELECT
        if self._is_in_select_context(text, cursor_position, tree):
            columns = self._get_available_columns(query_info["tables"])
            if leaf.type == "identifier":
                current_text = leaf.text.decode().lower()
                # Filter columns that start with the current text
                filtered_columns = [
                    c for c in columns if c.lower().startswith(current_text)
                ]
                return filtered_columns if filtered_columns else columns
            return columns

        # Check for column suggestions after WHERE, ON, ORDER BY, GROUP BY
        if self._is_in_where_context(text, cursor_position, tree):
            columns = self._get_available_columns(query_info["tables"])
            if leaf.type == "identifier":
                current_text = leaf.text.decode().lower()
                # Check if it's a qualified column reference (table.column)
                if parent and parent.type == "field_reference":
                    # Get the table part
                    for child in parent.children:
                        if child.type == "identifier" and child != leaf:
                            table_ref = child.text.decode()
                            # Resolve alias to actual table name
                            actual_table = query_info["aliases"].get(
                                table_ref, table_ref
                            )
                            table_columns = self._get_table_columns(actual_table)
                            filtered_columns = [
                                c
                                for c in table_columns
                                if c.lower().startswith(current_text)
                            ]
                            return (
                                filtered_columns if filtered_columns else table_columns
                            )

                # Regular column filtering
                filtered_columns = [
                    c for c in columns if c.lower().startswith(current_text)
                ]
                return filtered_columns if filtered_columns else columns
            return columns

        # Check if we're in a table name context (object_reference with identifier)
        if parent and parent.type == "object_reference" and leaf.type == "identifier":
            tables, _ = self.db_connection.get_tables()
            current_text = leaf.text.decode().lower()
            # Filter tables that start with the current text
            filtered_tables = [t for t in tables if t.lower().startswith(current_text)]
            # Always return filtered results, even if empty
            return filtered_tables

        # Check if we're directly after a FROM keyword
        if self._is_after_from_keyword(text, cursor_position):
            tables, _ = self.db_connection.get_tables()
            # If we're on an identifier, filter by partial match
            if leaf.type == "identifier":
                current_text = leaf.text.decode().lower()
                return [t for t in tables if t.lower().startswith(current_text)]
            return tables

        # Handle partial keywords
        if leaf.type == "identifier":
            current_word = leaf.text.decode().lower()
            matching_keywords = [
                kw for kw in SQL_KEYWORDS if kw.lower().startswith(current_word)
            ]
            if matching_keywords:
                return matching_keywords

        return SQL_KEYWORDS

    def _check_insert_context(self, text: str, cursor_position: tuple) -> list[str]:
        """Check if we're in an INSERT INTO context and provide appropriate suggestions."""
        text_before_cursor = text[: cursor_position[1]].upper()

        # Check for INSERT INTO pattern
        if "INSERT" not in text_before_cursor:
            return []

        # Find the last INSERT position
        insert_pos = text_before_cursor.rfind("INSERT")
        text_after_insert = text_before_cursor[insert_pos:]

        # Pattern 1: INSERT INTO <table_name>
        if "INTO" in text_after_insert:
            into_pos = text_after_insert.find("INTO")
            text_after_into = text_after_insert[into_pos + 4 :].strip()

            # If we have just "INSERT INTO " suggest tables
            if not text_after_into or text_after_into.split()[0] == text_after_into:
                tables, _ = self.db_connection.get_tables()
                # Filter if we have partial table name
                if text_after_into:
                    current_text = text_after_into.lower()
                    filtered_tables = [
                        t for t in tables if t.lower().startswith(current_text)
                    ]
                    return filtered_tables if filtered_tables else tables
                return tables

            # Pattern 2: INSERT INTO table_name ( <columns>
            words = text_after_into.split()
            if len(words) >= 1:
                table_name = words[0]

                # Check if we're inside parentheses for column list
                remaining_text = " ".join(words[1:]) if len(words) > 1 else ""

                # Count parentheses to see if we're inside column definition
                paren_count = remaining_text.count("(") - remaining_text.count(")")

                if paren_count > 0:  # We're inside parentheses
                    # Get table columns
                    columns = self._get_table_columns(table_name)

                    # Check if we're typing a partial column name
                    cursor_line, cursor_col = cursor_position
                    lines = text.split("\n")
                    if cursor_line < len(lines):
                        current_line = lines[cursor_line]
                        # Find the current word being typed
                        start_col = cursor_col
                        while start_col > 0 and (
                            current_line[start_col - 1].isalnum()
                            or current_line[start_col - 1] == "_"
                        ):
                            start_col -= 1

                        if start_col < cursor_col:
                            current_word = current_line[start_col:cursor_col].lower()
                            filtered_columns = [
                                c for c in columns if c.lower().startswith(current_word)
                            ]
                            return filtered_columns if filtered_columns else columns

                    return columns

        return []

    def _check_update_context(self, text: str, cursor_position: tuple) -> list[str]:
        """Check if we're in an UPDATE context and provide appropriate suggestions."""
        text_before_cursor = text[: cursor_position[1]].upper()

        # Check for UPDATE pattern
        if "UPDATE" not in text_before_cursor:
            return []

        # Find the last UPDATE position
        update_pos = text_before_cursor.rfind("UPDATE")
        text_after_update = text_before_cursor[
            update_pos + 6 :
        ].strip()  # 6 = len('UPDATE')

        # Pattern 1: UPDATE <table_name>
        if "SET" not in text_after_update:
            words = text_after_update.split()

            # If no table name yet or typing partial table name
            if len(words) == 0 or (
                len(words) == 1 and not text_after_update.endswith(" ")
            ):
                tables, _ = self.db_connection.get_tables()
                if len(words) == 1:
                    current_text = words[0].lower()
                    filtered_tables = [
                        t for t in tables if t.lower().startswith(current_text)
                    ]
                    return filtered_tables if filtered_tables else tables
                return tables

        # Pattern 2: UPDATE table_name SET <columns>
        else:
            set_pos = text_after_update.find("SET")
            text_before_set = text_after_update[:set_pos].strip()
            text_after_set = text_after_update[set_pos + 3 :].strip()  # 3 = len('SET')

            if text_before_set:
                table_name = text_before_set.split()[0]

                # Get table columns for SET clause
                columns = self._get_table_columns(table_name)

                # Check if we're typing a partial column name
                cursor_line, cursor_col = cursor_position
                lines = text.split("\n")
                if cursor_line < len(lines):
                    current_line = lines[cursor_line]
                    # Find the current word being typed
                    start_col = cursor_col
                    while start_col > 0 and (
                        current_line[start_col - 1].isalnum()
                        or current_line[start_col - 1] == "_"
                    ):
                        start_col -= 1

                    if start_col < cursor_col:
                        current_word = current_line[start_col:cursor_col].lower()
                        filtered_columns = [
                            c for c in columns if c.lower().startswith(current_word)
                        ]
                        return filtered_columns if filtered_columns else columns

                return columns

        return []

    def _check_delete_context(self, text: str, cursor_position: tuple) -> list[str]:
        """Check if we're in a DELETE FROM context and provide appropriate suggestions."""
        text_before_cursor = text[: cursor_position[1]].upper()

        # Check for DELETE FROM pattern
        if "DELETE" not in text_before_cursor:
            return []

        # Find the last DELETE position
        delete_pos = text_before_cursor.rfind("DELETE")
        text_after_delete = text_before_cursor[
            delete_pos + 6 :
        ].strip()  # 6 = len('DELETE')

        # Pattern: DELETE FROM <table_name>
        if "FROM" in text_after_delete:
            from_pos = text_after_delete.find("FROM")
            text_after_from = text_after_delete[
                from_pos + 4 :
            ].strip()  # 4 = len('FROM')

            # If we have just "DELETE FROM " suggest tables
            words = text_after_from.split()
            if len(words) == 0 or (
                len(words) == 1 and not text_after_from.endswith(" ")
            ):
                tables, _ = self.db_connection.get_tables()
                if len(words) == 1:
                    current_text = words[0].lower()
                    filtered_tables = [
                        t for t in tables if t.lower().startswith(current_text)
                    ]
                    return filtered_tables if filtered_tables else tables
                return tables

        return []

    def _check_qualified_column_context(
        self, text: str, cursor_position: tuple, query_info: dict
    ) -> list[str]:
        """Check if we're in a qualified column context (table.column or alias.column)."""
        cursor_line, cursor_col = cursor_position
        lines = text.split("\n")

        if cursor_line >= len(lines):
            return []

        current_line = lines[cursor_line]

        # Look backwards from cursor to find if there's a dot followed by identifier
        dot_pos = -1
        for i in range(cursor_col - 1, -1, -1):
            if current_line[i] == ".":
                dot_pos = i
                break
            elif not (current_line[i].isalnum() or current_line[i] == "_"):
                break

        if dot_pos == -1:
            return []

        # Find the identifier before the dot (table name or alias)
        table_start = dot_pos - 1
        while table_start >= 0 and (
            current_line[table_start].isalnum() or current_line[table_start] == "_"
        ):
            table_start -= 1
        table_start += 1

        if table_start >= dot_pos:
            return []

        table_ref = current_line[table_start:dot_pos]

        # Get partial column name after dot (if any)
        column_start = dot_pos + 1
        column_partial = current_line[column_start:cursor_col]

        print(
            f"Qualified column context: table_ref='{table_ref}', partial='{column_partial}'"
        )

        # Resolve table reference to actual table name
        actual_table = query_info["aliases"].get(table_ref, table_ref)

        if actual_table:
            columns = self._get_table_columns(actual_table)
            if column_partial:
                # Filter columns that start with the partial text
                filtered_columns = [
                    c for c in columns if c.lower().startswith(column_partial.lower())
                ]
                return filtered_columns
            return columns

        return []

    def _parse_query_context(self, text: str, tree) -> dict:
        """Parse the query to extract table names and aliases using both tree-sitter and text parsing."""
        tables = []
        aliases = {}  # alias -> table_name mapping

        # First try tree-sitter parsing
        def extract_table_info(node):
            """Recursively extract table information from tree nodes."""
            if node.type == "relation":
                # This handles FROM and JOIN relations
                table_name = None
                alias = None

                for child in node.children:
                    if child.type == "object_reference":
                        # Get the table name
                        for grandchild in child.children:
                            if grandchild.type == "identifier":
                                table_name = grandchild.text.decode()
                                break
                    elif child.type == "identifier" and table_name:
                        # This is an alias (comes after the table name)
                        alias = child.text.decode()

                if table_name:
                    tables.append(table_name)
                    if alias:
                        aliases[alias] = table_name
                    else:
                        aliases[table_name] = table_name

            # Recursively process child nodes
            for child in node.children:
                extract_table_info(child)

        # Start extraction from the root
        extract_table_info(tree.root_node)

        # Fallback: parse using regex for cases where tree-sitter fails
        if not tables:
            tables, aliases = self._parse_tables_with_regex(text)

        return {"tables": tables, "aliases": aliases}

    def _parse_tables_with_regex(self, text: str) -> tuple:
        """Parse table names and aliases using regex as fallback."""

        tables = []
        aliases = {}

        # Pattern to match FROM and JOIN clauses with optional aliases
        # Handles: FROM table, FROM table alias, FROM table AS alias
        pattern = r"(?:FROM|JOIN)\s+(\w+)(?:\s+(?:AS\s+)?(\w+))?"

        matches = re.finditer(pattern, text, re.IGNORECASE)

        for match in matches:
            table_name = match.group(1)
            alias = match.group(2)

            if table_name:
                tables.append(table_name)
                if alias:
                    aliases[alias] = table_name
                else:
                    aliases[table_name] = table_name

        return tables, aliases

    def _is_in_select_context(self, text: str, cursor_position: tuple, tree) -> bool:
        """Check if cursor is in SELECT column list context."""
        text_before_cursor = text[: cursor_position[1]].upper()

        # More robust check for SELECT context
        if "SELECT" not in text_before_cursor:
            return False

        # Find the last SELECT position
        select_pos = text_before_cursor.rfind("SELECT")

        # Check if we're between SELECT and FROM (or end of text)
        text_after_select = text_before_cursor[select_pos:]

        # If there's no FROM after the last SELECT, we're in SELECT context
        if "FROM" not in text_after_select:
            return True

        # If there's a FROM, check if cursor is before it
        from_pos = text_after_select.find("FROM")
        cursor_relative_pos = len(text_before_cursor) - select_pos

        return cursor_relative_pos < from_pos

    def _is_in_where_context(self, text: str, cursor_position: tuple, tree) -> bool:
        """Check if cursor is in WHERE, ON, ORDER BY, or GROUP BY context."""
        text_before_cursor = text[: cursor_position[1]].upper()

        # Check for WHERE, ON, ORDER BY, GROUP BY contexts
        where_keywords = ["WHERE", "ON", "ORDER BY", "GROUP BY", "HAVING"]

        # Find the rightmost occurrence of any WHERE-like keyword
        last_keyword_pos = -1
        found_keyword = None

        for keyword in where_keywords:
            pos = text_before_cursor.rfind(keyword)
            if pos > last_keyword_pos:
                last_keyword_pos = pos
                found_keyword = keyword

        if found_keyword and last_keyword_pos != -1:
            # Check if we're actually after the keyword (not just at the beginning of it)
            keyword_end_pos = last_keyword_pos + len(found_keyword)
            return cursor_position[1] >= keyword_end_pos

        return False

    def _is_after_from_keyword(self, text: str, cursor_position: tuple) -> bool:
        """Check if cursor is positioned after FROM keyword but before other clauses."""
        text_before_cursor = text[: cursor_position[1]].upper()

        # Find the last FROM keyword
        from_pos = text_before_cursor.rfind("FROM")
        if from_pos == -1:
            return False

        # Check if cursor is after FROM
        if cursor_position[1] <= from_pos + 4:  # 4 is length of "FROM"
            return False

        # Check if we're still in FROM clause (before WHERE, ORDER BY, etc.)
        text_after_from = text_before_cursor[from_pos + 4 :]

        # Keywords that end the FROM clause
        ending_keywords = ["WHERE", "ORDER BY", "GROUP BY", "HAVING", "LIMIT", "UNION"]

        for keyword in ending_keywords:
            if keyword in text_after_from:
                keyword_pos = text_after_from.find(keyword)
                cursor_relative_pos = len(text_after_from)
                if cursor_relative_pos > keyword_pos:
                    return False

        return True

    def _should_hide_autocomplete(self, text: str, cursor_position: tuple) -> bool:
        """Check if autocomplete should be hidden at the current position."""
        cursor_line, cursor_col = cursor_position
        lines = text.split("\n")

        if cursor_line >= len(lines):
            return False

        current_line = lines[cursor_line]

        # Check if we're inside a string literal
        if self._is_inside_string_literal(text, cursor_position):
            return True

        # Check if we're inside a comment
        if self._is_inside_comment(text, cursor_position):
            return True

        # Check if we're in a numeric literal
        if self._is_inside_numeric_literal(current_line, cursor_col):
            return True

        # Check if we're in a VALUES clause for INSERT
        if self._is_in_values_clause(text, cursor_position):
            return True

        # Check if we're after certain operators where suggestions don't make sense
        if self._is_after_value_operator(current_line, cursor_col):
            return True

        # NEW: Check if we're after a semicolon
        if self._is_after_semicolon(text, cursor_position):
            return True

        # NEW: Check if we're at the end of a complete statement
        if self._is_after_complete_statement(text, cursor_position):
            return True

        # NEW: Check if we're in whitespace after FROM table_name
        if self._is_after_table_name_in_from(text, cursor_position):
            return True

        return False

    def _is_after_semicolon(self, text: str, cursor_position: tuple) -> bool:
        """Check if cursor is after a semicolon."""
        cursor_line, cursor_col = cursor_position
        lines = text.split("\n")

        if cursor_line >= len(lines):
            return False

        # Check if there's a semicolon before the cursor on the same line
        current_line = lines[cursor_line]
        text_before_cursor_on_line = current_line[:cursor_col]

        # Also check previous lines for semicolon
        text_before_cursor = text[
            : sum(len(line) + 1 for line in lines[:cursor_line]) + cursor_col
        ]

        # Find the last semicolon
        last_semicolon = text_before_cursor.rfind(";")
        if last_semicolon == -1:
            return False

        # Check if there's any significant SQL content after the semicolon
        text_after_semicolon = text_before_cursor[last_semicolon + 1 :].strip()

        # If there's no significant content after semicolon, hide suggestions
        if not text_after_semicolon:
            return True

        # If the content after semicolon is just whitespace or comments, hide suggestions
        lines_after_semicolon = text_after_semicolon.split("\n")
        for line in lines_after_semicolon:
            line_stripped = line.strip()
            if line_stripped and not line_stripped.startswith("--"):
                # There's actual SQL content, don't hide
                return False

        return True

    def _is_after_complete_statement(self, text: str, cursor_position: tuple) -> bool:
        """Check if cursor is after a complete SQL statement."""
        cursor_line, cursor_col = cursor_position

        # Get text before cursor
        text_before_cursor = text[
            : sum(len(line) + 1 for line in text.split("\n")[:cursor_line]) + cursor_col
        ]

        # Remove comments and extra whitespace
        cleaned_text = self._clean_sql_text(text_before_cursor)

        if not cleaned_text.strip():
            return False

        # Check if the text ends with a complete statement pattern
        # Simple heuristic: if it ends with table name after FROM and we're in whitespace
        words = cleaned_text.upper().split()
        if len(words) >= 3:
            # Pattern: SELECT ... FROM table_name
            if "FROM" in words:
                from_index = len(words) - 1 - words[::-1].index("FROM")
                # If FROM is not the last word and we have a table name after it
                if from_index < len(words) - 1:
                    # We're after a table name, check if cursor is just in whitespace
                    remaining_text = text_before_cursor.rstrip()
                    if text_before_cursor != remaining_text:
                        # We're in trailing whitespace after a complete FROM clause
                        return True

        return False

    def _is_after_table_name_in_from(self, text: str, cursor_position: tuple) -> bool:
        """Check if cursor is in whitespace after a table name in FROM clause."""
        cursor_line, cursor_col = cursor_position

        # Get text before cursor
        text_before_cursor = text[
            : sum(len(line) + 1 for line in text.split("\n")[:cursor_line]) + cursor_col
        ]

        # Check if we're in a FROM context
        if not self._is_after_from_keyword(text, cursor_position):
            return False

        # Get the text after the last FROM
        from_pos = text_before_cursor.upper().rfind("FROM")
        if from_pos == -1:
            return False

        text_after_from = text_before_cursor[from_pos + 4 :].strip()

        # Split into words
        words = text_after_from.split()

        # If we have exactly one word (table name) and cursor is in whitespace after it
        if len(words) == 1:
            # Check if cursor is after the table name in whitespace
            table_name = words[0]
            table_end_pos = text_after_from.find(table_name) + len(table_name)
            cursor_pos_in_from_text = len(text_after_from)

            # If cursor is after table name in whitespace
            if cursor_pos_in_from_text > table_end_pos:
                remaining_text = text_after_from[table_end_pos:].strip()
                if not remaining_text:  # Only whitespace after table name
                    return True

        return False

    def _clean_sql_text(self, text: str) -> str:
        """Clean SQL text by removing comments and normalizing whitespace."""
        lines = text.split("\n")
        cleaned_lines = []

        for line in lines:
            # Remove single-line comments
            comment_pos = line.find("--")
            if comment_pos != -1:
                line = line[:comment_pos]
            cleaned_lines.append(line)

        # Join lines and normalize whitespace
        cleaned = " ".join(cleaned_lines)

        # Remove multi-line comments (simple approach)
        while "/*" in cleaned and "*/" in cleaned:
            start = cleaned.find("/*")
            end = cleaned.find("*/", start)
            if start != -1 and end != -1:
                cleaned = cleaned[:start] + cleaned[end + 2 :]
            else:
                break

        return cleaned

    def _is_inside_string_literal(self, text: str, cursor_position: tuple) -> bool:
        """Check if cursor is inside a string literal (single or double quotes)."""
        cursor_line, cursor_col = cursor_position
        lines = text.split("\n")

        if cursor_line >= len(lines):
            return False

        current_line = lines[cursor_line]

        # Count quotes before cursor position
        single_quote_count = 0
        double_quote_count = 0

        i = 0
        while i < cursor_col and i < len(current_line):
            char = current_line[i]
            if char == "'" and (i == 0 or current_line[i - 1] != "\\"):
                single_quote_count += 1
            elif char == '"' and (i == 0 or current_line[i - 1] != "\\"):
                double_quote_count += 1
            i += 1

        # If odd number of quotes, we're inside a string
        return (single_quote_count % 2 == 1) or (double_quote_count % 2 == 1)

    def _is_inside_comment(self, text: str, cursor_position: tuple) -> bool:
        """Check if cursor is inside a SQL comment."""
        cursor_line, cursor_col = cursor_position
        lines = text.split("\n")

        if cursor_line >= len(lines):
            return False

        current_line = lines[cursor_line]

        # Check for single-line comment (--)
        comment_pos = current_line.find("--")
        if comment_pos != -1 and cursor_col >= comment_pos:
            return True

        # Check for multi-line comment (/* */)
        # This is more complex - need to check if we're inside a /* */ block
        text_before_cursor = text[: cursor_position[1]]

        # Find all /* and */ positions
        start_comment = text_before_cursor.rfind("/*")
        end_comment = text_before_cursor.rfind("*/")

        # If we found a /* after the last */, we're inside a comment
        if start_comment != -1 and (end_comment == -1 or start_comment > end_comment):
            return True

        return False

    def _is_inside_numeric_literal(self, line: str, cursor_col: int) -> bool:
        """Check if cursor is inside a numeric literal."""
        if cursor_col == 0 or cursor_col > len(line):
            return False

        # Check characters around cursor
        start = cursor_col - 1
        end = cursor_col

        # Expand to find the full token
        while start > 0 and (line[start - 1].isdigit() or line[start - 1] in ".-"):
            start -= 1

        while end < len(line) and (line[end].isdigit() or line[end] in ".-"):
            end += 1

        if start < end:
            token = line[start:end]
            # Check if it looks like a number
            try:
                float(token)
                return True
            except ValueError:
                pass

        return False

    def _is_in_values_clause(self, text: str, cursor_position: tuple) -> bool:
        """Check if cursor is in a VALUES clause of an INSERT statement."""
        text_before_cursor = text[: cursor_position[1]].upper()

        # Look for INSERT ... VALUES pattern
        if "INSERT" not in text_before_cursor or "VALUES" not in text_before_cursor:
            return False

        # Find the last VALUES keyword
        values_pos = text_before_cursor.rfind("VALUES")
        if values_pos == -1:
            return False

        # Check if we're after VALUES and inside parentheses
        text_after_values = text_before_cursor[values_pos + 6 :]  # 6 = len('VALUES')

        # Count parentheses to see if we're inside a values list
        paren_count = 0
        for char in text_after_values:
            if char == "(":
                paren_count += 1
            elif char == ")":
                paren_count -= 1

        return paren_count > 0

    def _is_after_value_operator(self, line: str, cursor_col: int) -> bool:
        """Check if cursor is after operators where values are expected, not column names."""
        if cursor_col < 2:
            return False

        # Look at the few characters before cursor
        text_before = line[:cursor_col].strip()

        # Operators after which we typically expect values, not column/table names
        value_operators = [
            "=",
            "!=",
            "<>",
            "<",
            ">",
            "<=",
            ">=",
            "LIKE",
            "IN",
            "NOT IN",
        ]

        for op in value_operators:
            if text_before.upper().endswith(op.upper()):
                return True
            # Also check with space after operator
            if text_before.upper().endswith(op.upper() + " "):
                return True

        return False

    def _get_available_columns(self, tables: list[str]) -> list[str]:
        """Get all available columns from the specified tables."""
        all_columns = []

        for table in tables:
            columns = self._get_table_columns(table)
            # Add unqualified columns
            for col in columns:
                all_columns.append(col)
            # Add table-qualified columns
            for col in columns:
                all_columns.append(f"{table}.{col}")

        print(f"Available columns from tables {tables}: {all_columns}")
        return list(set(all_columns))  # Remove duplicates

    def _get_table_columns(self, table_name: str) -> list[str]:
        """Get columns for a specific table."""
        return self.db_connection.get_columns(table_name)
