# DBShell - TUI SQL Query Editor

A simple Text User Interface (TUI) application for executing SQL queries against MySQL databases.

![screenshot](https://github.com/user-attachments/assets/5831a3d0-d619-4e66-a6fc-c1ab8cba9ab4)

> [!WARNING]
> This project is in early development. Currently the code is a bit messy, Prs are welcome!

## Features
* Connect to MySQL databases
* Execute SQL queries
* View query results in a tabular format (you can switch between horizontal and vertical views)
* Suggestions for SQL keywords and table/column names.

## Installation

```
uv tool install git+https://github.com/blasferna/dbshell.git
```

## Usage

```
dbshell --host <hostname> --user <username> --password <password> [--database <database_name>] [--port <port>]
``` 

