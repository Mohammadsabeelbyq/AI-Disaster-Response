# AI Disaster Response – Core Engine

## Incident Reporting and Understanding (Epics 1 and 2)

Users can submit incidents through a web form or bulk-import JSON / CSV, with optional photo evidence.
Every accepted record becomes its own `incident_reports` row (status `SUBMITTED`) with a unique UUID and UTC submission timestamp. A separate `report_extractions` row stores evidence-linked, confidence-scored text facts. Original source fields are never overwritten by extraction or coordinator corrections.

Epic 1 stories 1.1–1.5 and Epic 2 stories 2.1–2.5 are implemented. Text understanding uses deterministic, versioned rules and does not require a model API. Image analysis is advisory and opt-in; without configuration the report is still accepted and its extraction reports `DISABLED`.

**Run it** (from `backend/`):
```bash
pip install -r requirements.txt
Copy-Item .env.example .env  # configure AUTH_SECRET_KEY and local demo account passwords
uvicorn app.main:app --reload      # then open http://localhost:8000/ to sign in
pytest                             # run the tests
```
Authenticate first to save a cookie jar, then pass it with protected requests:
```bash
curl -c cookies.txt -X POST localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"user@demo.test","password":"<local demo password>","role":"USER"}'
```
The React workspace lives in `frontend/`. For frontend development, start the backend as above, then run `npm install` and `npm run dev` from `frontend/`; open the URL printed by Vite. To serve a production build through FastAPI, run `npm run build` in `frontend/` and restart the backend. Frontend structure and extension conventions are documented in `frontend/README.md`.
Config lives in `backend/app/config.py` (override with env vars, see `backend/.env.example`).
Default DB is SQLite for zero-setup dev; set `DATABASE_URL` to PostgreSQL for the real thing.

### Where things are
| Concern | File |
|---|---|
| HTTP endpoints (thin) | `backend/app/api/reports.py` |
| Create / read reports (**only place that writes reports**) | `backend/app/services/report_service.py` |
| Text extraction, evidence, optional image cues, corrections | `backend/app/services/extraction_service.py` |
| JSON / CSV parsing + per-record results | `backend/app/services/import_service.py` |
| Image validation + file storage | `backend/app/services/media_service.py` |
| Error types → HTTP status | `backend/app/services/errors.py`, `app/main.py` |
| Validation rules / disaster types / image types | `backend/app/schemas/report.py`, `backend/app/config.py` |
| Tables `incident_reports`, `incident_media` | `backend/app/models/report.py` |
| Extraction and review history | `backend/app/models/extraction.py` |
| React frontend | `frontend/src/` (served at `/`; `/report-form` remains a compatibility route) |
| FAISS / semantic search | `backend/app/faiss_search/` |
| Session authentication and current user | `backend/app/api/auth.py`, `backend/app/api/deps.py` |

### Endpoints
| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/login` | Verify credentials and selected role; sets an HTTP-only session cookie |
| GET | `/auth/me` | Read the current authenticated account |
| POST | `/auth/logout` | Clear the session cookie |
| POST | `/reports` | Submit one report (multipart form, optional `image`) |
| POST | `/reports/import/json` | Bulk import, JSON body |
| POST | `/reports/import/csv` | Bulk import, CSV body (`Content-Type: text/csv`) |
| POST | `/reports/{id}/media` | Attach an image to an existing report |
| GET | `/reports`, `/reports/{id}`, `/reports/{id}/image` | Read; USER is limited to owned reports |

**Report fields** (from the Master Plan §7.1): `disaster_type` (FLOOD, FIRE, EARTHQUAKE, LANDSLIDE, CYCLONE,
ROAD_ACCIDENT, BUILDING_COLLAPSE, MEDICAL_EMERGENCY, OTHER), `description`, `latitude` (-90..90),
`longitude` (-180..180) are required; `location_name` is optional.

```bash
curl -F disaster_type=FLOOD -F "description=Water entered houses" \
     -F latitude=10.027 -F longitude=76.308 -F location_name=Edappally \
      -F image=@photo.jpg -b cookies.txt http://localhost:8000/reports
```
  Report and import endpoints require a session cookie from `/auth/login`.
Success → `201` with the report (`id`, `status`, `submitted_at`, `image` or `null`).
Failure → `{"message": "Invalid report.", "errors": ["description is required", ...]}`
(`422` validation, `413` image too large, `415` unsupported image, `400` malformed import, `500` storage failure – generic message, details only in server logs).
The response also includes `extraction`: extracted facts, per-field confidence (0–1), source evidence, image-analysis status, optional advisory image cues, and any coordinator correction history. A missing confidence entry means the extractor did not find sufficient evidence for that field. Downstream workflows should consume `extraction.effective_facts`, which selects corrected values when present and otherwise uses the original extraction.

### Coordinator review (Epics 1.5 and 2.4–2.5)
`MANAGEMENT` and `ADMIN` accounts can open the **Review** workspace to compare the original submission with extracted facts, evidence and confidence. Corrections are saved separately and retain before/after snapshots, actor and timestamp; the original description and first-pass extraction remain unchanged. The API is `PATCH /reports/{id}/extraction` with `{"facts": { ... }}`. Reporters receive `403` for correction attempts.

### Optional image understanding (Epic 2.3)
The default is off and no external service is required for Epics 1, 2.1, 2.2, 2.4 or 2.5. To enable advisory image cues, set `ENABLE_IMAGE_ANALYSIS=true`, provide a Google Gemini API key as `GEMINI_API_KEY`, and optionally override `GEMINI_MODEL` (default `gemini-2.5-flash`). Only attached images are sent to Gemini. Each returned cue includes confidence and evidence text, and remains linked to the attached image. Calls have a timeout; failures are recorded as `FAILED` and do not reject a report. When enabled, image bytes leave this deployment, so configure this only after approving the provider and data-handling policy. No API key is needed from you for the rest of Epic 2.

### JSON import
```bash
curl -b cookies.txt -X POST localhost:8000/reports/import/json -H 'Content-Type: application/json' -d '[
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
`curl -b cookies.txt -X POST localhost:8000/reports/import/csv -H 'Content-Type: text/csv' --data-binary @reports.csv`
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
- **Auth/RBAC:** Report and import endpoints require a signed session. `USER` accounts can view their own reports; `MANAGEMENT` and `ADMIN` can view all submitted reports. Add role checks to operational endpoints as those modules are implemented.
- **Local demo accounts:** Configure `DEMO_USER_*`, `DEMO_COORDINATOR_*`, and `DEMO_ADMIN_*` in the ignored `backend/.env`. Never commit that file or reuse demo passwords in production. Set `AUTH_COOKIE_SECURE=true` behind HTTPS.
- **Schema:** tables are created by `init_db()` for dev; move to Alembic and add the `submitted_by` foreign key to `users.id`.
- **Not done here (other owners):** incident creation from a report, priority, PostGIS, review workflow, video upload, `/reports/my`.
