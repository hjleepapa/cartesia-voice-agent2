import os
import sqlite3
from datetime import datetime
from typing import List, Tuple

import psycopg2
from psycopg2.extensions import connection as PgConnection


class MemoryStore:
    def __init__(self, db_uri: str) -> None:
        self.db_uri = db_uri
        self._is_postgres = "://" in db_uri and not db_uri.startswith("sqlite")
        if not self._is_postgres:
            db_path = self._sqlite_path(db_uri)
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        if self._is_postgres:
            with self._pg_connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS memories (
                            id SERIAL PRIMARY KEY,
                            role TEXT NOT NULL,
                            content TEXT NOT NULL,
                            created_at TIMESTAMPTZ NOT NULL
                        )
                        """
                    )
                conn.commit()
            return

        with sqlite3.connect(self._sqlite_path(self.db_uri)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def add(self, role: str, content: str) -> None:
        if self._is_postgres:
            with self._pg_connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO memories (role, content, created_at) VALUES (%s, %s, %s)",
                        (role, content, datetime.utcnow()),
                    )
                conn.commit()
            return

        with sqlite3.connect(self._sqlite_path(self.db_uri)) as conn:
            conn.execute(
                "INSERT INTO memories (role, content, created_at) VALUES (?, ?, ?)",
                (role, content, datetime.utcnow().isoformat()),
            )
            conn.commit()

    def recent(self, limit: int = 8) -> List[Tuple[str, str]]:
        if self._is_postgres:
            with self._pg_connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT role, content FROM memories ORDER BY id DESC LIMIT %s",
                        (limit,),
                    )
                    rows = cursor.fetchall()
            return list(reversed(rows))

        with sqlite3.connect(self._sqlite_path(self.db_uri)) as conn:
            rows = conn.execute(
                "SELECT role, content FROM memories ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return list(reversed(rows))

    def _pg_connect(self) -> PgConnection:
        return psycopg2.connect(self.db_uri)

    @staticmethod
    def _sqlite_path(db_uri: str) -> str:
        if db_uri.startswith("sqlite:///"):
            return db_uri.replace("sqlite:///", "", 1)
        return db_uri
