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
    _upgrade_extraction_columns(engine)
    _upgrade_response_plan_columns(engine)
    _upgrade_resource_columns(engine)


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


def _upgrade_extraction_columns(bind) -> None:
    """Add traceability fields to extraction tables created by older app versions."""
    from app.models.extraction import ReportExtraction

    inspector = inspect(bind)
    if "report_extractions" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("report_extractions")}
    if "evidence_spans" in existing:
        return

    preparer = bind.dialect.identifier_preparer
    table_name = preparer.quote("report_extractions")
    column_name = preparer.quote("evidence_spans")
    column_type = ReportExtraction.__table__.c.evidence_spans.type.compile(dialect=bind.dialect)
    with bind.begin() as connection:
        connection.execute(text(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
        ))


def _upgrade_response_plan_columns(bind) -> None:
    """Add FR-28/29 grounding fields to response_plans if missing in older databases."""
    from app.models.incident import ResponsePlan

    inspector = inspect(bind)
    if "response_plans" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("response_plans")}
    preparer = bind.dialect.identifier_preparer
    table_name = preparer.quote("response_plans")
    with bind.begin() as connection:
        for col_name in ("response_option", "constraints_considered", "rationale", "evidence"):
            if col_name not in existing:
                column = ResponsePlan.__table__.c[col_name]
                col_quoted = preparer.quote(col_name)
                col_type = column.type.compile(dialect=bind.dialect)
                connection.execute(text(
                    f"ALTER TABLE {table_name} ADD COLUMN {col_quoted} {col_type}"
                ))


def _upgrade_resource_columns(bind) -> None:
    """Add resource_type to registered_resources if missing in older databases."""
    from app.models.resource import RegisteredResource

    inspector = inspect(bind)
    if "registered_resources" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("registered_resources")}
    if "resource_type" in existing:
        return

    preparer = bind.dialect.identifier_preparer
    table_name = preparer.quote("registered_resources")
    column_name = preparer.quote("resource_type")
    column_type = RegisteredResource.__table__.c.resource_type.type.compile(dialect=bind.dialect)
    with bind.begin() as connection:
        connection.execute(text(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
        ))
