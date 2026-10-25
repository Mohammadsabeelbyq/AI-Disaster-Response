import json
import uuid

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.database.session import (
    Base,
    _migrate_legacy_resources,
    _upgrade_extraction_columns,
    _upgrade_incident_columns,
    _upgrade_response_plan_columns,
    _upgrade_resource_registry_columns,
)
from app.models.incident import Incident
from app.models.resources import Department, Resource, ResourceAvailabilityEvent


def test_upgrade_adds_priority_columns_to_legacy_incidents_table():
    test_engine = create_engine("sqlite:///:memory:")
    try:
        with test_engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE incidents ("
                "id CHAR(32) PRIMARY KEY, report_id CHAR(32) NOT NULL UNIQUE, "
                "status VARCHAR(30) NOT NULL, confirmed_by CHAR(32) NOT NULL, "
                "confirmed_at DATETIME NOT NULL)"
            ))

        _upgrade_incident_columns(test_engine)

        columns = {column["name"] for column in inspect(test_engine).get_columns("incidents")}
        expected = {column.name for column in Incident.__table__.columns}
        assert expected <= columns

        with test_engine.connect() as connection:
            result = connection.execute(text(
                "SELECT priority_is_overridden FROM incidents"
            ))
            assert result.keys() == ["priority_is_overridden"]
    finally:
        test_engine.dispose()


def test_upgrade_adds_evidence_spans_to_legacy_extractions_table():
    test_engine = create_engine("sqlite:///:memory:")
    try:
        with test_engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE report_extractions (id CHAR(32) PRIMARY KEY, "
                "report_id CHAR(32) NOT NULL UNIQUE)"
            ))

        _upgrade_extraction_columns(test_engine)

        columns = {column["name"] for column in inspect(test_engine).get_columns("report_extractions")}
        assert "evidence_spans" in columns
    finally:
        test_engine.dispose()


def test_upgrade_adds_planner_attribution_to_legacy_response_plans():
    test_engine = create_engine("sqlite:///:memory:")
    try:
        with test_engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE response_plans (id CHAR(32) PRIMARY KEY)"
            ))
            connection.execute(text(
                "INSERT INTO response_plans (id) VALUES (:id)"
            ), {"id": uuid.uuid4().hex})

        _upgrade_response_plan_columns(test_engine)
        columns = {column["name"] for column in inspect(test_engine).get_columns("response_plans")}
        assert {"planner_provider", "planner_model"} <= columns
        with test_engine.connect() as connection:
            row = connection.execute(text(
                "SELECT planner_provider, planner_model FROM response_plans"
            )).one()
            assert row == ("DETERMINISTIC", None)
    finally:
        test_engine.dispose()


def test_legacy_resources_migrate_once_and_remain_ineligible_until_assigned():
    test_engine = create_engine("sqlite:///:memory:")
    resource_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    try:
        Base.metadata.create_all(test_engine)
        with test_engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE registered_resources ("
                "id CHAR(32) PRIMARY KEY, name VARCHAR(160) NOT NULL, "
                "resource_type VARCHAR(50), latitude NUMERIC, longitude NUMERIC, "
                "capabilities JSON NOT NULL, status VARCHAR(20) NOT NULL, "
                "created_by CHAR(32) NOT NULL, created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL)"
            ))
            connection.execute(text(
                "INSERT INTO registered_resources VALUES "
                "(:id, :name, :resource_type, :latitude, :longitude, :capabilities, "
                ":status, :created_by, :created_at, :updated_at)"
            ), {
                "id": resource_id.hex,
                "name": "Unassigned legacy boat",
                "resource_type": None,
                "latitude": None,
                "longitude": None,
                "capabilities": json.dumps(["WATER_RESCUE"]),
                "status": "AVAILABLE",
                "created_by": actor_id.hex,
                "created_at": "2025-01-01 00:00:00",
                "updated_at": "2025-01-01 00:00:00",
            })

        _migrate_legacy_resources(test_engine)
        _migrate_legacy_resources(test_engine)

        with Session(bind=test_engine) as db:
            migrated = db.get(Resource, resource_id)
            department = db.get(Department, migrated.department_id)
            events = list(db.scalars(select(ResourceAvailabilityEvent)))
            assert migrated.name == "Unassigned legacy boat"
            assert migrated.resource_type is None
            assert migrated.latitude is None and migrated.longitude is None
            assert migrated.capabilities == ["WATER_RESCUE"]
            assert migrated.availability == "AVAILABLE"
            assert department.code == "LEGACY_UNASSIGNED"
            assert department.is_active is False
            assert len(events) == 1
            assert "Assign this resource" in events[0].reason

        assert "registered_resources" not in inspect(test_engine).get_table_names()
    finally:
        test_engine.dispose()


def test_registry_migration_allows_unknown_legacy_type_and_location():
    test_engine = create_engine("sqlite:///:memory:")
    try:
        with test_engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE resources ("
                "id CHAR(32) PRIMARY KEY, code VARCHAR(30) NOT NULL, "
                "department_id CHAR(32) NOT NULL, resource_type VARCHAR(50) NOT NULL, "
                "name VARCHAR(150) NOT NULL, capabilities JSON NOT NULL, "
                "latitude NUMERIC NOT NULL, longitude NUMERIC NOT NULL, "
                "availability VARCHAR(20) NOT NULL, created_by CHAR(32) NOT NULL, "
                "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
            ))
            connection.execute(text(
                "INSERT INTO resources VALUES (:id, :code, :department_id, :resource_type, "
                ":name, :capabilities, :latitude, :longitude, :availability, :created_by, "
                ":created_at, :updated_at)"
            ), {
                "id": uuid.uuid4().hex,
                "code": "RES-OLD-01",
                "department_id": uuid.uuid4().hex,
                "resource_type": "SUPPLY",
                "name": "Old resource",
                "capabilities": "[]",
                "latitude": 10,
                "longitude": 76,
                "availability": "AVAILABLE",
                "created_by": uuid.uuid4().hex,
                "created_at": "2025-01-01 00:00:00",
                "updated_at": "2025-01-01 00:00:00",
            })

        _upgrade_resource_registry_columns(test_engine)
        columns = {column["name"]: column for column in inspect(test_engine).get_columns("resources")}
        assert columns["resource_type"]["nullable"] is True
        assert columns["latitude"]["nullable"] is True
        assert columns["longitude"]["nullable"] is True
        with test_engine.connect() as connection:
            row = connection.execute(text("SELECT code, name FROM resources")).one()
            assert row == ("RES-OLD-01", "Old resource")
    finally:
        test_engine.dispose()