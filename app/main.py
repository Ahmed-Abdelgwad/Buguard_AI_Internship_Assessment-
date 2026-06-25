"""FastAPI application entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.assets import router as assets_router
from app.api.analysis import router as analysis_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Wire the DB session factory into the agent tools once at startup.
    # All agent tool calls (asset_tools + chain_tools) use _get_db() which
    # depends on this factory being set.
    from app.ai.tools.asset_tools import set_db_session_factory
    from app.database import SessionLocal
    set_db_session_factory(SessionLocal)
    yield


app = FastAPI(
    title="DarkAtlas Asset Management API",
    description=(
        "Attack Surface Monitoring — asset ingestion, lifecycle tracking, "
        "relationship graph, and LangChain-powered AI analysis."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(assets_router, prefix="/api/v1")
app.include_router(analysis_router, prefix="/api/v1")


# ── Error handlers ────────────────────────────────────────────────────────────

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "Validation error",
            "detail": exc.errors(),
        },
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Internal server error", "detail": str(exc)},
    )


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
def health():
    return {"status": "ok", "service": "darkatlas-asset-management"}


@app.get("/", include_in_schema=False)
def root():
    return {"message": "DarkAtlas Asset Management API — visit /docs for Swagger UI"}
