import sqlite3
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

    def connect(self) -> tuple[bool, str]:
        """Establish database connection."""
        try:
            self.connection = sqlite3.connect(self.database)
            self.connection.row_factory = sqlite3.Row
            self.cursor = self.connection.cursor()
            self.current_database = self.database

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
        if not self.connection:
            return False, "No database connection", None

        databases = [self.database] if self.database != ":memory:" else ["memory"]
        return True, f"Current database: {databases[0]}", databases

    def change_database(self, database: str) -> tuple[bool, str]:
        """
        Change to a different database.
        For SQLite, this would require opening a new connection.
        """
        if database == self.database:
            return True, f"Already using database: {database}"

        try:
            if self.connection:
                self.connection.close()

            self.database = database
            self.connection = sqlite3.connect(self.database)
            self.connection.row_factory = sqlite3.Row
            self.cursor = self.connection.cursor()
            self.current_database = database

            return True, f"Changed to database: {database}"
        except sqlite3.Error as e:
            return False, f"Error changing database: {str(e)}"

    def get_tables(self, database: str = None) -> tuple[list[str], str | None]:
        """Get list of tables in the database."""
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
        if not self.connection or not self.cursor:
            return []

        try:
            self.cursor.execute(f"PRAGMA table_info({table})")
            # row[1] is column name
            columns = [row[1] for row in self.cursor.fetchall()]
            return columns
        except sqlite3.Error:
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

            # Check if query returns data
            if self.cursor.description:
                columns = [desc[0] for desc in self.cursor.description]
                rows = self.cursor.fetchall()

                # Convert sqlite3.Row objects to regular tuples
                if rows and isinstance(rows[0], sqlite3.Row):
                    rows = [tuple(row) for row in rows]

                row_count = len(rows)
                return (
                    True,
                    f"Query successful. {row_count} rows returned.",
                    columns,
                    rows,
                )
            else:
                # For INSERT, UPDATE, DELETE operations
                row_count = self.cursor.rowcount
                self.connection.commit()  # Commit the transaction
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
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()

    def get_database_objects(
        self, database: str = None
    ) -> tuple[bool, str, dict[str, list[str]] | None]:
        """Get all database objects grouped by type."""
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
