"""Database connection and session factory with SQLite PRAGMA enforcement."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy ORM models."""
    pass


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
    """Enforce SQLite foreign key constraints and WAL journal mode when connected to SQLite."""
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        except Exception:
            pass


def get_engine(database_url: str | None = None):
    """Create SQLAlchemy engine with appropriate pooling and connection settings."""
    if database_url is None:
        database_url = get_settings().database_url

    connect_args = {}
    engine_kwargs: dict[str, Any] = {"echo": False}

    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        engine_kwargs["connect_args"] = connect_args
    elif database_url.startswith("postgresql"):
        # Pilot PostgreSQL production pooling configuration
        engine_kwargs["pool_size"] = 10
        engine_kwargs["max_overflow"] = 20
        engine_kwargs["pool_pre_ping"] = True

    return create_engine(
        database_url,
        **engine_kwargs,
    )


engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding an isolated database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(target_engine: Engine | None = None) -> None:
    """Create all database tables defined in metadata."""
    if target_engine is None:
        target_engine = engine
    Base.metadata.create_all(bind=target_engine)
