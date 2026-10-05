# Frontend workspace

React + Vite client for incident intake and the first coordinator review/planning slice. It consumes FastAPI contracts and does not implement public/operational maps, resource registries, or actual dispatch.

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

Open the local URL Vite prints. Vite proxies `/auth`, `/reports`, and `/health` to `http://127.0.0.1:8000`. Set `VITE_API_BASE_URL` only when the API is hosted elsewhere.

To serve the production bundle from FastAPI, run `npm run build` and restart the backend. The client is served at `/`; `/report-form` remains as a compatibility URL. The legacy `incident_report.html` is retained as a fallback when no production bundle exists.

## Current scope

- `/login` authenticates `USER`, `MANAGEMENT` (Coordinator), and `ADMIN` accounts against the backend. The server sets an HTTP-only signed session cookie; unauthenticated users are redirected to login.
- Report, media, and import endpoints require a valid session. `USER` can view their own submitted reports; `MANAGEMENT` and `ADMIN` can view all submitted reports.
- Local demo accounts are provisioned from `backend/.env`. Never commit demo passwords or use them in production.
- Web form (`/` or `/intake`) submits multipart data to `POST /reports`, including optional JPEG, PNG, or WebP evidence.
- The form's Leaflet/OpenStreetMap location picker supports address search and reverse geocoding through public Nominatim, map clicks, draggable markers, coordinate/full Google Maps URL input, and browser geolocation. Coordinates and place name are map-populated form outputs.
- Bulk import uses `POST /reports/import/json` or `/reports/import/csv` and displays each accepted/rejected row.
- The coordinator Review workspace can move a report through review, confirm or dismiss it, inspect/correct extracted facts, generate a needs-based response-plan draft, and record an approve/reject decision.
- Response plans use corrected/effective facts, require human approval, and explicitly show that no responder assignment or dispatch occurs because verified departments/resources are not yet registered.
- `/report-form` remains an alias for the web form.
- Dashboard, report history, public/operational maps, department/resource management, and actual incident operations/dispatch are not implemented in this frontend slice.

## Ownership and naming

- `src/App.jsx` owns route registration. Feature owners add routes here and keep page code inside their feature folder.
- `src/features/<feature-name>/` owns pages and UI specific to that domain. Prefer domain-qualified filenames such as `ResourceListPage.jsx` over generic names like `List.jsx`.
- `src/components/` is for components shared by multiple features; `src/api/` owns backend request functions.
- `src/styles/tokens.css` is the single source for colors, type, radii, and shared dimensions. Add a token there before using a new theme color; do not define page-level theme palettes.
- `src/styles/intake.css` owns shared layout and component classes. Prefix feature-specific classes with the feature name to avoid collisions.
- Keep endpoint paths and response shapes aligned with backend schemas. Add a backend contract before wiring a future workflow.

## Theme

The shared palette uses deep green for primary actions, warm paper for the canvas, amber for emphasis, and restrained terracotta for validation errors. Use the existing CSS custom properties rather than introducing page-specific colors. The interface is light-theme only in this scaffold.