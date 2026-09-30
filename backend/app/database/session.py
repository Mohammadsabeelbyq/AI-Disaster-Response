"""SQLAlchemy engine/session. Swap DATABASE_URL for PostgreSQL in real deployments."""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings

_url = get_settings().database_url
engine = create_engine(
    _url, connect_args={"check_same_thread": False} if _url.startswith("sqlite") else {}
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Dev convenience. Replace with Alembic migrations once the schema owner sets them up."""
    import app.models  # noqa: F401  (register models)
    Base.metadata.create_all(bind=engine)
