"""FastAPI application entry point."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.api.assets import router as assets_router
from app.api.analysis import router as analysis_router

logger = logging.getLogger(__name__)

_LIFECYCLE_INTERVAL_SECONDS = 86_400  # 24 hours

# ── Rate limiter ──────────────────────────────────────────────────────────────
# Keyed by client IP; in production replace with a Redis backend for multi-process deployments.
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])


async def _lifecycle_scheduler() -> None:
    """Background task: refresh certificate lifecycle statuses every 24 hours."""
    from app.database import SessionLocal
    from app.services.lifecycle_service import refresh_certificate_lifecycle

    while True:
        try:
            with SessionLocal() as db:
                result = refresh_certificate_lifecycle(db)
            logger.info(
                "Lifecycle refresh: scanned=%d expired=%d expiring_soon=%d renewed=%d",
                result.certificates_scanned,
                result.expired,
                result.expiring_soon,
                result.renewed,
            )
        except Exception:
            logger.exception("Lifecycle scheduler encountered an error; will retry next cycle")
        await asyncio.sleep(_LIFECYCLE_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.ai.tools.asset_tools import set_db_session_factory
    from app.database import SessionLocal
    set_db_session_factory(SessionLocal)

    scheduler_task = asyncio.create_task(_lifecycle_scheduler())
    yield
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass


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

# ── Middleware ────────────────────────────────────────────────────────────────

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

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
        content={"error": "Validation error", "detail": exc.errors()},
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


# ── Graph visualization (HTML) ────────────────────────────────────────────────

@app.get("/graph/{asset_id}", response_class=HTMLResponse, include_in_schema=False)
def graph_visualization(asset_id: str):
    """Interactive relationship graph for a single asset rendered with vis-network."""
    return HTMLResponse(_graph_html(asset_id))


def _graph_html(asset_id: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>Asset Graph — {asset_id}</title>
  <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0; }}
    #header {{ padding: 14px 20px; background: #1e293b; border-bottom: 1px solid #334155;
               display: flex; align-items: center; gap: 12px; }}
    #header h1 {{ font-size: 1rem; font-weight: 600; }}
    #asset-id {{ font-size: 0.8rem; color: #94a3b8; font-family: monospace; }}
    #graph {{ width: 100%; height: calc(100vh - 52px); }}
    #error {{ display: none; padding: 40px; text-align: center; color: #f87171; }}
    #legend {{ position: fixed; bottom: 16px; right: 16px; background: #1e293b;
               border: 1px solid #334155; border-radius: 8px; padding: 12px 16px;
               font-size: 0.75rem; line-height: 1.8; }}
    .dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%;
            margin-right: 6px; vertical-align: middle; }}
  </style>
</head>
<body>
  <div id="header">
    <h1>Asset Relationship Graph</h1>
    <span id="asset-id">{asset_id}</span>
  </div>
  <div id="graph"></div>
  <div id="error"></div>
  <div id="legend">
    <strong>Asset types</strong><br>
    <span class="dot" style="background:#3b82f6"></span>domain<br>
    <span class="dot" style="background:#8b5cf6"></span>subdomain<br>
    <span class="dot" style="background:#f59e0b"></span>ip_address<br>
    <span class="dot" style="background:#10b981"></span>service<br>
    <span class="dot" style="background:#ef4444"></span>certificate<br>
    <span class="dot" style="background:#6b7280"></span>technology<br>
    <span class="dot" style="background:#f97316; border: 2px solid #fff"></span>root node
  </div>

  <script>
    const TYPE_COLORS = {{
      domain:      '#3b82f6',
      subdomain:   '#8b5cf6',
      ip_address:  '#f59e0b',
      service:     '#10b981',
      certificate: '#ef4444',
      technology:  '#6b7280',
    }};

    async function init() {{
      const apiKey = sessionStorage.getItem('darkatlas_key') ||
                     prompt('Enter your API key (reader or admin):');
      if (!apiKey) return;
      sessionStorage.setItem('darkatlas_key', apiKey);

      let data;
      try {{
        const res = await fetch('/api/v1/assets/{asset_id}/graph',
          {{ headers: {{ 'X-API-Key': apiKey }} }});
        if (!res.ok) {{
          const err = await res.json().catch(() => ({{}}));
          throw new Error(err.detail || res.statusText);
        }}
        data = await res.json();
      }} catch (e) {{
        document.getElementById('graph').style.display = 'none';
        const el = document.getElementById('error');
        el.style.display = 'block';
        el.textContent = 'Failed to load graph: ' + e.message;
        return;
      }}

      const nodes = new vis.DataSet(data.nodes.map(n => ({{
        id: n.id,
        label: n.label.length > 30 ? n.label.slice(0, 28) + '…' : n.label,
        title: `${{n.type}} | ${{n.status}}\\n${{n.label}}`,
        color: {{
          background: n.group === 'root' ? '#f97316' : (TYPE_COLORS[n.type] || '#6b7280'),
          border:     n.group === 'root' ? '#fff' : '#0f172a',
          highlight:  {{ background: '#fbbf24', border: '#fff' }},
        }},
        font:  {{ color: '#f8fafc', size: n.group === 'root' ? 14 : 12 }},
        size:  n.group === 'root' ? 28 : 18,
        shape: n.type === 'certificate' ? 'diamond' : 'dot',
        borderWidth: n.group === 'root' ? 3 : 1,
      }})));

      const edges = new vis.DataSet(data.edges.map(e => ({{
        from: e.from, to: e.to,
        label: e.label,
        font: {{ size: 10, color: '#94a3b8', align: 'middle' }},
        color: {{ color: '#475569', highlight: '#fbbf24' }},
        arrows: 'to',
        smooth: {{ type: 'curvedCW', roundness: 0.2 }},
      }})));

      new vis.Network(
        document.getElementById('graph'),
        {{ nodes, edges }},
        {{
          physics: {{ barnesHut: {{ gravitationalConstant: -8000, springLength: 160 }} }},
          interaction: {{ hover: true, tooltipDelay: 100 }},
          layout: {{ improvedLayout: true }},
        }}
      );
    }}

    init();
  </script>
</body>
</html>"""


@app.get("/", include_in_schema=False)
def root():
    return {"message": "DarkAtlas Asset Management API — visit /docs for Swagger UI"}
