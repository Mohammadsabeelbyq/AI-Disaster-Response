# AI Disaster Response – Core Engine

## Incident Reporting, Understanding, and Coordinator Workflow

Users can submit incidents through a web form or bulk-import JSON / CSV, with optional photo evidence. The web form asks Groq to analyze the narrative before submission, then lets the user review and edit each proposed fact. If Groq is unavailable, fields remain unknown and can be entered manually; no rule-based injury inference is used in the web intake flow. Bulk imports and legacy backfills retain their deterministic extraction path.
Every accepted record becomes its own `incident_reports` row (status `SUBMITTED`) with a unique UUID and UTC submission timestamp. A separate `report_extractions` row stores the model-proposed facts, evidence and confidence; any user edits are stored as reviewed facts without overwriting the original narrative or initial proposal.

The implemented slice includes Epics 1–6: report intake and extraction, incident mapping and impact areas, priority and related-report review, and the department-owned resource registry with audited availability, explicit plan-linked assignments, and nearby-resource queries. Web-intake text understanding uses Groq when configured. Response planning also tries Groq first and falls back to deterministic planning if Groq is unavailable; backend resource validation remains authoritative. Image analysis is advisory; failures do not prevent an otherwise valid report from being stored.

Coordinators use one **Link report to an incident** action for both unconfirmed reports and confirmed duplicate incidents. Linking a confirmed incident consolidates it under the chosen canonical incident; original reports, descriptions, media, extractions and incident history remain available, and the linking reason is recorded. Resources live in one department-owned registry. Response-plan drafts include only currently available resources with matching capabilities in the incident region. Plans still require human approval; approval does not assign or dispatch resources. In the approved-plan assignment menu, all available registry resources are listed and AI-suggested resources are highlighted. Coordinators may choose another available unit; the backend rechecks its availability and operational registry data, and audits whether each assignment was AI-suggested or coordinator-selected. Assignment and release do not execute dispatch.

### Groq-backed report analysis and response planning

When `GROQ_API_KEY` is configured in the ignored `backend/.env`, web intake sends the report type, description, location name, and active administrator priority policy to Groq for proposed structured facts. The policy weights and thresholds are accompanied by the scoring factor definitions. The user can edit those proposals before submission. Priority math remains deterministic and applies the active policy weights and thresholds to the final effective facts, so a model-generated score cannot bypass the configured policy. The current policy weights are factor-level (life safety, urgency, population, hazard, and evidence confidence), not separate per-hazard weights; for example, injury affects the life-safety and hazard factors.

Response-plan generation tries Groq first and retries once after a provider or output-validation failure. If Groq still fails, the system uses the deterministic backend planning fallback and records which planner produced the plan. Coordinators can use **Try Groq again (new draft)** to make another attempt after a fallback (for example, after fixing the key or provider availability). Configure `GROQ_MODEL`, timeout and output limits there as needed. In either mode, resource IDs, availability, capability matches and regional filtering come from the database; Groq cannot create or assign resources. Corrected facts and descriptions from the primary and linked reports, incident category/priority, coordinates/impact area, and eligible resource details are sent to Groq. The coordinator still reviews and approves or rejects each plan; plan generation does not assign resources or dispatch responders.

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

### Frontend demo: preserved reports and registered resources

1. Configure `AUTH_SECRET_KEY` and local `DEMO_USER_*`, `DEMO_COORDINATOR_*`, and `DEMO_ADMIN_*` values in `backend/.env`. Set `GROQ_API_KEY` there to use Groq as the first-choice planner. Start the API from `backend/` with `uvicorn app.main:app --reload`.
2. In a second terminal, start the frontend from `frontend/` with `npm install` (first run only), then `npm run dev`. Sign in as `USER` and submit two reports for the same event, using descriptions that include a request such as “need rescue.”
3. The local SQLite demo database has 12 available, named emergency resources—three each in Thrippunithura, Wayanad, Kakkanad and Kottayam. For a separate database, sign in as `ADMIN`, open **Resources**, and register your units. The default operational travel limit is 100 km (`RESOURCE_SEARCH_RADIUS_METRES`); an incident's smaller radius still narrows that limit. The optional `demo_resource_seed.py` command is only for a clean mock-only development registry; it is not needed for this demo data.
4. Sign in as `MANAGEMENT` (Coordinator), open **Review**, then confirm or dismiss a submitted report directly. Open **Report analysis** to compare extracted facts with coordinator corrections and inspect evidence. Confirming calculates priority and enables response planning. Use **Link report to an incident** to associate an unconfirmed report or consolidate a confirmed duplicate. Use **Unlink / unmerge** to reverse that association and restore a merged incident; **Delete report** permanently removes a report and its dependent incident workflow after confirmation.
5. Use **Generate response plan** to request a plan from Groq using corrected report facts, all linked-report context, eligible resources, and their distance from the incident. The interface identifies whether Groq or the deterministic fallback produced the draft. Review and approve/reject the plan as coordinator; approval does not dispatch. To associate two already-confirmed incidents, select the duplicate incident's original report and use the same **Link report to an incident** action to choose the canonical incident.
6. Optionally assign selected recommended resources from an approved plan, enter an assignment reason, and assign them. The resource becomes `ASSIGNED`; no dispatch is executed. Release the assignment from the plan with a reason to restore availability. **Make all resources available** on the Resources page also releases active assignments and records the coordinator's reason in history.

