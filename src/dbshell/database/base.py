import threading
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

DEFAULT_MAX_ROWS = 1000


class DatabaseAdapter(ABC):
    """Base class for database adapters following the adapter pattern."""

    def __init__(self, connection_params: dict[str, Any]):
        self.connection_params = connection_params
        self.connection = None
        self.current_database: str | None = None
        max_rows = connection_params.get("max_rows", DEFAULT_MAX_ROWS)
        if max_rows is None:
            max_rows = DEFAULT_MAX_ROWS
        # None disables the cap (CLI/UI expose it as 0 = "no limit").
        # Can be changed at runtime, e.g. from the app's limit selector.
        self.max_rows: int | None = int(max_rows) if int(max_rows) > 0 else None
        # True when the last executed query returned more rows than
        # ``max_rows`` and the result was cut off.
        self.last_result_truncated: bool = False
        # Serializes access to the shared connection/cursor, which is used
        # from worker threads as well as the UI thread. Reentrant because
        # some adapter methods call each other.
        self._lock = threading.RLock()

    @abstractmethod
    def connect(self) -> tuple[bool, str]:
        """Establish database connection."""
        pass

    @abstractmethod
    def execute_query(
        self, query: str, params: Sequence[Any] | None = None
    ) -> tuple[bool, str, list | None, list | None]:
        """Execute a single statement, optionally with bind parameters.

        Returns ``(success, message, columns, rows)``. At most
        ``max_rows`` rows are returned; ``last_result_truncated`` is set
        when the result was cut off.
        """
        pass

    @property
    @abstractmethod
    def param_placeholder(self) -> str:
        """Return the bind-parameter placeholder for this engine."""
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
