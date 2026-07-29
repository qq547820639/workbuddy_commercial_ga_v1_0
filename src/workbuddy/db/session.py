from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from workbuddy.settings import settings
from .models import Base


def make_engine(database_url: str | None = None):
    url = database_url or settings.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, future=True, connect_args=connect_args)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_fk(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def init_db(target_engine=None) -> None:
    Base.metadata.create_all(target_engine or engine)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def apply_tenant_context(session: Session, tenant_id: str, *, local: bool = True) -> None:
    session.info["tenant_id"] = tenant_id
    if session.bind and session.bind.dialect.name == "postgresql":
        session.execute(
            text("SELECT set_config('app.tenant_id', :tid, :local)"),
            {"tid": tenant_id, "local": local},
        )


def clear_tenant_context(session: Session) -> None:
    session.info.pop("tenant_id", None)
    if session.bind and session.bind.dialect.name == "postgresql":
        session.execute(text("SELECT set_config('app.tenant_id', '', false)"))
