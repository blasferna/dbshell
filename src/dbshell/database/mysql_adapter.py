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
        self.current_database = self.database
        self.cursor: mysql.connector.cursor.MySQLCursor | None = None
        self.ssl_disabled: bool = connection_params.get("ssl_disabled")

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
                ssl_disabled=self.ssl_disabled
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
            self.current_database = database
            return True, f"Changed to database: {database}"
        except MySQLError as e:
            return False, f"Error changing database: {str(e)}"

    def get_tables(self, database: str = None) -> tuple[list[str], str | None]:
        db_name = database or self.current_database
        if not db_name or not self.cursor:
            return [], "No database selected"
        try:
            self.cursor.execute(f"SHOW TABLES FROM `{db_name}`")
            return [row[0] for row in self.cursor.fetchall()], None
        except MySQLError as e:
            return [], str(e)

    def get_columns(self, table_name: str, database: str = None) -> list[str]:
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

    def get_database_objects(
        self, database: str = None
    ) -> tuple[bool, str, dict[str, list[str]] | None]:
        """Get all database objects grouped by type."""
        if not self.connection or not self.cursor:
            return False, "No database connection", None

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
            self.cursor.execute(f"SHOW TABLES FROM `{db_name}`")
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
        if not self.connection or not self.cursor:
            return False, "No database connection", None

        try:
            # Map object types to SQL commands
            sql_commands = {
                "tables": f"SHOW CREATE TABLE `{obj_name}`",
                "views": f"SHOW CREATE VIEW `{obj_name}`",
                "procedures": f"SHOW CREATE PROCEDURE `{obj_name}`",
                "functions": f"SHOW CREATE FUNCTION `{obj_name}`"
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
