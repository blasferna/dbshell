from typing import Any

import mysql.connector
from mysql.connector import Error as MySQLError

from .base import DatabaseAdapter


class MySQLAdapter(DatabaseAdapter):
    """MySQL database adapter implementation."""

    def __init__(self, connection_params: dict[str, Any]):
        super().__init__(connection_params)
        self.host = connection_params.get("host", "localhost")
        self.user = connection_params.get("user", "")
        self.password = connection_params.get("password", "")
        self.port = connection_params.get("port", 3306)
        self.database = connection_params.get("database")
        self.cursor: mysql.connector.cursor.MySQLCursor | None = None

    @property
    def engine_name(self) -> str:
        """Return the name of the database engine."""
        return "MySQL"

    def connect(self) -> tuple[bool, str]:
        """Establish database connection."""

        try:
            self.connection = mysql.connector.connect(
                host=self.host,
                user=self.user,
                password=self.password,
                port=self.port,
                autocommit=True,
            )

            self.cursor = self.connection.cursor()

            if self.database:
                self.cursor.execute(f"USE `{self.database}`")
                self.current_database = self.database

            return (
                True,
                f"Connected to {self.host}:{self.port} (no database selected)",
            )
        except MySQLError as e:
            return False, f"Connection failed: {str(e)}"

    def get_databases(self) -> tuple[bool, str, list[str] | None]:
        """
        Get list of available databases.
        Returns: (success: bool, message: str, databases: Optional[List[str]])
        """
        if not self.connection or not self.cursor:
            return False, "No database connection", None

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
        if not self.connection or not self.cursor:
            return False, "No database connection"

        try:
            self.cursor.execute(f"USE `{database}`")
            self.database = database
            return True, f"Changed to database: {database}"
        except MySQLError as e:
            return False, f"Error changing database: {str(e)}"

    def get_tables(self) -> tuple[list[str], str | None]:
        if not self.database or not self.cursor:
            return [], "No database selected"
        try:
            self.cursor.execute("SHOW TABLES")
            return [row[0] for row in self.cursor.fetchall()], None
        except MySQLError as e:
            return [], str(e)

    def get_columns(self, table_name: str) -> list[str]:
        """Get columns for a specific table."""
        if not self.connection or not self.cursor:
            return []

        try:
            _, _, _, rows = self.execute_query(f"DESCRIBE `{table_name}`")
            columns = [row[0] for row in rows]
            return columns
        except Exception:
            return []

    def execute_query(self, query: str) -> tuple[bool, str, list | None, list | None]:
        """Execute SQL query."""
        if not self.connection or not self.cursor:
            return False, "No database connection", None, None

        try:
            query = query.strip()
            if not query:
                return False, "Empty query", None, None

            self.cursor.execute(query)

            if self.cursor.description:
                columns = [desc[0] for desc in self.cursor.description]
                rows = self.cursor.fetchall()
                row_count = len(rows)
                return (
                    True,
                    f"Query successful. {row_count} rows returned.",
                    columns,
                    rows,
                )
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

    def close(self):
        """Close database connection."""
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
