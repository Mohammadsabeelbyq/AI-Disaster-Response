from datetime import datetime

from app.models.report import IncidentReport
from app.services.incident_tracking import ensure_report_tracking_metadata, generate_incident_id


def test_generate_incident_id_returns_unique_uuid():
    first_id = generate_incident_id()
    second_id = generate_incident_id()

    assert first_id != second_id
    assert str(first_id)
    assert str(second_id)


def test_ensure_report_tracking_metadata_sets_id_and_timestamp():
    report = IncidentReport(
        disaster_type="FLOOD",
        description="Roads are underwater near the station.",
        latitude=10.0,
        longitude=76.3,
    )

    report = ensure_report_tracking_metadata(report)

    assert report.id is not None
    assert report.submitted_at is not None
    assert isinstance(report.submitted_at, datetime)
