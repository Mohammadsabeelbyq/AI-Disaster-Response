"""User Story 1.1 - JSON / CSV import, including mixed validity."""
from tests.conftest import rec
import json

JSON_URL, CSV_URL = "/reports/import/json", "/reports/import/csv"
CSV_HEADER = "disaster_type,description,latitude,longitude,location_name\n"


def post_json(client, payload):
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return client.post(JSON_URL, content=body, headers={"Content-Type": "application/json"})


def post_csv(client, text):
    return client.post(CSV_URL, content=text, headers={"Content-Type": "text/csv"})


def stored(client):
    return client.get("/reports").json()


# ---------------- JSON ----------------
def test_json_single_valid_record(client):
    r = post_json(client, rec())
    assert r.status_code == 200
    assert (r.json()["total"], r.json()["accepted"], r.json()["rejected"]) == (1, 1, 0)


def test_json_multiple_valid_records_are_distinct_reports(client):
    r = post_json(client, [rec(), rec(disaster_type="FLOOD"), rec(description="Third")])
    body = r.json()
    ids = {x["reportId"] for x in body["results"]}
    assert body["accepted"] == 3 and len(ids) == 3
    assert {x["id"] for x in stored(client)} == ids


def test_json_mixed_validity(client):
    r = post_json(client, [rec(), rec(description=""), rec(disaster_type="FLOOD")])
    body = r.json()
    assert (body["total"], body["accepted"], body["rejected"]) == (3, 2, 1)
    a, b, c = body["results"]
    assert a["status"] == "accepted" and a["reportId"]
    assert b["record"] == 2 and b["status"] == "rejected" and "description is required" in b["errors"]
    assert c["status"] == "accepted" and c["reportId"] != a["reportId"]
    assert len(stored(client)) == 2          # the rejected record was NOT stored


def test_json_non_object_record_rejected_others_kept(client):
    body = post_json(client, [rec(), "just a string", rec()]).json()
    assert [x["status"] for x in body["results"]] == ["accepted", "rejected", "accepted"]


def test_json_wrapped_in_reports_key(client):
    assert post_json(client, {"reports": [rec(), rec()]}).json()["accepted"] == 2


def test_malformed_json(client):
    r = post_json(client, '[{"disaster_type": "FIRE",')
    assert r.status_code == 400 and r.json()["message"] == "Malformed JSON."
    assert stored(client) == []


def test_json_empty_and_wrong_shape(client):
    assert post_json(client, []).status_code == 400
    assert post_json(client, "42").status_code == 400


# ---------------- CSV ----------------
def test_csv_valid_and_distinct(client):
    text = CSV_HEADER + "Fire,Fire reported in a building,10.0,76.3,Kochi\nFLOOD,Water rising,10.1,76.2,\n"
    body = post_csv(client, text).json()
    assert (body["total"], body["accepted"], body["rejected"]) == (2, 2, 0)
    assert len({x["reportId"] for x in body["results"]}) == 2
    assert {x["disaster_type"] for x in stored(client)} == {"FIRE", "FLOOD"}


def test_csv_quoted_commas_and_newlines(client):
    text = CSV_HEADER + 'FIRE,"Smoke, flames\nand a crowd",10,76,\n'
    body = post_csv(client, text).json()
    assert body["accepted"] == 1
    assert "Smoke, flames\nand a crowd" == stored(client)[0]["description"]


def test_csv_mixed_validity_identifies_rows(client):
    text = (CSV_HEADER
            + "FIRE,Building fire,10.0,76.3,\n"
            + "FLOOD,,10.0,76.3,\n"                 # row 2: no description
            + "FLOOD,Water rising,999,76.3,\n"       # row 3: bad latitude
            + "FIRE,Second fire,11.0,76.0,\n")
    body = post_csv(client, text).json()
    assert (body["total"], body["accepted"], body["rejected"]) == (4, 2, 2)
    by_row = {x["record"]: x for x in body["results"]}
    assert by_row[1]["status"] == "accepted" and by_row[4]["status"] == "accepted"
    assert "description is required" in by_row[2]["errors"]
    assert any(e.startswith("latitude") for e in by_row[3]["errors"])
    assert len(stored(client)) == 2


def test_csv_row_with_too_many_values_rejected(client):
    text = CSV_HEADER + "FIRE,ok,10,76,x,EXTRA\nFIRE,ok,10,76,\n"
    body = post_csv(client, text).json()
    assert [x["status"] for x in body["results"]] == ["rejected", "accepted"]


def test_csv_missing_required_column(client):
    r = post_csv(client, "disaster_type,description\nFIRE,x\n")
    assert r.status_code == 400
    assert "missing column: latitude" in r.json()["errors"]
    assert stored(client) == []


def test_csv_malformed(client):
    r = post_csv(client, CSV_HEADER + 'FIRE,"unterminated,10,76,\n')
    assert r.status_code == 400 and "CSV" in r.json()["message"]


def test_csv_binary_and_empty(client):
    assert post_csv(client, "").status_code == 400
    r = client.post(CSV_URL, content=b"\xff\xfe\x00\x01", headers={"Content-Type": "text/csv"})
    assert r.status_code == 400


def test_csv_utf8_bom_header(client):
    text = "\ufeff" + CSV_HEADER + "FIRE,Bâtiment en feu,10,76,\n"
    assert post_csv(client, text.encode("utf-8")).json()["accepted"] == 1
