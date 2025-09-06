from typing import Any

from .base import DatabaseAdapter
from .mysql_adapter import MySQLAdapter


class DatabaseFactory:
    """Factory for creating database adapter instances."""

    _adapters = {
        "mysql": MySQLAdapter,
        "mariadb": MySQLAdapter,
    }

    @classmethod
    def create_adapter(
        cls, engine: str, connection_params: dict[str, Any]
    ) -> DatabaseAdapter:
        """Create a database adapter instance."""
        engine = engine.lower()
        if engine not in cls._adapters:
            raise ValueError(f"Unsupported database engine: {engine}")

        adapter_class = cls._adapters[engine]
        return adapter_class(connection_params)

    @classmethod
    def get_supported_engines(cls) -> list:
        """Get list of supported database engines."""
        return list(cls._adapters.keys())
