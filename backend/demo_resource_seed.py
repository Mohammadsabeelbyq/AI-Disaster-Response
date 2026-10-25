"""Reset the local mock registry and seed test resources in four Kerala locations."""
from pathlib import Path

DEMO_DEPARTMENTS = (
    ("MOCK-FIRE", "Fire and Safety", "FIRE"),
    ("MOCK-MEDICAL", "Medical Response", "MEDICAL"),
    ("MOCK-POLICE", "Police Response", "POLICE"),
    ("MOCK-DISASTER", "Disaster Response", "DISASTER_MANAGEMENT"),
)

DEMO_LOCATIONS = {
    "THRIPPUNITHURA": (9.9516, 76.3490),
    "WAYANAD_KALPETTA": (11.6085, 76.0834),
    "KAKKANAD": (10.0159, 76.3419),
    "KOTTAYAM": (9.5916, 76.5222),
}

DEMO_RESOURCES = (
    ("THRIPPUNITHURA", "MOCK-FIRE", "MOCK-THR-FIRE-01", "Thrippunithura Fire & Safety Unit", "VEHICLE", ["FIRE", "FIRE_SUPPRESSION"], 9.9560, 76.3520),
    ("THRIPPUNITHURA", "MOCK-POLICE", "MOCK-THR-POLICE-01", "Thrippunithura Police Response Unit", "RESCUE_TEAM", ["POLICE", "EVACUATION", "RESCUE"], 9.9460, 76.3440),
    ("THRIPPUNITHURA", "MOCK-MEDICAL", "MOCK-THR-AMB-01", "Thrippunithura Ambulance 01", "VEHICLE", ["MEDICAL", "MEDICAL_AID", "TRANSPORT"], 9.9530, 76.3390),
    ("THRIPPUNITHURA", "MOCK-DISASTER", "MOCK-THR-RESCUE-01", "Thrippunithura Rescue Team 01", "RESCUE_TEAM", ["RESCUE", "SEARCH_AND_RESCUE", "WATER_RESCUE"], 9.9470, 76.3560),
    ("WAYANAD_KALPETTA", "MOCK-FIRE", "MOCK-WYD-FIRE-01", "Wayanad Fire & Safety Unit", "VEHICLE", ["FIRE", "FIRE_SUPPRESSION"], 11.6120, 76.0870),
    ("WAYANAD_KALPETTA", "MOCK-POLICE", "MOCK-WYD-POLICE-01", "Wayanad Police Response Unit", "RESCUE_TEAM", ["POLICE", "EVACUATION", "RESCUE"], 11.6030, 76.0790),
    ("WAYANAD_KALPETTA", "MOCK-MEDICAL", "MOCK-WYD-AMB-01", "Wayanad Ambulance 01", "VEHICLE", ["MEDICAL", "MEDICAL_AID", "TRANSPORT"], 11.6160, 76.0760),
    ("WAYANAD_KALPETTA", "MOCK-DISASTER", "MOCK-WYD-HELI-01", "Wayanad Helicopter Support Unit", "VEHICLE", ["AIR_RESCUE", "RESCUE", "SEARCH_AND_RESCUE", "TRANSPORT"], 11.6000, 76.0910),
    ("KAKKANAD", "MOCK-FIRE", "MOCK-KKD-FIRE-01", "Kakkanad Fire & Safety Unit", "VEHICLE", ["FIRE", "FIRE_SUPPRESSION"], 10.0200, 76.3470),
    ("KAKKANAD", "MOCK-POLICE", "MOCK-KKD-POLICE-01", "Kakkanad Police Response Unit", "RESCUE_TEAM", ["POLICE", "EVACUATION", "RESCUE"], 10.0100, 76.3370),
    ("KAKKANAD", "MOCK-MEDICAL", "MOCK-KKD-AMB-01", "Kakkanad Ambulance 01", "VEHICLE", ["MEDICAL", "MEDICAL_AID", "TRANSPORT"], 10.0240, 76.3330),
    ("KAKKANAD", "MOCK-DISASTER", "MOCK-KKD-RESCUE-01", "Kakkanad Rescue Team 01", "RESCUE_TEAM", ["RESCUE", "SEARCH_AND_RESCUE", "WATER_RESCUE"], 10.0060, 76.3490),
    ("KOTTAYAM", "MOCK-FIRE", "MOCK-KTM-FIRE-01", "Kottayam Fire & Safety Unit", "VEHICLE", ["FIRE", "FIRE_SUPPRESSION"], 9.5970, 76.5270),
    ("KOTTAYAM", "MOCK-POLICE", "MOCK-KTM-POLICE-01", "Kottayam Police Response Unit", "RESCUE_TEAM", ["POLICE", "EVACUATION", "RESCUE"], 9.5860, 76.5160),
    ("KOTTAYAM", "MOCK-MEDICAL", "MOCK-KTM-AMB-01", "Kottayam Ambulance 01", "VEHICLE", ["MEDICAL", "MEDICAL_AID", "TRANSPORT"], 9.6020, 76.5160),
    ("KOTTAYAM", "MOCK-DISASTER", "MOCK-KTM-RESCUE-01", "Kottayam Rescue Team 01", "RESCUE_TEAM", ["RESCUE", "SEARCH_AND_RESCUE", "WATER_RESCUE"], 9.5800, 76.5280),
)


