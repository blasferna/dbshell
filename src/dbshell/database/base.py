from abc import ABC, abstractmethod
from typing import Any


class DatabaseAdapter(ABC):
    """Base class for database adapters following the adapter pattern."""

    def __init__(self, connection_params: dict[str, Any]):
        self.connection_params = connection_params
        self.connection = None
        self.current_database: str | None = None

    @abstractmethod
    def connect(self) -> tuple[bool, str]:
        """Establish database connection."""
        pass

    @abstractmethod
    def execute_query(self, query: str) -> tuple[bool, str, list | None, list | None]:
        """Execute a query and return results."""
        pass

    @abstractmethod
    def get_databases(self) -> tuple[bool, str, list[str] | None]:
        """Get list of available databases."""
        pass

    @abstractmethod
    def get_tables(self, database: str = None) -> tuple[list[str], str | None]:
        """Get list of tables in specified database."""
        pass

    @abstractmethod
    def get_columns(self, table: str, database: str = None) -> list[str]:
        """Get column information for specified table."""
        pass

    @abstractmethod
    def change_database(self, database: str) -> tuple[bool, str]:
        """Switch to different database."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close database connection."""
        pass

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Return the name of the database engine."""
        pass

    @abstractmethod
    def get_database_objects(
        self, database: str = None
    ) -> tuple[bool, str, dict[str, list[str]] | None]:
        """Get all database objects grouped by type."""
        pass

    @abstractmethod
    def get_object_creation_sql(
        self, obj_name: str, obj_type: str, database: str = None
    ) -> tuple[bool, str, str | None]:
        """Get the creation SQL for a database object."""
        pass

    @abstractmethod
    def get_row_count(
        self, table: str, database: str = None
    ) -> tuple[bool, str, int | None]:
        """Get the row count for a table or view."""
        pass

    @abstractmethod
    def get_object_columns_detailed(
        self, table: str, database: str = None
    ) -> tuple[bool, str, list[tuple[str, str]] | None]:
        """Get columns with their types for a table or view.

        Returns a list of (column_name, column_type) tuples.
        """
        pass

    @abstractmethod
    def get_primary_keys(
        self, table: str, database: str = None
    ) -> tuple[bool, str, list[str] | None]:
        """Get the list of primary key column names for a table.

        Returns an empty list if the table has no primary key (or if it is
        a view). Order is preserved for composite keys.
        """
        pass

    @abstractmethod
    def quote_identifier(self, name: str) -> str:
        """Return the identifier quoted for the current engine."""
        pass
