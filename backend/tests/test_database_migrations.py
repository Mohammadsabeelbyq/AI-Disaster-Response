from sqlalchemy import create_engine, inspect, text

from app.database.session import _upgrade_incident_columns
from app.models.incident import Incident


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