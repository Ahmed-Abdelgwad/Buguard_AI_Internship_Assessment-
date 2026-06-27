# DarkAtlas Asset Management — Track B: AI Applications

A FastAPI + PostgreSQL + LangChain service for Attack Surface Monitoring asset management.
Built for the Buguard internship assessment — **Track B: AI Applications**.

---

## Quick start (Docker)

```bash
# 1. Copy and configure environment
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY and (optionally) API_KEY

# 2. Start API + PostgreSQL
docker-compose up --build

# 3. Seed the sample dataset
curl -X POST http://localhost:8000/api/v1/assets/import \
     -H "Content-Type: application/json" \
     -H "X-API-Key: changeme" \
     -d @data/sample_dataset.json

# 4. Open Swagger UI
open http://localhost:8000/docs
```

---

## Local development (without Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in DATABASE_URL + ANTHROPIC_API_KEY

# Run migrations
alembic upgrade head

# Start the API
uvicorn app.main:app --reload
```

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `API_KEY` | Yes | `changeme` | API key for write endpoints (`X-API-Key` header) |
| `ANTHROPIC_API_KEY` | Yes (AI features) | — | Anthropic API key |
| `ANTHROPIC_MODEL` | No | `claude-opus-4-8` | Claude model to use |
| `CACHE_TTL` | No | `600` | LangChain result cache TTL in seconds |
| `CACHE_MAXSIZE` | No | `512` | Max cache entries |

---

## Project structure

```text
app/
├── main.py               # FastAPI app entry point
├── config.py             # Pydantic Settings
├── database.py           # SQLAlchemy engine + session
├── models/
│   ├── asset.py          # Asset ORM model + enums
│   └── relationship.py   # AssetRelationship ORM model
├── schemas/
│   ├── asset.py          # Asset request/response schemas
│   └── analysis.py       # All AI analysis schemas
├── api/
│   ├── deps.py           # API key + org ID dependencies
│   ├── assets.py         # Import + list routes
│   └── analysis.py       # AI analysis routes
├── services/
│   ├── asset_service.py  # Dedup, upsert, pagination
│   └── import_service.py # Bulk import with per-record isolation
└── ai/
    ├── llm.py            # Anthropic LLM factory
    ├── cache.py          # TTL result cache
    ├── prompts/          # ChatPromptTemplate per capability
    ├── chains/           # LCEL chains (NL query, risk, enrich, report)
    ├── tools/            # LangChain @tool wrappers for agent mode
    ├── agent.py          # LangGraph agent with tool-calling (bonus)
    └── evaluation.py     # Grounding + completeness evaluation (bonus)
```

---

## API documentation

Interactive Swagger UI: **[http://localhost:8000/docs](http://localhost:8000/docs)**
ReDoc: **[http://localhost:8000/redoc](http://localhost:8000/redoc)**

> Write endpoints require `X-API-Key` header.

### Asset endpoints (`/api/v1/assets`)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/assets` | — | List assets with filter/sort/pagination |
| `POST` | `/assets/import` | ✓ | Bulk import (idempotent) |
| `POST` | `/assets/lifecycle/refresh` | ✓ | Manually trigger certificate lifecycle scan |

**Filtering parameters** (`GET /assets`):
- `type` — `domain | subdomain | ip_address | service | certificate | technology`
- `status` — `active | stale | archived`
- `tag` — exact tag match
- `value_contains` — substring search
- `sort_by`, `sort_dir`, `page`, `page_size`

### Analysis endpoints (`/api/v1/analysis`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/analysis/query` | Natural-language query (grounded in DB) |
| `POST` | `/analysis/risk` | Risk scoring & summarization |
| `POST` | `/analysis/enrich` | Enrichment & categorization |
| `POST` | `/analysis/report` | Inventory/risk report generation |
| `POST` | `/analysis/agent` | Agentic multi-step analysis (bonus) |
| `POST` | `/analysis/ask` | Unified endpoint — auto-routes to best chain + auto-evaluates (bonus) |
| `POST` | `/analysis/evaluate` | Output evaluation harness (bonus) |

---

## Example prompts and outputs

### 1. Natural-language query

**Request:**
```json
POST /api/v1/analysis/query

{
  "question": "show me all expired certificates on production subdomains"
}
```

**Response:**
```json
{
  "question": "show me all expired certificates on production subdomains",
  "interpreted_filters": {
    "type": "certificate",
    "status": "active",
    "tag": "prod"
  },
  "assets": [
    {
      "id": "cert1",
      "type": "certificate",
      "value": "CN=api.example.com",
      "status": "active",
      "metadata": {"expires": "2025-01-02T00:00:00Z", "issuer": "Let's Encrypt"}
    }
  ],
  "total": 3,
  "summary": "Found 3 asset(s) matching your query with filters: {type: certificate, tag: prod}"
}
```

### 2. Risk scoring

**Request:**
```json
POST /api/v1/analysis/risk

{
  "tag": "prod"
}
```

**Response:**
```json
{
  "overall_score": 85,
  "risk_level": "high",
  "findings": [
    {
      "asset_id": "cert2",
      "asset_value": "CN=www.example.com",
      "severity": "critical",
      "category": "expired_certificate",
      "description": "Certificate expired on 2024-06-15. Production traffic is affected.",
      "recommendation": "Renew certificate immediately via Let's Encrypt or DigiCert."
    },
    {
      "asset_id": "svc4",
      "asset_value": "3389/tcp",
      "severity": "high",
      "category": "exposed_service",
      "description": "RDP (port 3389) exposed on production IP 203.0.113.12.",
      "recommendation": "Restrict RDP access behind VPN or disable if unused."
    }
  ],
  "summary": "Critical: 2 expired certificates on production assets. High: RDP and FTP exposed publicly.",
  "assets_analyzed": 28
}
```

