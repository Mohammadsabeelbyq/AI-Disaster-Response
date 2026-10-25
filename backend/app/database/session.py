"""SQLAlchemy engine/session. Swap DATABASE_URL for PostgreSQL in real deployments."""
import base64
import json
import uuid

from sqlalchemy import MetaData, String, Table, create_engine, inspect, insert, select, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

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
    _upgrade_resource_registry_columns(engine)
    _migrate_legacy_resources(engine)


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
        for col_name in (
            "response_option", "constraints_considered", "rationale", "evidence",
            "planner_provider", "planner_model",
        ):
            if col_name not in existing:
                column = ResponsePlan.__table__.c[col_name]
                col_quoted = preparer.quote(col_name)
                col_type = column.type.compile(dialect=bind.dialect)
                default = " DEFAULT 'DETERMINISTIC' NOT NULL" if col_name == "planner_provider" else ""
                connection.execute(text(
                    f"ALTER TABLE {table_name} ADD COLUMN {col_quoted} {col_type}{default}"
                ))


def _upgrade_resource_columns(bind) -> None:
    """Add resource_type to registered_resources if missing in older databases."""
    inspector = inspect(bind)
    if "registered_resources" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("registered_resources")}
    if "resource_type" in existing:
        return

    preparer = bind.dialect.identifier_preparer
    table_name = preparer.quote("registered_resources")
    column_name = preparer.quote("resource_type")
    column_type = String(50).compile(dialect=bind.dialect)
    with bind.begin() as connection:
        connection.execute(text(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
        ))


def _upgrade_resource_registry_columns(bind) -> None:
    """Allow migrated resources to keep genuinely unknown legacy fields as NULL."""
    from app.models.resources import Department, Resource
    from app.models.user import User

    if "resources" not in inspect(bind).get_table_names():
        return
    columns = {column["name"]: column for column in inspect(bind).get_columns("resources")}
    nullable_fields = ("resource_type", "latitude", "longitude")
    if all(columns[name]["nullable"] for name in nullable_fields):
        return

    if bind.dialect.name == "postgresql":
        preparer = bind.dialect.identifier_preparer
        with bind.begin() as connection:
            for name in nullable_fields:
                if not columns[name]["nullable"]:
                    connection.execute(text(
                        f"ALTER TABLE {preparer.quote('resources')} "
                        f"ALTER COLUMN {preparer.quote(name)} DROP NOT NULL"
                    ))
        return

    if bind.dialect.name != "sqlite":
        raise RuntimeError("Resource nullability migration is not implemented for this database.")

    source = Table("resources", MetaData(), autoload_with=bind)
    target_metadata = MetaData()
    User.__table__.to_metadata(target_metadata)
    Department.__table__.to_metadata(target_metadata)
    replacement = Resource.__table__.to_metadata(
        target_metadata, name="resources_nullable_new")
    for index in replacement.indexes:
        if index.name:
            index.name = f"{index.name}_nullable_new"

    with bind.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        try:
            with connection.begin():
                replacement.create(connection)
                names = [column.name for column in Resource.__table__.columns]
                connection.execute(
                    insert(replacement).from_select(names, select(*(source.c[name] for name in names)))
                )
                connection.exec_driver_sql('DROP TABLE "resources"')
                connection.exec_driver_sql(
                    'ALTER TABLE "resources_nullable_new" RENAME TO "resources"'
                )
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()


def _migrate_legacy_resources(bind) -> None:
    """Move standalone legacy resources into the department-owned registry once."""
    from app.models.resources import Department, Resource, ResourceAvailabilityEvent

    if "registered_resources" not in inspect(bind).get_table_names():
        return

    legacy_table = Table("registered_resources", MetaData(), autoload_with=bind)
    with Session(bind=bind, expire_on_commit=False) as db:
        legacy_rows = list(db.execute(
            select(legacy_table).order_by(legacy_table.c.created_at)
        ).mappings())
        if not legacy_rows:
            legacy_table.drop(bind)
            return

        legacy_department = db.scalar(
            select(Department).where(Department.code == "LEGACY_UNASSIGNED")
        )
        if legacy_department is None:
            legacy_department = Department(
                code="LEGACY_UNASSIGNED",
                name="Unassigned migrated resources",
                department_type="DISASTER_MANAGEMENT",
                is_active=False,
                created_by=_uuid_value(legacy_rows[0]["created_by"]),
            )
            db.add(legacy_department)
            db.flush()

        for legacy in legacy_rows:
            legacy_id = _uuid_value(legacy["id"])
            if db.get(Resource, legacy_id) is not None:
                continue

            availability = legacy["status"].upper()
            if availability not in {
                "AVAILABLE", "BUSY", "DEPLOYED", "UNAVAILABLE", "ASSIGNED", "INACTIVE", "MAINTENANCE",
            }:
                availability = "UNAVAILABLE"

            code_suffix = base64.urlsafe_b64encode(legacy_id.bytes).decode("ascii").rstrip("=")
            resource = Resource(
                id=legacy_id,
                code=f"LEGACY-{code_suffix}",
                department_id=legacy_department.id,
                resource_type=legacy["resource_type"],
                name=legacy["name"],
                capabilities=(
                    json.loads(legacy["capabilities"])
                    if isinstance(legacy["capabilities"], str)
                    else legacy["capabilities"] or []
                ),
                latitude=legacy["latitude"],
                longitude=legacy["longitude"],
                availability=availability,
                created_by=_uuid_value(legacy["created_by"]),
                created_at=legacy["created_at"],
                updated_at=legacy["updated_at"],
            )
            db.add(resource)
            db.flush()
            db.add(ResourceAvailabilityEvent(
                resource_id=resource.id,
                changed_by=_uuid_value(legacy["created_by"]),
                previous_availability=None,
                new_availability=availability,
                reason=(
                    "Migrated from the legacy resource table. Assign this resource "
                    "to an active department before operational use."
                ),
                changed_at=legacy["created_at"],
            ))

        db.commit()
    legacy_table.drop(bind)


def _uuid_value(value):
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
