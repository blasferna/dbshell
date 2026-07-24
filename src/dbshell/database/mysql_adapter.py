import contextlib
from collections.abc import Sequence
from typing import Any

import mysql.connector
from mysql.connector import Error as MySQLError

from .base import DatabaseAdapter

# Fail fast when the host is unreachable instead of hanging the UI.
CONNECT_TIMEOUT_SECONDS = 10

# Chunk size used to discard rows past the max-rows cap so the
# connection is left without unread results.
_DRAIN_CHUNK = 10_000


class MySQLAdapter(DatabaseAdapter):
    """MySQL database adapter implementation."""

    def __init__(self, connection_params: dict[str, Any]):
        super().__init__(connection_params)
        self.host = connection_params.get("host", "localhost")
        self.user = connection_params.get("user", "")
        self.password = connection_params.get("password", "")
        self.port = connection_params.get("port", 3306)
        self.database = connection_params.get("database")
        self.current_database = self.database
        self.cursor: mysql.connector.cursor.MySQLCursor | None = None
        self.ssl_disabled: bool = connection_params.get("ssl_disabled")

    @property
    def engine_name(self) -> str:
        """Return the name of the database engine."""
        return "MySQL"

    @property
    def param_placeholder(self) -> str:
        """Return the bind-parameter placeholder for MySQL."""
        return "%s"

    def connect(self) -> tuple[bool, str]:
        """Establish database connection."""
        with self._lock:
            try:
                self.connection = mysql.connector.connect(
                    host=self.host,
                    user=self.user,
                    password=self.password,
                    port=self.port,
                    autocommit=True,
                    ssl_disabled=self.ssl_disabled,
                    connection_timeout=CONNECT_TIMEOUT_SECONDS,
                    consume_results=True,
                )

                self.cursor = self.connection.cursor()

                if self.database:
                    self.cursor.execute(
                        f"USE {self.quote_identifier(self.database)}"
                    )
                    self.current_database = self.database
                    return (
                        True,
                        f"Connected to {self.host}:{self.port}, "
                        f"using database '{self.database}'",
                    )

                return (
                    True,
                    f"Connected to {self.host}:{self.port} (no database selected)",
                )
            except MySQLError as e:
                return False, f"Connection failed: {str(e)}"

    def _ensure_connection(self) -> str | None:
        """Verify the connection is alive, reconnecting once if needed.

        Returns an error message when the connection cannot be restored,
        or ``None`` when it is usable. After a reconnect the cursor is
        recreated and the current database re-selected, since session
        state is lost.
        """
        if not self.connection or not self.cursor:
            return "No database connection"

        try:
            self.connection.ping(reconnect=False)
            return None
        except MySQLError:
            pass

        try:
            self.connection.ping(reconnect=True, attempts=1, delay=0)
            with contextlib.suppress(MySQLError):
                self.cursor.close()
            self.cursor = self.connection.cursor()
            if self.database:
                self.cursor.execute(f"USE {self.quote_identifier(self.database)}")
            return None
        except MySQLError as e:
            return f"Connection lost and reconnect failed: {e}"

    def get_databases(self) -> tuple[bool, str, list[str] | None]:
        """
        Get list of available databases.
        Returns: (success: bool, message: str, databases: Optional[List[str]])
        """
        with self._lock:
            error = self._ensure_connection()
            if error:
                return False, error, None

            try:
                self.cursor.execute("SHOW DATABASES")
                databases = [row[0] for row in self.cursor.fetchall()]
                # Filter out system databases
                user_databases = [
                    db
                    for db in databases
                    if db
                    not in ["information_schema", "performance_schema", "mysql", "sys"]
                ]
                return True, f"Found {len(user_databases)} databases", user_databases
            except MySQLError as e:
                return False, f"Error getting databases: {str(e)}", None

    def change_database(self, database: str) -> tuple[bool, str]:
        """
        Change to a different database.
        Returns: (success: bool, message: str)
        """
        with self._lock:
            error = self._ensure_connection()
            if error:
                return False, error

            try:
                self.cursor.execute(f"USE {self.quote_identifier(database)}")
                self.database = database
                self.current_database = database
                return True, f"Changed to database: {database}"
            except MySQLError as e:
                return False, f"Error changing database: {str(e)}"

    def get_tables(self, database: str = None) -> tuple[list[str], str | None]:
        with self._lock:
            db_name = database or self.current_database
            if not db_name or not self.cursor:
                return [], "No database selected"
            try:
                self.cursor.execute(
                    f"SHOW TABLES FROM {self.quote_identifier(db_name)}"
                )
                return [row[0] for row in self.cursor.fetchall()], None
            except MySQLError as e:
                return [], str(e)

    def get_columns(self, table_name: str, database: str = None) -> list[str]:
        """Get columns for a specific table."""
        with self._lock:
            if not self.connection or not self.cursor:
                return []

            try:
                self.cursor.execute(
                    f"DESCRIBE {self.quote_identifier(table_name)}"
                )
                return [row[0] for row in self.cursor.fetchall()]
            except MySQLError:
                return []

    def execute_query(
        self, query: str, params: Sequence[Any] | None = None
    ) -> tuple[bool, str, list | None, list | None]:
        """Execute a single SQL statement."""
        with self._lock:
            query = query.strip()
            if not query:
                return False, "Empty query", None, None

            error = self._ensure_connection()
            if error:
                return False, error, None, None

            self.last_result_truncated = False
            try:
                if params is None:
                    self.cursor.execute(query)
                else:
                    self.cursor.execute(query, params)

                if self.cursor.description:
                    columns = [desc[0] for desc in self.cursor.description]
                    if self.max_rows is None:
                        rows = self.cursor.fetchall()
                        message = f"Query successful. {len(rows)} rows returned."
                        return True, message, columns, rows
                    rows = self.cursor.fetchmany(self.max_rows + 1)
                    if len(rows) > self.max_rows:
                        rows = rows[: self.max_rows]
                        self.last_result_truncated = True
                        self._drain_pending_rows()
                        message = (
                            f"Query successful. Showing first {self.max_rows} "
                            "rows (result truncated)."
                        )
                    else:
                        message = f"Query successful. {len(rows)} rows returned."
                    return True, message, columns, rows
                else:
                    row_count = self.cursor.rowcount
                    return (
                        True,
                        f"Query executed successfully. {row_count} rows affected.",
                        None,
                        None,
                    )

            except MySQLError as e:
                return False, f"Query error: {str(e)}", None, None

    def _drain_pending_rows(self) -> None:
        """Discard rows beyond the cap so no unread results remain."""
        with contextlib.suppress(MySQLError):
            while self.cursor.fetchmany(_DRAIN_CHUNK):
                pass

    def close(self):
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
            error = self._ensure_connection()
            if error:
                return False, error, None

            db_name = database or self.current_database
            if not db_name:
                return False, "No database selected", None

            try:
                objects = {
                    "tables": [],
                    "views": [],
                    "procedures": [],
                    "functions": []
                }

                # Get tables
                self.cursor.execute(
                    f"SHOW TABLES FROM {self.quote_identifier(db_name)}"
                )
                objects["tables"] = [row[0] for row in self.cursor.fetchall()]

                # Get views
                self.cursor.execute("""
                    SELECT TABLE_NAME 
                    FROM INFORMATION_SCHEMA.VIEWS 
                    WHERE TABLE_SCHEMA = %s
                """, (db_name,))
                objects["views"] = [row[0] for row in self.cursor.fetchall()]

                # Get procedures
                self.cursor.execute("""
                    SELECT ROUTINE_NAME 
                    FROM INFORMATION_SCHEMA.ROUTINES 
                    WHERE ROUTINE_SCHEMA = %s AND ROUTINE_TYPE = 'PROCEDURE'
                """, (db_name,))
                objects["procedures"] = [row[0] for row in self.cursor.fetchall()]

                # Get functions
                self.cursor.execute("""
                    SELECT ROUTINE_NAME 
                    FROM INFORMATION_SCHEMA.ROUTINES 
                    WHERE ROUTINE_SCHEMA = %s AND ROUTINE_TYPE = 'FUNCTION'
                """, (db_name,))
                objects["functions"] = [row[0] for row in self.cursor.fetchall()]

                total_objects = sum(len(obj_list) for obj_list in objects.values())
                return True, f"Found {total_objects} objects", objects

            except MySQLError as e:
                return False, f"Error getting database objects: {str(e)}", None

    def get_object_creation_sql(
        self, obj_name: str, obj_type: str, database: str = None
    ) -> tuple[bool, str, str | None]:
        """Get the creation SQL for a database object."""
        with self._lock:
            if not self.connection or not self.cursor:
                return False, "No database connection", None

            try:
                quoted = self.quote_identifier(obj_name)
                # Map object types to SQL commands
                sql_commands = {
                    "tables": f"SHOW CREATE TABLE {quoted}",
                    "views": f"SHOW CREATE VIEW {quoted}",
                    "procedures": f"SHOW CREATE PROCEDURE {quoted}",
                    "functions": f"SHOW CREATE FUNCTION {quoted}"
                }

                sql = sql_commands.get(obj_type)
                if not sql:
                    return False, f"Unsupported object type: {obj_type}", None

                self.cursor.execute(sql)
                result = self.cursor.fetchone()

                if result:
                    # Return the creation SQL (usually in the second column)
                    creation_sql = result[1] if len(result) > 1 else str(result[0])
                    message = f"Retrieved creation SQL for {obj_type[:-1]}: {obj_name}"
                    return True, message, creation_sql
                else:
                    return False, f"No creation SQL found for {obj_name}", None

            except MySQLError as e:
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
            except MySQLError as e:
                return False, f"Error counting rows: {str(e)}", None

    def get_object_columns_detailed(
        self, table: str, database: str = None
    ) -> tuple[bool, str, list[tuple[str, str]] | None]:
        """Get columns with their types for a table or view."""
        with self._lock:
            if not self.connection or not self.cursor:
                return False, "No database connection", None

            try:
                self.cursor.execute(f"DESCRIBE {self.quote_identifier(table)}")
                columns: list[tuple[str, str]] = [
                    (row[0], row[1]) for row in self.cursor.fetchall()
                ]
                return True, f"{len(columns)} columns", columns
            except MySQLError as e:
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
                    SELECT TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                    """,
                    (table,),
                )
                row = self.cursor.fetchone()
                if row is None or str(row[0]).upper() != "BASE TABLE":
                    return True, "View has no primary key", []

                self.cursor.execute(
                    f"SHOW KEYS FROM {self.quote_identifier(table)} "
                    "WHERE Key_name = 'PRIMARY'"
                )
                pk_columns: list[str] = [
                    item_row[4] for item_row in self.cursor.fetchall()
                ]
                return True, f"{len(pk_columns)} primary key column(s)", pk_columns
            except MySQLError as e:
                return False, f"Error getting primary keys: {str(e)}", None

    def quote_identifier(self, name: str) -> str:
        """Return the identifier quoted with MySQL backticks."""
        escaped = name.replace("`", "``")
        return f"`{escaped}`"
