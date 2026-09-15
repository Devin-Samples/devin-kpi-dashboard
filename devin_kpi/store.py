"""SQLite persistence layer (stdlib sqlite3 + pandas)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    org_id TEXT,
    user_id TEXT,
    status TEXT,
    title TEXT,
    tags_json TEXT,
    created_at INTEGER,
    updated_at INTEGER,
    acus_consumed REAL,
    origin TEXT,
    category TEXT,
    subcategory TEXT,
    playbook_id TEXT,
    automation_id TEXT,
    devin_mode TEXT,
    is_archived INTEGER,
    parent_session_id TEXT,
    service_user_id TEXT,
    status_detail TEXT,
    url TEXT,
    repo_names_json TEXT,
    raw_json TEXT
);
CREATE TABLE IF NOT EXISTS session_prs (
    session_id TEXT,
    pr_url TEXT PRIMARY KEY,
    pr_state TEXT,
    provider TEXT,
    repo_full_name TEXT,
    pr_number INTEGER,
    pr_created_at INTEGER,
    merged_at INTEGER,
    closed_at INTEGER,
    review_comments INTEGER,
    review_rounds INTEGER,
    additions INTEGER,
    deletions INTEGER,
    enriched_at INTEGER
);
CREATE TABLE IF NOT EXISTS session_insights (
    session_id TEXT PRIMARY KEY,
    num_user_messages INTEGER,
    num_devin_messages INTEGER,
    session_size TEXT,
    analysis_json TEXT
);
CREATE TABLE IF NOT EXISTS session_issues (
    session_id TEXT,
    issue_key TEXT,
    tracker TEXT,
    story_points REAL,
    fetched_at INTEGER,
    PRIMARY KEY (session_id, issue_key)
);
CREATE TABLE IF NOT EXISTS metrics_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint TEXT,
    scope TEXT,
    params_json TEXT,
    window_start INTEGER,
    window_end INTEGER,
    fetched_at INTEGER,
    payload_json TEXT
);
CREATE TABLE IF NOT EXISTS consumption_daily (
    scope TEXT,
    scope_id TEXT,
    date TEXT,
    product TEXT,
    acus REAL,
    PRIMARY KEY (scope, scope_id, date, product)
);
CREATE TABLE IF NOT EXISTS billing_cycles (
    cycle_start INTEGER PRIMARY KEY,
    cycle_end INTEGER,
    raw_json TEXT
);
CREATE TABLE IF NOT EXISTS code_scan_metrics (
    window_start INTEGER,
    window_end INTEGER,
    fetched_at INTEGER,
    payload_json TEXT
);
CREATE TABLE IF NOT EXISTS audit_logs (
    event_id TEXT PRIMARY KEY,
    occurred_at INTEGER,
    event_type TEXT,
    actor TEXT,
    raw_json TEXT
);
CREATE TABLE IF NOT EXISTS collector_runs (
    window_start INTEGER,
    window_end INTEGER,
    endpoint TEXT,
    status TEXT,
    completed_at INTEGER,
    PRIMARY KEY (window_start, window_end, endpoint)
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self.init_schema()

    def init_schema(self) -> None:
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after the initial schema to existing DBs."""
        for col in ("is_archived", "parent_session_id", "service_user_id", "status_detail", "url"):
            try:
                self._conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass  # column already exists

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Store:  # noqa: PYI034
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- write helpers -------------------------------------------------

    def upsert(self, table: str, row: dict[str, Any]) -> None:
        """INSERT ... ON CONFLICT DO UPDATE so re-runs are idempotent."""
        cols = list(row)
        placeholders = ", ".join(f":{c}" for c in cols)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols)
        sql = (
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT DO UPDATE SET {updates}"
        )
        self._conn.execute(sql, row)

    def upsert_many(self, table: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        cols = list(rows[0])
        placeholders = ", ".join(f":{c}" for c in cols)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols)
        sql = (
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT DO UPDATE SET {updates}"
        )
        self._conn.executemany(sql, rows)

    def insert_snapshot(self, row: dict[str, Any]) -> None:
        cols = list(row)
        sql = f"INSERT INTO metrics_snapshots ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        self._conn.execute(sql, [row[c] for c in cols])

    def delete_snapshots(self, endpoint: str, window_start: int, window_end: int) -> None:
        self._conn.execute(
            "DELETE FROM metrics_snapshots WHERE endpoint=? AND window_start=? AND window_end=?",
            (endpoint, window_start, window_end),
        )

    def snapshot_exists(self, endpoint: str, window_start: int, window_end: int) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM metrics_snapshots WHERE endpoint=? AND window_start=? AND window_end=? LIMIT 1",
            (endpoint, window_start, window_end),
        )
        return cur.fetchone() is not None

    def commit(self) -> None:
        self._conn.commit()

    # --- collector run bookkeeping --------------------------------------

    def run_done(self, window_start: int, window_end: int, endpoint: str) -> bool:
        cur = self._conn.execute(
            "SELECT status FROM collector_runs WHERE window_start=? AND window_end=? AND endpoint=?",
            (window_start, window_end, endpoint),
        )
        row = cur.fetchone()
        return bool(row and row[0] == "done")

    def mark_run(
        self, window_start: int, window_end: int, endpoint: str, status: str, completed_at: int
    ) -> None:
        self.upsert(
            "collector_runs",
            {
                "window_start": window_start,
                "window_end": window_end,
                "endpoint": endpoint,
                "status": status,
                "completed_at": completed_at,
            },
        )

    # --- meta ------------------------------------------------------------

    def set_meta(self, key: str, value: str) -> None:
        self.upsert("meta", {"key": key, "value": value})

    def get_meta(self, key: str) -> str | None:
        cur = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else None

    # --- reads -----------------------------------------------------------

    def read_df(self, table: str, where: str | None = None, params: tuple = ()) -> pd.DataFrame:
        sql = f"SELECT * FROM {table}"
        if where:
            sql += f" WHERE {where}"
        return pd.read_sql_query(sql, self._conn, params=params)

    def count(self, table: str) -> int:
        return self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def unenriched_prs(self) -> pd.DataFrame:
        return self.read_df("session_prs", "enriched_at IS NULL AND provider IS NOT NULL")

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)
