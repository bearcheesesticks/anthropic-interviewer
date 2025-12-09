"""Database session management."""

from __future__ import annotations

from pathlib import Path
from typing import Generator, Optional, Union

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base

# Default database path
DEFAULT_DB_PATH = Path("./data/interviewer.db")

_engine = None
_SessionLocal = None

# Type alias for path arguments (Python 3.9 compatible)
PathLike = Optional[Union[Path, str]]


def get_engine(db_path: PathLike = None):
    """Get or create the database engine."""
    global _engine

    if _engine is None:
        db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        db_path.parent.mkdir(parents=True, exist_ok=True)

        _engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            connect_args={"check_same_thread": False},  # Needed for SQLite + FastAPI
        )

    return _engine


def get_session_factory(db_path: PathLike = None) -> sessionmaker:
    """Get the session factory."""
    global _SessionLocal

    if _SessionLocal is None:
        engine = get_engine(db_path)
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    return _SessionLocal


def init_db(db_path: PathLike = None) -> None:
    """Initialize the database, creating all tables."""
    engine = get_engine(db_path)
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Dependency for getting database sessions."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def reset_db(db_path: PathLike = None) -> None:
    """Reset the database (drop all tables and recreate)."""
    global _engine, _SessionLocal

    db_path = Path(db_path) if db_path else DEFAULT_DB_PATH

    # Close existing connections
    if _engine:
        _engine.dispose()
        _engine = None
        _SessionLocal = None

    # Delete database file if exists
    if db_path.exists():
        db_path.unlink()

    # Reinitialize
    init_db(db_path)
