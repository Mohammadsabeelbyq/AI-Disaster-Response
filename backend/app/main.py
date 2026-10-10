"""FastAPI entry point. Run from backend/:  uvicorn app.main:app --reload
Other modules: include your router here with app.include_router(...)."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from app.api import auth, reports, workflow
from app.database import SessionLocal, init_db
from app.services.auth_service import seed_demo_accounts
from app.services.errors import AppError
from app.services.report_service import backfill_missing_extractions

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"
FRONTEND_INDEX = FRONTEND_DIST_DIR / "index.html"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as db:
        seed_demo_accounts(db)
        backfill_missing_extractions(db)
    yield


app = FastAPI(title="AI Disaster Response - Core Engine", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(reports.router)
app.include_router(workflow.reports_router)
app.include_router(workflow.incidents_router)
app.include_router(workflow.plans_router)
app.include_router(workflow.priority_router)
if (FRONTEND_DIST_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST_DIR / "assets"), name="frontend-assets")


@app.exception_handler(AppError)
async def handle_app_error(_: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code,
                        content={"message": exc.message, "errors": exc.errors})


@app.exception_handler(Exception)
async def handle_unexpected(_: Request, exc: Exception):
    logging.getLogger(__name__).exception("Unhandled error")
    return JSONResponse(status_code=500, content={"message": "Internal server error.", "errors": []})


@app.get("/health")
def health():
    return {"status": "ok"}


def _frontend_page():
    return FileResponse(FRONTEND_INDEX if FRONTEND_INDEX.is_file() else FRONTEND_DIR / "incident_report.html")


@app.get("/", include_in_schema=False)
def frontend_home():
    return _frontend_page()


@app.get("/report-form", include_in_schema=False)
def report_form():
    """Compatibility route for the original report-form URL."""
    return _frontend_page()


@app.get("/{frontend_path:path}", include_in_schema=False)
def frontend_routes(frontend_path: str):
    """Serve the React SPA for browser routes without masking unknown API paths."""
    api_prefixes = {"auth", "departments", "health", "incidents", "reports", "resources", "response-plans"}
    if frontend_path.split("/", 1)[0] in api_prefixes or not FRONTEND_INDEX.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(FRONTEND_INDEX)
