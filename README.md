# DBShell - TUI SQL Query Editor

A simple Text User Interface (TUI) application for executing SQL queries against MySQL databases or SQLite database files.

![screenshot](https://github.com/user-attachments/assets/0d57cde4-4264-45f4-b179-1727d4e2638d)

> [!WARNING]
> This project is in early development. Currently the code is a bit messy, Prs are welcome!

## Features
* Connect to MySQL databases and SQLite database files
* Execute SQL queries
* View query results in a tabular format (you can switch between horizontal and vertical views)
* Suggestions for SQL keywords and table/column names.

## Installation

```
uv tool install git+https://github.com/blasferna/dbshell.git
```

## Usage

`MySQL Mode` - Connect to a MySQL database using host, user, and password:

```
dbshell --host <hostname> --user <username> --password <password> [--database <database_name>] [--port <port>]
``` 

`SQLite Mode` - Connect to a SQLite database file:

```
dbshell <path_to_sqlite_db_file>
```
