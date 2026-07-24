"""Autocomplete completers compatible with textual-textarea."""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dbshell.suggestions.keywords import AGGREGATE_FUNCTIONS, ALL_KEYWORDS

if TYPE_CHECKING:
    from dbshell.database import DatabaseAdapter


SEPARATOR_PROG = re.compile(r"\.|::?")
ANY_QUOTE_PROG = re.compile(r'["\'`]')
TYPE_PREFIXES = {
    "kw": "kw",
    "fn": "fn",
    "tbl": "t",
    "col": "c",
}


@dataclass(order=False)
class Completion:
    """A single autocomplete suggestion."""

    label: str
    type_label: str
    value: str
    priority: int
    context: str | None = None

    def __lt__(self, other: Completion) -> bool:
        return (self.priority, self.label) < (other.priority, other.label)

    def __le__(self, other: Completion) -> bool:
        return (self.priority, self.label) <= (other.priority, other.label)

    def __gt__(self, other: Completion) -> bool:
        return (self.priority, self.label) > (other.priority, other.label)

    def __ge__(self, other: Completion) -> bool:
        return (self.priority, self.label) >= (other.priority, other.label)

    @property
    def match_val(self) -> str:
        return self.label.lower()


class WordCompleter:
    """General-purpose completer for keywords, functions, tables, and columns."""

    def __init__(self, db_connection: DatabaseAdapter | None = None) -> None:
        self._db_connection = db_connection
        self._keyword_completions = self._build_keywords()
        self._function_completions = self._build_functions()
        self._schema_completions: list[Completion] = []
        self.completions: list[Completion] = []
        self._rebuild_completions()

    def __call__(self, prefix: str) -> list[tuple[str, str]]:
        """Return matching completions for the given prefix."""
        match_val = prefix.lower()
        matches: list[tuple[str, str]] = []

        # Exact matches
        matches.extend(
            self._to_pair(c) for c in self.completions if c.match_val == match_val
        )
        # Prefix matches
        matches.extend(
            self._to_pair(c)
            for c in self.completions
            if c.match_val.startswith(match_val)
        )
        # Fuzzy matches if there are not enough results
        if len(matches) < 20:
            matches.extend(
                self._to_pair(c) for c in self._fuzzy_match(match_val, self.completions)
            )

        return self._dedupe(matches)

    def update_schema(self) -> None:
        """Reload schema objects from the database connection."""
        self.set_schema(self.build_schema_completions())

    def build_schema_completions(self) -> list[Completion]:
        """Fetch tables/columns from the database and build completions.

        Safe to call from a worker thread; install the result with
        ``set_schema`` afterwards.
        """
        return self._build_schema_completions()

    def set_schema(self, completions: list[Completion]) -> None:
        """Install pre-built schema completions."""
        self._schema_completions = completions
        self._rebuild_completions()

    def clear_schema(self) -> None:
        """Clear schema-dependent completions (e.g., when disconnected)."""
        self._schema_completions = []
        self._rebuild_completions()

    @staticmethod
    def _to_pair(completion: Completion) -> tuple[str, str]:
        prefix = TYPE_PREFIXES.get(completion.type_label, completion.type_label)
        prompt = f"[dim]{prefix}[/dim] {completion.label}"
        return (prompt, completion.value)

    @staticmethod
    def _build_keywords() -> list[Completion]:
        return [
            Completion(label=kw, type_label="kw", value=kw, priority=100)
            for kw in ALL_KEYWORDS
        ]

    @staticmethod
    def _build_functions() -> list[Completion]:
        return [
            Completion(label=fn, type_label="fn", value=fn, priority=200)
            for fn in AGGREGATE_FUNCTIONS
        ]

    def _build_schema_completions(self) -> list[Completion]:
        """Build completions for tables and columns from the database schema."""
        if self._db_connection is None:
            return []

        completions: list[Completion] = []
        try:
            tables, _ = self._db_connection.get_tables()
        except Exception:
            return []

        for table in tables:
            completions.append(
                Completion(label=table, type_label="tbl", value=table, priority=300)
            )
            try:
                columns = self._db_connection.get_columns(table)
            except Exception:
                continue
            for column in columns:
                completions.append(
                    Completion(
                        label=column,
                        type_label="col",
                        value=column,
                        priority=400,
                        context=table,
                    )
                )

        return completions

    def _rebuild_completions(self) -> None:
        self.completions = [
            c
            for c in sorted(
                itertools.chain(
                    self._keyword_completions,
                    self._function_completions,
                    self._schema_completions,
                )
            )
        ]

    @staticmethod
    def _fuzzy_match(match_val: str, completions: list[Completion]) -> list[Completion]:
        regex_base = ".{0,2}?".join(f"({re.escape(c)})" for c in match_val)
        regex = "^.*" + regex_base + ".*$"
        match_regex = re.compile(regex, re.IGNORECASE)
        matches = [c for c in completions if match_regex.match(c.match_val)]
        matches.sort(key=lambda c: len(c.match_val))
        return matches

    @staticmethod
    def _dedupe(matches: list[tuple[str, str]]) -> list[tuple[str, str]]:
        seen: set[str] = set()
        result: list[tuple[str, str]] = []
        for prompt, value in matches:
            if prompt not in seen:
                seen.add(prompt)
                result.append((prompt, value))
        return result


class MemberCompleter(WordCompleter):
    """Completer for member access like table.column or alias.column."""

    def __call__(self, prefix: str) -> list[tuple[str, str]]:
        """Return matching member completions for the given prefix."""
        try:
            *_, context, item_prefix = SEPARATOR_PROG.split(prefix)
        except ValueError:
            return []

        quote_match = ANY_QUOTE_PROG.match(item_prefix)
        if quote_match is not None:
            match_val = item_prefix[1:].lower()
        else:
            match_val = item_prefix.lower()

        match_context = context.strip("'`\"").lower()

        context_completions = [
            c
            for c in self.completions
            if c.context and c.context.lower() == match_context
        ]

        matches: list[tuple[str, str]] = []
        matches.extend(
            self._to_pair(c) for c in context_completions if c.match_val == match_val
        )
        matches.extend(
            self._to_pair(c)
            for c in context_completions
            if c.match_val.startswith(match_val)
        )
        if len(matches) < 20:
            matches.extend(
                self._to_pair(c)
                for c in self._fuzzy_match(match_val, context_completions)
            )

        return self._dedupe(matches)

    def _rebuild_completions(self) -> None:
        """Keep only schema completions that have a context (table-qualified)."""
        self.completions = [
            c for c in sorted(itertools.chain(self._schema_completions)) if c.context
        ]
