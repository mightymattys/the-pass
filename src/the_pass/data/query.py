"""Read-only DuckDB query facade over immutable Parquet partitions."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable


SAFE_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DuckDBQueryLayer:
    """Query Parquet directly without creating a mutable analytical database."""

    def scan(
        self,
        paths: Iterable[Path],
        *,
        columns: Iterable[str] = ("*",),
        where: str | None = None,
        parameters: tuple[Any, ...] = (),
    ) -> list[dict[str, Any]]:
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError("DuckDB queries require the 'data' extra") from exc
        resolved = [str(path.resolve()) for path in paths]
        if not resolved:
            raise ValueError("at least one Parquet path is required")
        selected = list(columns)
        if not selected or any(column != "*" and not SAFE_COLUMN.fullmatch(column) for column in selected):
            raise ValueError("columns must be simple identifiers or '*'")
        if where and ";" in where:
            raise ValueError("where clause must contain one expression")
        projection = ", ".join(f'"{column}"' if column != "*" else "*" for column in selected)
        query = f"SELECT {projection} FROM read_parquet(?)"
        if where:
            query += f" WHERE {where}"
        connection = duckdb.connect(":memory:")
        try:
            cursor = connection.execute(query, (resolved, *parameters))
            names = [description[0] for description in cursor.description]
            return [dict(zip(names, row)) for row in cursor.fetchall()]
        finally:
            connection.close()