The demo does not silently seed resources, automatically link suspected duplicates, or execute dispatch. The explicitly registered emergency resources, report links, assignments/releases, and availability changes persist in the configured database.

### Task verification

From the repository root:

```powershell
backend\.venv\Scripts\python.exe -m pytest
cd frontend
npm test
npm run build
```

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
| Confirmed incidents, response plans, workflow audit | `backend/app/models/incident.py` |
| Report/incident links and consolidated incident history | `backend/app/models/incident.py`, `backend/app/services/incident_service.py` |
| Departments, resources, availability and assignment history | `backend/app/models/resources.py`, `backend/app/services/resource_service.py`, `backend/app/services/incident_service.py` |
| Department/resource APIs | `backend/app/api/resources.py` |
| Resource registry UI | `frontend/src/features/resources/ResourceRegistryPage.jsx` |
| Review transitions, Groq/deterministic draft planning and resource validation | `backend/app/services/incident_service.py`, `backend/app/services/groq_planner.py`, `backend/app/api/workflow.py` |
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
| POST | `/reports/{id}/confirm` | Confirm a submitted report and create an incident |
| POST | `/reports/{id}/dismiss` | Dismiss a submitted report with an optional reason |
| POST | `/reports/{id}/reopen` | Reopen a dismissed, unlinked report to `SUBMITTED` with a required reason (MANAGEMENT/ADMIN) |
| POST | `/reports/{id}/potential-relationships` | Detect and save time/location-based potential report links (MANAGEMENT/ADMIN) |
| GET | `/report-relationships?status=PROPOSED` | List potential report links for coordinator review |
| POST | `/report-relationships/{id}/confirm` | Confirm a relationship without merging reports |
| POST | `/report-relationships/{id}/reject` | Reject a potential relationship and record the decision |
| POST | `/incidents/{id}/reports/{report_id}/link` | Link an unconfirmed report or consolidate a confirmed incident under an active canonical incident (MANAGEMENT/ADMIN) |
| GET | `/incidents`, `/incidents/{id}` | List canonical incidents and read incident/link history |
| POST | `/incidents/{id}/close`, `/incidents/{id}/reopen` | Close or reopen a canonical incident with a required reason; release active assignments before closing (MANAGEMENT/ADMIN) |
| GET / POST / PATCH | `/departments` | Read departments (MANAGEMENT/ADMIN); create/update department master data (ADMIN) |
| GET / POST / PATCH | `/resources` | Read resources (MANAGEMENT/ADMIN); create/edit resource master data (ADMIN) |
| PATCH | `/resources/{id}/availability` | Change current availability with a required reason (MANAGEMENT/ADMIN) |
| POST | `/incidents/{id}/plans` | Generate a needs-based plan draft from corrected/effective facts |
| GET | `/response-plans/{id}` | Read a response-plan draft and decision |
| POST | `/response-plans/{id}/approve` | Record human approval; does not assign or execute dispatch |
| POST | `/response-plans/{id}/reject` | Record human rejection |
| POST | `/response-plans/{id}/assignments` | Assign selected recommended resources from an approved plan (MANAGEMENT/ADMIN) |
| POST | `/response-plans/{id}/assignments/{assignment_id}/release` | Release an active resource assignment with a reason (MANAGEMENT/ADMIN) |
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
`MANAGEMENT` and `ADMIN` accounts can open the **Review** workspace to compare the original submission with extracted facts, evidence and confidence. Corrections are saved separately and retain before/after snapshots, actor and timestamp; the original description and first-pass extraction remain unchanged. Confidence is a documented evidence-support score, not a probability. The API is `PATCH /reports/{id}/extraction` with `{"facts": { ... }}`. Reporters receive `403` for correction attempts.

### Potential report relationships
Coordinators can run **Find potential matches** from the report review workspace. Detection proposes report pairs within the configured time and corrected-location windows (24 hours and 25 km by default), and records these values as evidence. The **Semantic search** toggle optionally adds the five most semantically similar reports, including reports outside those windows; semantic similarity uses the optional `numpy` and `sentence-transformers` packages. Match cards let coordinators link a report into the other report's active incident with a reason. This reuses the audited incident link/merge workflow, confirms the potential relationship in the same transaction, and preserves the original report records. Coordinators can also reject proposals; decisions are recorded in workflow audit history. The report-menu link action remains available independently. `ENABLE_SEMANTIC_REPORT_MATCHING=true` is the default only for detection requests that omit an explicit semantic-search option.

