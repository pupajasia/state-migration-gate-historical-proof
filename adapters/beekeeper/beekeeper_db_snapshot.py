#!/usr/bin/env python3
"""Read the small semantic Beekeeper witness from an application database."""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys
from typing import Any


class SnapshotError(ValueError):
    pass


def rows_as_dicts(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def snapshot_database(database_path: pathlib.Path, title: str) -> dict[str, Any]:
    resolved = database_path.resolve()
    if not resolved.is_file():
        raise SnapshotError(f"database not found: {resolved}")
    connection = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)
    try:
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check").fetchall()]
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            ).fetchall()
        ]
        tables_lower = {table.lower() for table in tables}
        for required in ("bk_migrations", "favorite_query", "tabs"):
            if required not in tables_lower:
                raise SnapshotError(f"required application table is missing: {required}")
        saved_queries = rows_as_dicts(
            connection.execute(
                "SELECT id, title, text, connectionHash "
                "FROM favorite_query WHERE title = ? ORDER BY id",
                (title,),
            )
        )
        linked_tabs: list[dict[str, Any]] = []
        if len(saved_queries) == 1:
            linked_tabs = rows_as_dicts(
                connection.execute(
                    "SELECT id, queryId, connectionId, unsavedChanges, unsavedQueryText "
                    "FROM tabs WHERE queryId = ? ORDER BY id",
                    (saved_queries[0]["id"],),
                )
            )
        migrations = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM BK_MIGRATIONS ORDER BY name"
            ).fetchall()
        ]
    except sqlite3.DatabaseError as exc:
        raise SnapshotError(f"SQLite read failed: {exc}") from exc
    finally:
        connection.close()
    return {
        "integrity": integrity,
        "tables": tables,
        "saved_queries": saved_queries,
        "linked_tabs": linked_tabs,
        "migrations": migrations,
        "migrations_unique": len(set(migrations)) == len(migrations),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read a Beekeeper state-gate database witness.")
    parser.add_argument("--database", type=pathlib.Path, required=True)
    parser.add_argument("--title", required=True)
    args = parser.parse_args()
    try:
        snapshot = snapshot_database(args.database, args.title)
    except (SnapshotError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
