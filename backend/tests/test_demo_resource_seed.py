import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.resources import Department, Resource
from app.models.user import User
from demo_resource_seed import (
    DEMO_LOCATIONS,
    DEMO_RESOURCES,
    reset_and_seed_demo_resources,
)


def test_demo_registry_resets_and_seeds_mock_fleet_at_each_location(client):
    with SessionLocal() as db:
        administrator = db.scalar(select(User).where(User.role == "ADMIN"))
        old_department = db.scalar(select(Department).where(
            Department.code == "DEMO-RESPONSE"
        ))
        if old_department is None:
            old_department = Department(
                code="DEMO-RESPONSE",
                name="MOCK Old Demo Department",
                department_type="DISASTER_MANAGEMENT",
                created_by=administrator.id,
            )
            db.add(old_department)
            db.commit()
        db.add(Resource(
            code="DEMO-OLD-RESOURCE",
            department_id=old_department.id,
            resource_type="VEHICLE",
            name="MOCK Old Demo Resource",
            capabilities=["RESCUE"],
            latitude=9.8,
            longitude=76.9,
            availability="AVAILABLE",
            created_by=administrator.id,
        ))
        db.commit()

        resources = reset_and_seed_demo_resources(db, administrator.id)
        persisted_resources = list(db.scalars(select(Resource)).all())
        departments = list(db.scalars(select(Department)).all())

    assert len(resources) == 16
    assert len(persisted_resources) == len(DEMO_RESOURCES) == 16
    assert len(departments) == 4
    assert all(resource.code.startswith("MOCK-") for resource in resources)
    assert all(not resource.name.startswith("MOCK ") for resource in resources)
    assert all(resource.availability == "AVAILABLE" for resource in resources)
    assert {location for location, *_ in DEMO_RESOURCES} == set(DEMO_LOCATIONS)
    assert {resource.resource_type for resource in resources} == {"VEHICLE", "RESCUE_TEAM"}
    for location in DEMO_LOCATIONS:
        assert sum(1 for row in DEMO_RESOURCES if row[0] == location) == 4


def test_demo_registry_reset_refuses_non_mock_resources(client):
    with SessionLocal() as db:
        administrator = db.scalar(select(User).where(User.role == "ADMIN"))
        department = Department(
            code="REAL-OPS",
            name="Existing Operations",
            department_type="DISASTER_MANAGEMENT",
            created_by=administrator.id,
        )
        db.add(department)
        db.flush()
        resource = Resource(
            code="OPS-001",
            department_id=department.id,
            resource_type="VEHICLE",
            name="Existing response unit",
            capabilities=["RESCUE"],
            latitude=9.8,
            longitude=76.9,
            availability="AVAILABLE",
            created_by=administrator.id,
        )
        db.add(resource)
        db.commit()

        with pytest.raises(RuntimeError, match="non-demo resources"):
            reset_and_seed_demo_resources(db, administrator.id)
        assert db.get(Resource, resource.id) is not None
