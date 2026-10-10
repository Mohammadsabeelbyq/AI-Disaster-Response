"""SQLAlchemy engine/session. Swap DATABASE_URL for PostgreSQL in real deployments."""
from sqlalchemy import create_engine, inspect, text
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
    _upgrade_incident_columns(engine)


def _upgrade_incident_columns(bind) -> None:
    """Add newly introduced incident fields to databases created by older app versions."""
    from app.models.incident import Incident

    inspector = inspect(bind)
    if "incidents" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("incidents")}
    preparer = bind.dialect.identifier_preparer
    table_name = preparer.quote("incidents")
    with bind.begin() as connection:
        for column in Incident.__table__.columns:
            if column.name in existing or column.primary_key:
                continue

            column_name = preparer.quote(column.name)
            column_type = column.type.compile(dialect=bind.dialect)
            if column.name == "priority_is_overridden":
                default_value = "0" if bind.dialect.name == "sqlite" else "FALSE"
                definition = f"{column_type} NOT NULL DEFAULT {default_value}"
            else:
                definition = column_type
            for foreign_key in column.foreign_keys:
                target_table, target_column = foreign_key.target_fullname.split(".")[-2:]
                definition += (
                    f" REFERENCES {preparer.quote(target_table)}"
                    f" ({preparer.quote(target_column)})"
                )
                if foreign_key.ondelete:
                    definition += f" ON DELETE {foreign_key.ondelete}"
            connection.execute(text(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
            ))
