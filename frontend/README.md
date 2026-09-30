# Frontend workspace

React + Vite client for the two incident-report intake stories: web submission and structured JSON/CSV import. The frontend consumes the existing FastAPI contracts and intentionally does not implement dashboard, review, map, or response-coordination workflows.

## Run locally

Start FastAPI from `backend/`:

```powershell
uvicorn app.main:app --reload
```

In a second terminal, from `frontend/`:

```powershell
npm install
npm run dev
```

Open the local URL Vite prints. Vite proxies `/reports` and `/health` to `http://127.0.0.1:8000`. Set `VITE_API_BASE_URL` only when the API is hosted elsewhere.

To serve the production bundle from FastAPI, run `npm run build` and restart the backend. The client is served at `/`; `/report-form` remains as a compatibility URL. The legacy `incident_report.html` is retained as a fallback when no production bundle exists.

## Current scope

- Web form (`/` or `/intake`) submits multipart data to `POST /reports`, including optional JPEG, PNG, or WebP evidence.
- Bulk import uses `POST /reports/import/json` or `/reports/import/csv` and displays each accepted/rejected row.
- `/report-form` remains an alias for the web form.
- Dashboard, report history, maps, authentication, incident review, response planning, assignment, and alerts are outside this frontend task.

## Ownership and naming

- `src/App.jsx` owns route registration. Feature owners add routes here and keep page code inside their feature folder.
- `src/features/<feature-name>/` owns pages and UI specific to that domain. Prefer domain-qualified filenames such as `ResourceListPage.jsx` over generic names like `List.jsx`.
- `src/components/` is for components shared by multiple features; `src/api/` owns backend request functions.
- `src/styles/tokens.css` is the single source for colors, type, radii, and shared dimensions. Add a token there before using a new theme color; do not define page-level theme palettes.
- `src/styles/app.css` owns shared layout and component classes. Prefix feature-specific classes with the feature name to avoid collisions.
- Keep endpoint paths and response shapes aligned with backend schemas. Add a backend contract before wiring a future workflow.

## Theme

The shared palette uses deep green for primary actions, warm paper for the canvas, amber for emphasis, and restrained terracotta for validation errors. Use the existing CSS custom properties rather than introducing page-specific colors. The interface is light-theme only in this scaffold.