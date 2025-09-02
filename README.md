# DBShell - TUI SQL Query Editor

A simple yet powerful Text User Interface (TUI) application for executing SQL queries against MySQL databases. Built with Python using the Textual framework.

## Features

- **Interactive SQL Editor**: Multi-line SQL query editor with syntax highlighting
- **Query Execution**: Execute queries with Ctrl+E or click the Execute button
- **Result Visualization**: View query results in a scrollable data table
- **Error Handling**: Clear error messages for connection and query issues
- **Keyboard Shortcuts**: 
  - `Ctrl+E`: Execute query
  - `Ctrl+Q` or `Ctrl+C`: Quit application

## Installation

1. **Install dependencies**:
   ```bash
   pip install textual mysql-connector-python
   ```

   Or if using this project with pyproject.toml:
   ```bash
   pip install -e .
   ```

## Usage

Run the application with database connection parameters:

```bash
python main.py --host localhost --user root --password yourpass --database testdb
```

### Command Line Arguments

- `--host`: Database host (required)
- `--user, -u`: Database username (required) 
- `--password, -p`: Database password (required)
- `--database, -d`: Database name (required)
- `--port`: Database port (default: 3306)

### Example

```bash
# Connect to local MySQL
python main.py --host localhost --user root --password mypassword --database sakila

# Connect to remote MySQL with custom port
python main.py --host 192.168.1.100 --user admin --password secret --database production --port 3307
```

## Application Layout

The application consists of two main sections:

1. **SQL Query Editor (Top)**: 
   - Text area with SQL syntax highlighting
   - Line numbers
   - Execute button

2. **Query Results (Bottom)**:
   - Data table showing query results
   - Scrollable for large result sets
   - Shows column headers and data

## Supported Query Types

- **SELECT**: Results displayed in the data table
- **INSERT/UPDATE/DELETE**: Shows number of affected rows
- **DDL statements**: CREATE, ALTER, DROP, etc.

## Error Handling

- Connection errors are displayed as notifications
- SQL syntax errors show the database error message
- Empty queries are prevented with user feedback

## Dependencies

- `textual>=0.41.0`: TUI framework
- `mysql-connector-python>=8.0.33`: MySQL database connector

## License

This project is open source. Feel free to modify and distribute.