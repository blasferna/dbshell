# DBShell - TUI SQL Query Editor

A simple Text User Interface (TUI) application for executing SQL queries against MySQL databases or SQLite database files.

![screenshot](https://github.com/user-attachments/assets/0d57cde4-4264-45f4-b179-1727d4e2638d)

> [!WARNING]
> This project is in early development. Currently the code is a bit messy, Prs are welcome!

## Features
* Connect to MySQL databases and SQLite database files
* Execute SQL queries in a background thread, so the UI stays responsive; the Results panel shows the row count and elapsed time
* Run multi-statement scripts: statements separated by `;` execute sequentially, the last result set is displayed, and execution stops at the first failing statement
* Row limit for SELECTs (default 1000): the toolbar **LIMIT** dropdown appends `LIMIT N` to SELECT statements that do not already have one, so large tables do not flood the UI. Pick **No LIMIT** to turn it off, or set the initial value with `--max-rows` (`0` disables it). A fetch safety net also caps results if a query asks for more rows than the current limit.
* View query results in a tabular format (switch between horizontal and vertical views with **Ctrl+T**)
* Edit the currently selected record (Ctrl+U): opens an in-place form pre-filled with the row's values, runs an `UPDATE` against the table, and refreshes the results automatically. The source table is auto-detected from simple `SELECT ... FROM <table>` queries and primary-key columns are used to build the `WHERE` clause.
* Add a new record (Ctrl+N): opens a blank form for the current source table (one Input per column), runs an `INSERT`, and refreshes the results, jumping to the newly added row. Primary-key columns start with their **NULL** box ticked so auto-increment/default values can apply; untick it to supply a value manually. Works even when the table has zero rows — you only need a source table, not an existing record. Also available from the Database Explorer's **Add Record** action, which works on any table without running a SELECT first.
* Delete the active record (Ctrl+Shift+D): opens a confirmation dialog and, if confirmed, runs a `DELETE` against the source table using the primary-key columns and refreshes the results. Requires the table to have a primary key and the key columns to be present in the current result set.
* Copy the active row as JSON to the clipboard (Ctrl+J). Works in both horizontal and vertical view; the output is a pretty-printed object keyed by column name.
* Export the current result set (Ctrl+Shift+E, or the **Export** button): opens a modal where you pick a format — **JSON**, **CSV**, **TSV**, **Markdown**, or **INSERT SQL** (the last one is available only when the source table is known) — and a destination (clipboard or file path). The file path is pre-filled with a timestamped default under your home directory.
* Smart SQL autocomplete powered by `textual-textarea`, with fuzzy matching, keyword/function/table/column suggestions, and table-qualified column completions.
* Suggestions for SQL keywords and table/column names.
* Database explorer (Ctrl+E): browse tables, views, procedures and functions. Press **Enter** on any object to open a context menu with actions:
  * **View Data** — inserts a `SELECT * FROM <object>;` into the editor (press F8 to run).
  * **Add Record** — opens a blank insert form for the table and runs an `INSERT`, without needing a SELECT to be loaded first.
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

Both modes accept `--max-rows N` to set the initial SELECT row limit (default: 1000, `0` = no limit). While the app is running, change or disable it with the **LIMIT** dropdown in the toolbar. Queries that already include their own `LIMIT` are left alone.

## Development

```
uv sync --dev
uv run ruff check .
uv run pytest
```
