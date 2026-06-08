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
* Database explorer (Ctrl+E): browse tables, views, procedures and functions. Press **Enter** on any object to open a context menu with actions:
  * **View Data** — inserts a `SELECT * FROM <object>;` into the editor (press F8 to run).
  * **Insert Template** — inserts `INSERT INTO <object> (col1, col2, ...) VALUES (?, ?, ...);`.
  * **Update Template** — inserts `UPDATE <object> SET col1 = ?, col2 = ? WHERE ...;`.
  * **Delete Template** — inserts `DELETE FROM <object> WHERE ...;`.
  * **Copy Name** — copies the object name to the clipboard.
  * **Copy CREATE SQL** — copies the `CREATE` statement to the clipboard.
  Available actions vary by object type (tables support all of them; views only support View Data and copies; procedures/functions only support copies).

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