### Advisory image analysis (Epic 2.3)
When an image is attached, the bundled local six-class classifier analyzes it; no external provider or API key is used. Returned cues include classifier confidence and remain advisory evidence linked to the image. If the classifier or its weights are unavailable, the report is still stored and the analysis status is recorded as `FAILED`.

### Epic 2.1 – description fact extraction
Accepted web-form and JSON/CSV reports receive a separate `extraction` object in report responses and `GET /reports/{id}`. The versioned rule extractor returns evidence-backed candidates for disaster category, severity cues, urgency, affected-person count, hazards, requested assistance and location mentions. Evidence contains the matched source phrases; unsupported values remain `null`/empty and receive no confidence value. Confidence is a field-level evidence-support score on a 0–1 scale, not a probability that a reported fact is true. The original submitted description and selected form fields are not overwritten.

This is a deterministic, bounded MVP rather than general-purpose named-entity understanding. Location phrases are mentions only; the intake map search resolves a supported place query to coordinates, while text mentions are not treated as verified coordinates. Extracted values are advisory and must be reviewed before operational use. Results are stored in `report_extractions` so existing `incident_reports` tables do not need column changes. Run `.\.venv\Scripts\python.exe -m pytest backend\tests\test_report_api.py backend\tests\test_import.py -q` from the repository root to test extraction, persistence, and failure handling.

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

### Incident and response-plan workflow
Coordinator/admin flow: coordinators directly confirm a `SUBMITTED` report (creating an `ACCEPTED` report and confirmed incident) or dismiss it as `DISMISSED`. A dismissed, unlinked report can be reopened with a reason to return it to `SUBMITTED`. Confirmed incidents can generate an `AWAITING_APPROVAL` plan → approve/reject → optionally assign selected recommended resources. Plan generation snapshots `extraction.effective_facts`, asks Groq first with one retry when configured, and uses deterministic rules if the LLM is unavailable. Both planners can only select database-validated resources from active departments with current `AVAILABLE` state. Approval records the human decision but does not assign or dispatch. Assignment is a separate audited action available only from an approved plan; the backend rechecks current capability, location, department and availability before atomically changing resource state. Release assignments before closing an incident. A coordinator may reopen a closed canonical incident to `ACTIVE`; close and reopen require an audited reason.

### Incident priority recommendation (ADM-23 / ADM-24)
Confirmed incidents receive a deterministic 0–100 rules-based score, raw factor values, a weighted contribution breakdown, the policy-config version, and scoring algorithm version (`priority-v1`). The policy version identifies the immutable stored weights and thresholds; the algorithm version identifies the code-defined factor mappings and formula. Available evidence factors are normalized over only the factors present; missing or unrecognized fields do not receive made-up zero-risk values. Population is scaled as `min(affected_persons / 25, 1)`. Urgency maps `CRITICAL/HIGH/ELEVATED/LOW` to `1/.75/.5/.2`; life-safety cues and recognized hazard types use the explicit severity maps in `backend/app/services/priority_service.py`. When extraction confidence is present, only confidence belonging to source fields that contributed a recognized score factor is used; its configured weight discounts the base risk score by `(1 - weight × (1 - mean_confidence))`. Unrelated confidence fields and absent confidence have no effect. If no supported risk factor is available, the score and band remain `null`.

Default inclusive lower-bound thresholds are **CRITICAL ≥ 75**, **HIGH ≥ 55**, **MEDIUM ≥ 30**, and **LOW ≥ 0**. Admins may version weights and thresholds through `POST /priority-configs`; thresholds must be strictly ordered and LOW must remain zero. The score, factor breakdown, band, and policy version are stored on the confirmed incident and returned by the incident endpoints. These are decision-support recommendations only: they do not confirm an incident, change source report data, or dispatch responders. Human report review/confirmation remains a separate workflow step.

### Notes for teammates
- **Auth/RBAC:** Report and import endpoints require a signed session. `USER` accounts can view their own reports; `MANAGEMENT` and `ADMIN` can view all submitted reports. Incident review and plan-decision endpoints are coordinator/admin-only.
- **Local demo accounts:** Configure `DEMO_USER_*`, `DEMO_COORDINATOR_*`, and `DEMO_ADMIN_*` in the ignored `backend/.env`. Never commit that file or reuse demo passwords in production. Set `AUTH_COOKIE_SECURE=true` behind HTTPS.
- **Schema:** tables are created by `init_db()` for dev; move to Alembic and add the `submitted_by` foreign key to `users.id`.
- **Not done in this demo slice:** PostGIS-backed persistence, plan execution/dispatch, video upload, `/reports/my`, department alerts, and broader downstream workflows. Resource assignments are recorded but do not dispatch responders.
