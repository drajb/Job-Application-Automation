"""SQLAlchemy session + sqlite-vec extension loading.

Use get_engine() once per process and create sessions from it. sqlite-vec is
loaded via SQLAlchemy event hook so every connection has the vec0 virtual table
available before queries.
"""

from __future__ import annotations

from functools import lru_cache

import sqlite_vec
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from src.config import DB_PATH


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{DB_PATH}",
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _load_extensions(dbapi_conn, _conn_record):
        dbapi_conn.enable_load_extension(True)
        sqlite_vec.load(dbapi_conn)
        dbapi_conn.enable_load_extension(False)
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        # The IMAP worker, scheduler and pipeline share the DB — wait briefly on
        # a lock instead of failing with "database is locked".
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return engine


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


def get_session() -> Session:
    return _session_factory()()