### 3. Enrichment & categorization

**Request:**
```json
POST /api/v1/analysis/enrich

{
  "asset_id": "sub1"
}
```

**Response:**
```json
{
  "asset_id": "sub1",
  "enrichment": {
    "environment": "production",
    "category": "api-gateway",
    "criticality": "critical",
    "enriched_metadata": {
      "detected_framework": "nginx reverse proxy",
      "public_facing": true
    },
    "reasoning": "Value 'api.example.com' with 'prod' tag indicates a production-facing API gateway."
  },
  "asset_updated": true
}
```

### 4. Report generation

**Request:**
```json
POST /api/v1/analysis/report

{
  "title": "Q2 2026 Production Attack Surface Report",
  "tag": "prod",
  "format": "markdown"
}
```

**Response (excerpt):**
```json
{
  "title": "Q2 2026 Production Attack Surface Report",
  "content": "# Q2 2026 Production Attack Surface Report\n\n## Executive Summary\n\nThe production environment exposes 28 assets across 6 categories. **2 certificates are expired** and require immediate renewal. **3 high-risk services** (RDP, FTP, Telnet) are publicly accessible...",
  "assets_included": 28,
  "generated_at": "2026-06-25T18:00:00Z"
}
```

### 5. Agentic mode (bonus)

**Request:**
```json
POST /api/v1/analysis/agent

{
  "question": "Which production domains have certificates expiring within 30 days and what services run on their IPs?",
  "max_iterations": 5
}
```

**Response:**
```json
{
  "question": "Which production domains have certificates expiring within 30 days...",
  "answer": "I found 2 certificates expiring within 30 days on production assets: CN=vpn.example.com (expires 2026-07-21) and CN=*.example.com (expires 2026-07-10). The IPs associated with these subdomains run: 443/tcp (HTTPS/nginx), 22/tcp (SSH), and 1194/udp (OpenVPN).",
  "steps": [
    {"tool": "search_assets", "input": {"type": "certificate", "tag": "prod"}, "output": "..."},
    {"tool": "get_asset_relationships", "input": {"asset_id": "cert4"}, "output": "..."},
    {"tool": "search_assets", "input": {"type": "service"}, "output": "..."}
  ]
}
```

---

## Design decisions and assumptions

### Deduplication
- Re-importing the same asset updates `last_seen`, merges `metadata` (JSONB `||` operator, incoming wins on key conflict), and unions `tags`.
- A `stale` asset that re-appears is automatically set back to `active`.

### Anti-hallucination
- The LLM **never generates or fabricates asset data**. For NL queries, it only extracts filter parameters; the actual results always come from the database.
- For risk scoring and reports, the LLM analyzes real DB data passed to it in the prompt.
- The evaluation harness verifies grounding by checking all mentioned asset IDs against the actual DB.

### Conflicting metadata
- Incoming metadata wins on key collision (JSONB `||` merge). This is appropriate for security data where newer scans are more reliable than older imports.

### Partial batch failures
- Each record in a bulk import is individually wrapped in try/except. A malformed record is appended to the `failures` list but never aborts the rest of the batch.

### Caching

- LangChain results are cached in a `TTLCache` (default: 10 minutes) keyed by `SHA256(chain_name + sorted JSON of input)`.
- In production this would be replaced with Redis for horizontal scaling.

### Authentication
- API key (`X-API-Key` header) is required on all write/mutating operations. Read endpoints are unauthenticated.
- Key is loaded from the `API_KEY` environment variable — never hardcoded.

### Certificate lifecycle

- A background scheduler runs at startup and every 24 hours (`app/services/lifecycle_service.py`).
- It scans all `certificate` assets and updates their `status` and `tags` based on `metadata.expires` (also accepts `metadata.expiry` and `metadata.not_after`):
  - `expires < now` → `status=stale`, tag `expired` added
  - `now ≤ expires < now+30d` → tag `expiring-soon` added
  - `expires ≥ now+30d` (or cert was renewed) → lifecycle tags cleared, `status` reactivated if stale was caused by expiry
- The `expired` tag acts as a sentinel: we only reactivate a `stale` cert if we were the ones who staled it (i.e., the tag is present), preventing accidental reactivation of assets staled for other reasons.
- A manual trigger is available at `POST /api/v1/assets/lifecycle/refresh` (requires API key).

### Multi-tenant isolation

- Not implemented in this version — the system is single-tenant.
- All assets are shared across all API consumers. A production multi-tenant design would add an `org_id` column to the `assets` table and scope every query with `WHERE org_id = :current_org`.

### LLM provider
- Anthropic Claude (`claude-opus-4-8`) via `langchain-anthropic`. Temperature is set to `0` for deterministic, non-creative responses appropriate for security analysis.

---

## What I would add with more time

1. **Redis cache** — replace the in-memory TTLCache with Redis for multi-process deployments.
2. **Rate limiting** — add `slowapi` middleware per-IP and per-API-key to prevent abuse.
3. **Streaming reports** — use `StreamingResponse` with LangChain's streaming callbacks for long reports.
4. **Asset graph visualization** — a `/graph` frontend page using D3.js or Cytoscape.js.
5. **Webhook alerts** — notify on critical findings (expired certs, new high-risk services).