def reset_and_seed_demo_resources(db, actor_id):
    """Replace registry records with mock data; preserve assignments by refusing if present."""
    from sqlalchemy import or_, select

    from app.models.resources import Department, Resource, ResourceAssignment
    from app.services.resource_service import create_department, create_resource

    assigned_resource = db.scalar(
        select(ResourceAssignment.id).limit(1)
    )
    if assigned_resource is not None:
        raise RuntimeError(
            "Resource assignments exist. Release/resolve assignments before resetting "
            "the registry; assignment history is preserved."
        )

    current_resources = db.scalars(select(Resource)).all()
    non_mock_resources = [
        resource.code for resource in current_resources
        if not resource.code.startswith(("MOCK-", "DEMO-"))
    ]
    if non_mock_resources:
        raise RuntimeError(
            "Reset stopped because non-demo resources are registered: "
            + ", ".join(sorted(non_mock_resources))
        )

    for resource in current_resources:
        db.delete(resource)
    db.flush()

    for department in db.scalars(
        select(Department).where(or_(
            Department.code.like("MOCK-%"),
            Department.code == "DEMO-RESPONSE",
        ))
    ).all():
        db.delete(department)
    db.commit()

    departments = {
        code: create_department(
            db,
            actor_id,
            code=code,
            name=name,
            department_type=department_type,
        )
        for code, name, department_type in DEMO_DEPARTMENTS
    }

    seeded = []
    for _location, department_code, code, name, resource_type, capabilities, latitude, longitude in DEMO_RESOURCES:
        seeded.append(create_resource(
            db,
            actor_id,
            code=code,
            department_id=departments[department_code].id,
            resource_type=resource_type,
            name=name,
            capabilities=capabilities,
            latitude=latitude,
            longitude=longitude,
            availability="AVAILABLE",
        ))
    return seeded


def main():
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")

    from app.config import get_settings

    if not get_settings().database_url.startswith("sqlite:"):
        raise SystemExit("Demo resource reset is restricted to SQLite databases.")

    from sqlalchemy import select

    from app.database import SessionLocal, init_db
    from app.models.user import User

    init_db()
    with SessionLocal() as db:
        administrator = db.scalar(
            select(User).where(User.role == "ADMIN", User.is_active.is_(True))
            .order_by(User.created_at).limit(1)
        )
        if administrator is None:
            raise SystemExit(
                "No active ADMIN account exists. Start the backend once to provision "
                "the configured local demo accounts, then retry."
            )
        try:
            seeded = reset_and_seed_demo_resources(db, administrator.id)
        except RuntimeError as error:
            raise SystemExit(str(error)) from error

        print(f"Mock resource registry reset: {len(seeded)} resources registered.")
        for name, coordinates in DEMO_LOCATIONS.items():
            count = sum(1 for row in DEMO_RESOURCES if row[0] == name)
            print(f"{name}: {count} resource(s) near {coordinates[0]}, {coordinates[1]}")
        print("Seeded resources use MOCK- registry codes to identify non-operational demo records.")


if __name__ == "__main__":
    main()
