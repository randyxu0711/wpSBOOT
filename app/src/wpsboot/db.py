from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from wpsboot.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(get_engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transaction for background code: commit on success, roll back on error."""
    with get_sessionmaker()() as session, session.begin():
        yield session


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with get_sessionmaker()() as session:
        yield session
