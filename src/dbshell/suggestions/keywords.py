"""SQL keywords and constants for autocompletion."""

# DML Keywords (Data Manipulation)
DML_KEYWORDS = [
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "MERGE",
    "REPLACE",
]

# DDL Keywords (Data Definition)
DDL_KEYWORDS = [
    "CREATE",
    "ALTER",
    "DROP",
    "TRUNCATE",
    "RENAME",
]

# Clause Keywords
CLAUSE_KEYWORDS = [
    "FROM",
    "WHERE",
    "SET",
    "VALUES",
    "INTO",
    "JOIN",
    "INNER",
    "LEFT",
    "RIGHT",
    "OUTER",
    "CROSS",
    "ON",
    "USING",
    "GROUP",
    "BY",
    "ORDER",
    "HAVING",
    "LIMIT",
    "OFFSET",
    "UNION",
    "INTERSECT",
    "EXCEPT",
    "AS",
    "DISTINCT",
    "ALL",
]

# Object Keywords
OBJECT_KEYWORDS = [
    "TABLE",
    "DATABASE",
    "SCHEMA",
    "INDEX",
    "VIEW",
    "PROCEDURE",
    "FUNCTION",
    "TRIGGER",
    "CONSTRAINT",
    "COLUMN",
    "PRIMARY",
    "FOREIGN",
    "KEY",
    "REFERENCES",
    "CASCADE",
]

# Logical/Comparison Keywords
LOGICAL_KEYWORDS = [
    "AND",
    "OR",
    "NOT",
    "IN",
    "EXISTS",
    "BETWEEN",
    "LIKE",
    "IS",
    "NULL",
    "TRUE",
    "FALSE",
    "CASE",
    "WHEN",
    "THEN",
    "ELSE",
    "END",
]

# Aggregate Functions
AGGREGATE_FUNCTIONS = [
    "COUNT",
    "SUM",
    "AVG",
    "MIN",
    "MAX",
    "GROUP_CONCAT",
    "COALESCE",
    "NULLIF",
    "IFNULL",
]

# Data Types
DATA_TYPES = [
    "INT",
    "INTEGER",
    "BIGINT",
    "SMALLINT",
    "TINYINT",
    "DECIMAL",
    "NUMERIC",
    "FLOAT",
    "DOUBLE",
    "REAL",
    "VARCHAR",
    "CHAR",
    "TEXT",
    "BLOB",
    "DATE",
    "TIME",
    "DATETIME",
    "TIMESTAMP",
    "BOOLEAN",
    "BOOL",
]

# All keywords combined
ALL_KEYWORDS = (
    DML_KEYWORDS
    + DDL_KEYWORDS
    + CLAUSE_KEYWORDS
    + OBJECT_KEYWORDS
    + LOGICAL_KEYWORDS
    + AGGREGATE_FUNCTIONS
    + DATA_TYPES
)

# Statement starters - keywords that typically start a SQL statement
STATEMENT_STARTERS = [
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "CREATE",
    "ALTER",
    "DROP",
    "TRUNCATE",
    "SHOW",
    "DESCRIBE",
    "EXPLAIN",
    "USE",
]

# Keywords that introduce table contexts
TABLE_CONTEXT_KEYWORDS = [
    "FROM",
    "JOIN",
    "INTO",
    "UPDATE",
    "TABLE",
]

# Keywords that introduce column contexts
COLUMN_CONTEXT_KEYWORDS = [
    "SELECT",
    "WHERE",
    "ON",
    "SET",
    "ORDER BY",
    "GROUP BY",
    "HAVING",
]
