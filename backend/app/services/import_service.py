"""IMPORT SERVICE - parses JSON / CSV and reports accepted vs rejected records.
It never touches the database directly: every valid record goes through
report_service.create_report(), each in its own transaction, so one bad record
never blocks (or rolls back) the good ones."""
import csv
import io
import json

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.schemas.report import ImportRecordResult, ImportSummary, ReportCreate
from app.services import report_service
from app.services.errors import AppError, ImportFormatError

REQUIRED_COLUMNS = ("disaster_type", "description", "latitude", "longitude")


# ---------- parsing (whole-file problems raise ImportFormatError) ----------
def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportFormatError("File is not valid UTF-8 text.") from exc


def parse_json(raw: bytes) -> list:
    """Accepts a JSON array of records, a single record object, or {"reports": [...]}."""
    try:
        payload = json.loads(_decode(raw))
    except json.JSONDecodeError as exc:
        raise ImportFormatError(
            "Malformed JSON.", [f"line {exc.lineno}, column {exc.colno}: {exc.msg}"]) from exc
    if isinstance(payload, dict) and isinstance(payload.get("reports"), list):
        payload = payload["reports"]
    elif isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        raise ImportFormatError("JSON must be an array of report objects.")
    return payload


def parse_csv(raw: bytes) -> list:
    """Returns one dict per data row. A str item means the row itself is malformed."""
    text = _decode(raw)
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        header = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        if not header or missing:
            raise ImportFormatError(
                "CSV header is missing required column(s).",
                [f"missing column: {c}" for c in missing] or ["CSV has no header row"])
        reader.fieldnames = header
        rows: list = []
        for row in reader:
            if None in row:  # more cells than header columns
                rows.append("row has more values than the header has columns")
            else:
                rows.append(row)
    except csv.Error as exc:
        raise ImportFormatError("Malformed CSV.", [str(exc)]) from exc
    return rows


# ---------- importing ----------
def format_validation_errors(exc: ValidationError) -> list[str]:
    errors = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"]) or "record"
        if err["type"] == "missing":
            errors.append(f"{field} is required")
        else:
            errors.append(f"{field}: {err['msg'].removeprefix('Value error, ')}")
    return errors


def _import_one(db: Session, index: int, record) -> ImportRecordResult:
    def rejected(errors: list[str]) -> ImportRecordResult:
        return ImportRecordResult(record=index, status="rejected", errors=errors)

    if isinstance(record, str):
        return rejected([record])
    if not isinstance(record, dict):
        return rejected(["record must be a JSON object"])
    # Blank CSV cells / nulls count as "not provided".
    record = {k: v for k, v in record.items() if v not in (None, "")}
    try:
        data = ReportCreate.model_validate(record)
    except ValidationError as exc:
        return rejected(format_validation_errors(exc))
    try:
        report = report_service.create_report(db, data)
    except AppError as exc:
        return rejected([exc.message])
    return ImportRecordResult(record=index, status="accepted", reportId=report.id)


def import_records(db: Session, records: list) -> ImportSummary:
    limit = get_settings().max_import_records
    if not records:
        raise ImportFormatError("The import contains no records.")
    if len(records) > limit:
        raise ImportFormatError(f"Too many records ({len(records)}). Limit is {limit} per import.")
    results = [_import_one(db, i, rec) for i, rec in enumerate(records, start=1)]
    accepted = sum(r.status == "accepted" for r in results)
    return ImportSummary(
        total=len(results), accepted=accepted, rejected=len(results) - accepted, results=results)


def import_json(db: Session, raw: bytes) -> ImportSummary:
    return import_records(db, parse_json(raw))


def import_csv(db: Session, raw: bytes) -> ImportSummary:
    return import_records(db, parse_csv(raw))
