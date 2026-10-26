# Frontend workspace

React + Vite client for incident intake, coordinator report/incident review, and the department/resource registry. It consumes persisted FastAPI contracts and supports explicit, audited resource assignments without executing dispatch.

## Run locally

Copy `backend/.env.example` to `backend/.env` and configure a random `AUTH_SECRET_KEY` plus local demo credentials. That `.env` file is ignored by Git. Start FastAPI from `backend/`:

```powershell
uvicorn app.main:app --reload
```

In a second terminal, from `frontend/`:

```powershell
npm install
npm run dev
```

Run the frontend location parser tests with:

```powershell
npm test
```

Open the local URL Vite prints. Vite proxies `/auth`, `/reports`, `/incidents`, `/response-plans`, `/priority-configs`, `/departments`, `/resources`, and `/health` to `http://127.0.0.1:8000`. Set `VITE_API_BASE_URL` only when the API is hosted elsewhere.

To serve the production bundle from FastAPI, run `npm run build` and restart the backend. The client is served at `/`; `/report-form` remains as a compatibility URL. The legacy `incident_report.html` is retained as a fallback when no production bundle exists.

## Current scope

- `/login` authenticates `USER`, `MANAGEMENT` (Coordinator), and `ADMIN` accounts against the backend. The server sets an HTTP-only signed session cookie; unauthenticated users are redirected to login.
- Report, media, and import endpoints require a valid session. `USER` can view their own submitted reports; `MANAGEMENT` and `ADMIN` can view all submitted reports.
- Local demo accounts are provisioned from `backend/.env`. Never commit demo passwords or use them in production.
- Web form (`/` or `/intake`) analyzes the report description with Groq before final submission, pre-fills editable fact fields, and sends multipart data to `POST /reports`, including optional JPEG, PNG, or WebP evidence. Groq receives the active admin priority policy and its factor definitions. If Groq is unavailable, proposed fields remain unknown for manual entry. The final priority preview applies the active admin weights and thresholds deterministically.
- The form's Leaflet/OpenStreetMap location picker supports direct latitude/longitude entry, address search and reverse geocoding through public Nominatim, map clicks, draggable markers, coordinate/full Google Maps URL input, and browser geolocation. Valid manually entered coordinates move the picker marker directly without requiring a place name.
- Bulk import uses `POST /reports/import/json` or `/reports/import/csv` and displays each accepted/rejected row.
- The coordinator Review workspace can directly confirm or dismiss a submitted report, reopen a dismissed report to `SUBMITTED` with a reason, and open a dedicated Report analysis view to compare extracted facts with coordinator corrections and edit effective facts. It can request a Groq-first response plan (with one automatic retry and deterministic fallback), retry Groq with a new draft, record an approve/reject decision, and close/reopen canonical incidents with a reason.
- Coordinators can run **Find potential matches** for a selected report and review pending potential relationships in the Review workspace. The **Semantic search** toggle optionally adds the five most semantically similar reports, including candidates outside the time and distance windows; those values remain visible as evidence. A match card can link one report into the other report's active incident, reusing the same audited link/merge operation as the report menu. That action records the potential relationship as confirmed in the same transaction; the original report remains available. The report-menu **Link report to an incident** workflow remains available independently. `ENABLE_SEMANTIC_REPORT_MATCHING=true` remains the backend default only for detection requests that omit the explicit semantic-search option.
- Coordinators use one **Link report to an incident** action for an unconfirmed report or a confirmed duplicate incident. Confirmed source incidents are consolidated under the chosen canonical incident; original report and incident records are retained, and the required reason is recorded.
- `/resources` is available to MANAGEMENT and ADMIN. ADMIN can create departments, register resources and edit resource details; MANAGEMENT and ADMIN can update resource availability with a required audit reason or make all eligible resources available with an audited reason. That bulk action releases active assignments.
- Resource plan candidates come from persisted, active-department resources whose availability is `AVAILABLE` and whose capability tags match extracted requested-assistance facts, ranked by capability match and distance. The configurable operational travel radius defaults to 100 km; a smaller incident radius narrows it but cannot expand it. No demo resource data is silently seeded. This workspace's SQLite demo database contains 12 explicitly registered emergency resources, three each in Thrippunithura, Wayanad, Kakkanad, and Kottayam. The optional SQLite seed utility is for disposable mock-only setups, not this resource registry.
- The coordinator Incident map (`/incident-map`) displays saved reports and confirmed incidents with status and priority indicators, configured impact-area overlays, selectable details, and a direct link to review/plan the selected report. Unconfirmed reports are labeled “Pending review”; priority and nearby resources are available after confirmation.
- Response plans use corrected/effective facts, show matching available registered-resource candidates, and require human approval. In the approved-plan assignment menu, all available registry resources are listed and AI-suggested resources are highlighted. Coordinators can select another available unit; the backend rechecks availability and operational registry data, and assignments/releases are audited without dispatching services.
- Coordinators can unlink a report association or unmerge a consolidated incident with a required reason. Deleting a report also deletes its dependent incident workflow, releases active resources, returns other linked reports to the submitted queue, and removes attached media.
- `/report-form` remains an alias for the web form.
- Dashboard, department alerts, and actual dispatch are not implemented in this frontend slice.

## Ownership and naming

- `src/App.jsx` owns route registration. Feature owners add routes here and keep page code inside their feature folder.
- `src/features/<feature-name>/` owns pages and UI specific to that domain. Prefer domain-qualified filenames such as `ResourceListPage.jsx` over generic names like `List.jsx`.
- `src/components/` is for components shared by multiple features; `src/api/` owns backend request functions.
- `src/styles/tokens.css` is the single source for colors, type, radii, and shared dimensions. Add a token there before using a new theme color; do not define page-level theme palettes.
- `src/styles/intake.css` owns shared layout and component classes. Prefix feature-specific classes with the feature name to avoid collisions.
- Keep endpoint paths and response shapes aligned with backend schemas. Add a backend contract before wiring a future workflow.

## Theme

The shared palette uses deep green for primary actions, warm paper for the canvas, amber for emphasis, and restrained terracotta for validation errors. Use the existing CSS custom properties rather than introducing page-specific colors. The interface is light-theme only in this scaffold.