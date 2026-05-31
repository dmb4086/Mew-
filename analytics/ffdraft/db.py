"""Postgres connection helpers (psycopg 3)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg

from .config import settings


@contextmanager
def connect(autocommit: bool = False) -> Iterator[psycopg.Connection]:
    """Yield a psycopg connection to the configured database.

    Usage::

        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select 1")
    """
    conn = psycopg.connect(settings.database_url, autocommit=autocommit)
    try:
        yield conn
        if not autocommit:
            conn.commit()
    except Exception:
        if not autocommit:
            conn.rollback()
        raise
    finally:
        conn.close()


def ping() -> bool:
    """Return True if the database is reachable."""
    with connect(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("select 1")
            return cur.fetchone() == (1,)
