# AI Disaster Response – Core Engine

## Incident Reporting module (Epic 1: stories 1.1 and 1.2)

Lets a user submit an incident through a web form, or bulk-import JSON / CSV, with an optional photo.
Every accepted record becomes its own row in `incident_reports` (status `SUBMITTED`).

**Run it** (from `backend/`):
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload      # then open http://localhost:8000/report-form
pytest                             # run the tests
```
The React workspace lives in `frontend/`. For frontend development, start the backend as above, then run `npm install` and `npm run dev` from `frontend/`; open the URL printed by Vite. To serve a production build through FastAPI, run `npm run build` in `frontend/` and restart the backend. Frontend structure and extension conventions are documented in `frontend/README.md`.
Config lives in `backend/app/config.py` (override with env vars, see `backend/.env.example`).
Default DB is SQLite for zero-setup dev; set `DATABASE_URL` to PostgreSQL for the real thing.

### Where things are
| Concern | File |
|---|---|
| HTTP endpoints (thin) | `backend/app/api/reports.py` |
| Create / read reports (**only place that writes reports**) | `backend/app/services/report_service.py` |
| JSON / CSV parsing + per-record results | `backend/app/services/import_service.py` |
| Image validation + file storage | `backend/app/services/media_service.py` |
| Error types → HTTP status | `backend/app/services/errors.py`, `app/main.py` |
| Validation rules / disaster types / image types | `backend/app/schemas/report.py`, `backend/app/config.py` |
| Tables `incident_reports`, `incident_media` | `backend/app/models/report.py` |
| React frontend | `frontend/src/` (served at `/`; `/report-form` remains a compatibility route) |
| FAISS / semantic search | `backend/app/faiss_search/` |
| Placeholder for the logged-in user (replace with JWT) | `backend/app/api/deps.py` |

### Endpoints
| Method | Path | Purpose |
|---|---|---|
| POST | `/reports` | Submit one report (multipart form, optional `image`) |
| POST | `/reports/import/json` | Bulk import, JSON body |
| POST | `/reports/import/csv` | Bulk import, CSV body (`Content-Type: text/csv`) |
| POST | `/reports/{id}/media` | Attach an image to an existing report |
| GET | `/reports`, `/reports/{id}`, `/reports/{id}/image` | Read (placeholders – add ownership/RBAC) |

**Report fields** (from the Master Plan §7.1): `disaster_type` (FLOOD, FIRE, EARTHQUAKE, LANDSLIDE, CYCLONE,
ROAD_ACCIDENT, BUILDING_COLLAPSE, MEDICAL_EMERGENCY, OTHER), `description`, `latitude` (-90..90),
`longitude` (-180..180) are required; `location_name` is optional.

```bash
curl -F disaster_type=FLOOD -F "description=Water entered houses" \
     -F latitude=10.027 -F longitude=76.308 -F location_name=Edappally \
     -F image=@photo.jpg http://localhost:8000/reports
```
Success → `201` with the report (`id`, `status`, `submitted_at`, `image` or `null`).
Failure → `{"message": "Invalid report.", "errors": ["description is required", ...]}`
(`422` validation, `413` image too large, `415` unsupported image, `400` malformed import, `500` storage failure – generic message, details only in server logs).

### JSON import
```bash
curl -X POST localhost:8000/reports/import/json -H 'Content-Type: application/json' -d '[
  {"disaster_type":"FIRE","description":"Fire in a building","latitude":10.0,"longitude":76.3},
  {"disaster_type":"FLOOD","description":"","latitude":10.1,"longitude":76.2},
  {"disaster_type":"FLOOD","description":"Road under water","latitude":10.2,"longitude":76.1}]'
```
Accepts an array, a single object, or `{"reports": [...]}`. Response (HTTP 200):
```json
{"total":3,"accepted":2,"rejected":1,"results":[
  {"record":1,"status":"accepted","reportId":"…"},
  {"record":2,"status":"rejected","errors":["description is required"]},
  {"record":3,"status":"accepted","reportId":"…"}]}
```
Records are validated and saved **independently** – a bad record never blocks or rolls back good ones.

### CSV import
```csv
disaster_type,description,latitude,longitude,location_name
FIRE,Fire reported in a building,10.0,76.3,Kochi
FLOOD,"Water rising, road blocked",10.1,76.2,
```
`curl -X POST localhost:8000/reports/import/csv -H 'Content-Type: text/csv' --data-binary @reports.csv`
Same response as JSON; `record` = data row number (header not counted). A missing required column,
unparseable CSV or non-UTF-8 file returns `400` and nothing is stored. Limit: 1000 records (`MAX_IMPORT_RECORDS`).

### Image upload
- Formats: **JPEG, PNG, WebP**. Max **5 MB** (`MAX_IMAGE_BYTES`). Change in `app/config.py`.
- Type is detected from the file's bytes, not just the filename/content-type.
- An invalid image rejects the whole submission (nothing is saved). No image is fine.
- Stored under `UPLOAD_DIR/incident_media/<random>.<ext>` (user filenames are never used as paths).
- Linked via `incident_media.report_id` → `incident_reports.id` (metadata: mime, size, sha256, path).
  `report.image` gives the image; the file is served from `GET /reports/{id}/image`.

### FAISS (semantic search) – separate module, not used by submission code
Code is in `backend/app/faiss_search/` (named `faiss_search`, not `faiss`, so it can't shadow the library).
Enable with `pip install faiss-cpu sentence-transformers`.
```python
from app.faiss_search import service
service.add_report(report.id, report.searchable_text)      # embed + add one report
hits = service.search("water entering houses", k=5)         # [(report_id, score), ...]
service.rebuild(report_service.list_reports(db, limit=10000))   # full rebuild
```
`embeddings.py` = text→vector, `index.py` = FAISS index + save/load, `service.py` = the only API to call.
Hook it up wherever you like (e.g. after `create_report`); the submission code does not import it.
Note: the design docs list *pgvector* for similarity – FAISS was requested, so it is kept isolated and easy to swap.

### Notes for teammates
- **Auth/RBAC:** `submitted_by` is `NULL` until `api/deps.py::get_current_user_id` is wired to JWT.
- **Schema:** tables are created by `init_db()` for dev; move to Alembic and add the `users` FK when that exists.
- **Not done here (other owners):** incident creation from a report, priority, PostGIS, review workflow, video upload, `/reports/my`.
