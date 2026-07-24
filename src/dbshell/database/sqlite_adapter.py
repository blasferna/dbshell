import contextlib
import sqlite3
from collections.abc import Sequence
from typing import Any

from .base import DatabaseAdapter


class SQLiteAdapter(DatabaseAdapter):
    """SQLite database adapter implementation."""

    def __init__(self, connection_params: dict[str, Any]):
        super().__init__(connection_params)
        self.database = connection_params.get("database", ":memory:")
        self.cursor: sqlite3.Cursor | None = None

    @property
    def engine_name(self) -> str:
        """Return the name of the database engine."""
        return "SQLite"

    @property
    def param_placeholder(self) -> str:
        """Return the bind-parameter placeholder for SQLite."""
        return "?"

    def _open_connection(self) -> None:
        # isolation_level=None puts sqlite3 in autocommit mode: every
        # statement takes effect immediately (matching the MySQL adapter,
        # which uses autocommit=True) and statements that return rows,
        # such as INSERT ... RETURNING, are persisted too. Explicit
        # BEGIN/COMMIT statements still work.
        # check_same_thread=False is required because queries run in
        # worker threads; the adapter lock serializes access.
        self.connection = sqlite3.connect(
            self.database,
            isolation_level=None,
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row
        self.cursor = self.connection.cursor()
        self.current_database = self.database

    def connect(self) -> tuple[bool, str]:
        """Establish database connection."""
        with self._lock:
            try:
                self._open_connection()
                return (
                    True,
                    f"Connected to SQLite database: {self.database}",
                )
            except sqlite3.Error as e:
                return False, f"Connection failed: {str(e)}"

    def get_databases(self) -> tuple[bool, str, list[str] | None]:
        """
        Get list of available databases.
        For SQLite, this returns the current database file.
        """
        with self._lock:
            if not self.connection:
                return False, "No database connection", None

            databases = [self.database] if self.database != ":memory:" else ["memory"]
            return True, f"Current database: {databases[0]}", databases

    def change_database(self, database: str) -> tuple[bool, str]:
        """
        Change to a different database.
        For SQLite, this would require opening a new connection.
        """
        with self._lock:
            if database == self.database:
                return True, f"Already using database: {database}"

            try:
                if self.connection:
                    self.connection.close()

                self.database = database
                self._open_connection()

                return True, f"Changed to database: {database}"
            except sqlite3.Error as e:
                return False, f"Error changing database: {str(e)}"

    def get_tables(self, database: str = None) -> tuple[list[str], str | None]:
        """Get list of tables in the database."""
        with self._lock:
            if not self.connection or not self.cursor:
                return [], "No database connection"

            try:
                self.cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name NOT LIKE 'sqlite_%'
                    ORDER BY name
                """)
                tables = [row[0] for row in self.cursor.fetchall()]
                return tables, None
            except sqlite3.Error as e:
                return [], str(e)

    def get_columns(self, table: str, database: str = None) -> list[str]:
        """Get column information for specified table."""
        with self._lock:
            if not self.connection or not self.cursor:
                return []

            try:
                self.cursor.execute(
                    f"PRAGMA table_info({self.quote_identifier(table)})"
                )
                # row[1] is column name
                columns = [row[1] for row in self.cursor.fetchall()]
                return columns
            except sqlite3.Error:
                return []

    def execute_query(
        self, query: str, params: Sequence[Any] | None = None
    ) -> tuple[bool, str, list | None, list | None]:
        """Execute a single SQL statement."""
        with self._lock:
            if not self.connection or not self.cursor:
                return False, "No database connection", None, None

            query = query.strip()
            if not query:
                return False, "Empty query", None, None

            self.last_result_truncated = False
            try:
                if params is None:
                    self.cursor.execute(query)
                else:
                    self.cursor.execute(query, params)

                # Check if query returns data
                if self.cursor.description:
                    columns = [desc[0] for desc in self.cursor.description]
                    if self.max_rows is None:
                        rows = [tuple(row) for row in self.cursor.fetchall()]
                        message = f"Query successful. {len(rows)} rows returned."
                        return True, message, columns, rows
                    rows = [
                        tuple(row)
                        for row in self.cursor.fetchmany(self.max_rows + 1)
                    ]
                    if len(rows) > self.max_rows:
                        rows = rows[: self.max_rows]
                        self.last_result_truncated = True
                        message = (
                            f"Query successful. Showing first {self.max_rows} "
                            "rows (result truncated)."
                        )
                    else:
                        message = f"Query successful. {len(rows)} rows returned."
                    return True, message, columns, rows
                else:
                    # For INSERT, UPDATE, DELETE operations
                    row_count = self.cursor.rowcount
                    return (
                        True,
                        f"Query executed successfully. {row_count} rows affected.",
                        None,
                        None,
                    )

            except sqlite3.Error as e:
                return False, f"Query error: {str(e)}", None, None

    def close(self) -> None:
        """Close database connection."""
        # Best effort: don't wait forever if a query is still running in
        # a worker thread.
        acquired = self._lock.acquire(timeout=2)
        try:
            if self.cursor:
                with contextlib.suppress(Exception):
                    self.cursor.close()
            if self.connection:
                with contextlib.suppress(Exception):
                    self.connection.close()
        finally:
            if acquired:
                self._lock.release()

    def get_database_objects(
        self, database: str = None
    ) -> tuple[bool, str, dict[str, list[str]] | None]:
        """Get all database objects grouped by type."""
        with self._lock:
            if not self.connection or not self.cursor:
                return False, "No database connection", None

            try:
                objects = {
                    "tables": [],
                    "views": [],
                    "procedures": [],
                    "functions": []
                }

                # Get tables
                self.cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name NOT LIKE 'sqlite_%'
                    ORDER BY name
                """)
                objects["tables"] = [row[0] for row in self.cursor.fetchall()]

                # Get views
                self.cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='view'
                    ORDER BY name
                """)
                objects["views"] = [row[0] for row in self.cursor.fetchall()]

                # SQLite doesn't support stored procedures/functions natively
                objects["procedures"] = []
                objects["functions"] = []

                total_objects = sum(len(obj_list) for obj_list in objects.values())
                return True, f"Found {total_objects} objects", objects

            except sqlite3.Error as e:
                return False, f"Error getting database objects: {str(e)}", None

    def get_object_creation_sql(
        self, obj_name: str, obj_type: str, database: str = None
    ) -> tuple[bool, str, str | None]:
        """Get the creation SQL for a database object."""
        with self._lock:
            if not self.connection or not self.cursor:
                return False, "No database connection", None

            try:
                if obj_type == "tables":
                    # Get table creation SQL from sqlite_master
                    self.cursor.execute(
                        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                        (obj_name,)
                    )
                elif obj_type == "views":
                    # Get view creation SQL from sqlite_master
                    self.cursor.execute(
                        "SELECT sql FROM sqlite_master WHERE type='view' AND name=?",
                        (obj_name,)
                    )
                elif obj_type in ["procedures", "functions"]:
                    # SQLite doesn't support stored procedures or functions
                    return False, f"SQLite doesn't support {obj_type}", None
                else:
                    return False, f"Unsupported object type: {obj_type}", None

                result = self.cursor.fetchone()

                if result and result[0]:
                    creation_sql = result[0]
                    message = f"Retrieved creation SQL for {obj_type[:-1]}: {obj_name}"
                    return True, message, creation_sql
                else:
                    return False, f"No creation SQL found for {obj_name}", None

            except sqlite3.Error as e:
                return False, f"Error getting creation SQL: {str(e)}", None

    def get_row_count(
        self, table: str, database: str = None
    ) -> tuple[bool, str, int | None]:
        """Get the row count for a table or view."""
        with self._lock:
            if not self.connection or not self.cursor:
                return False, "No database connection", None

            try:
                self.cursor.execute(
                    f"SELECT COUNT(*) FROM {self.quote_identifier(table)}"
                )
                row = self.cursor.fetchone()
                count = int(row[0]) if row else 0
                return True, f"{count} rows", count
            except sqlite3.Error as e:
                return False, f"Error counting rows: {str(e)}", None

    def get_object_columns_detailed(
        self, table: str, database: str = None
    ) -> tuple[bool, str, list[tuple[str, str]] | None]:
        """Get columns with their types for a table or view."""
        with self._lock:
            if not self.connection or not self.cursor:
                return False, "No database connection", None

            try:
                self.cursor.execute(
                    f"PRAGMA table_info({self.quote_identifier(table)})"
                )
                columns: list[tuple[str, str]] = [
                    (row[1], row[2] or "") for row in self.cursor.fetchall()
                ]
                return True, f"{len(columns)} columns", columns
            except sqlite3.Error as e:
                return False, f"Error describing table: {str(e)}", None

    def get_primary_keys(
        self, table: str, database: str = None
    ) -> tuple[bool, str, list[str] | None]:
        """Get primary key columns for a table.

        Returns an empty list for views or tables without a primary key.
        """
        with self._lock:
            if not self.connection or not self.cursor:
                return False, "No database connection", None

            try:
                self.cursor.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE name = ? AND type = 'view'
                    """,
                    (table,),
                )
                if self.cursor.fetchone() is not None:
                    return True, "View has no primary key", []

                self.cursor.execute(
                    f"PRAGMA table_info({self.quote_identifier(table)})"
                )
                pk_columns: list[str] = [
                    row[1] for row in self.cursor.fetchall() if row[5] and row[5] > 0
                ]
                return True, f"{len(pk_columns)} primary key column(s)", pk_columns
            except sqlite3.Error as e:
                return False, f"Error getting primary keys: {str(e)}", None

    def quote_identifier(self, name: str) -> str:
        """Return the identifier quoted with double quotes for SQLite."""
        escaped = name.replace('"', '""')
        return f'"{escaped}"'
