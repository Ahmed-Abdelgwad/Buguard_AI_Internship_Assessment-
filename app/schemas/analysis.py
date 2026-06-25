from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.models.asset import AssetStatus, AssetType
from app.schemas.asset import AssetOut

# ── Unified ask (Router + Agent orchestration) ────────────────────────────────

class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000, description="Any question about your assets")
    evaluate: bool = Field(True, description="Auto-evaluate output quality after answering")
    max_agent_iterations: int = Field(5, ge=1, le=10)


class AskResponse(BaseModel):
    question: str
    mode_used: str
    routing_reason: str
    answer: dict[str, Any]
    grounding_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    completeness_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    hallucinated_assets: Optional[list[str]] = None
    evaluation_note: Optional[str] = None


# ── Natural-language query ────────────────────────────────────────────────────

class NLQueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000, description="Natural-language question about your assets")


class FilterParams(BaseModel):
    """Structured filter that the LLM extracts from a natural-language question.

    All fields are optional; unset fields are ignored.
    """
    type: Optional[AssetType] = None
    status: Optional[AssetStatus] = None
    tag: Optional[str] = None
    value_contains: Optional[str] = None
    expired_before: Optional[datetime] = Field(None, description="Filter certs/assets with expiry before this date")
    expired_after: Optional[datetime] = None


class NLQueryResponse(BaseModel):
    question: str
    interpreted_filters: FilterParams
    assets: list[AssetOut]
    total: int
    summary: str


# ── Risk scoring ──────────────────────────────────────────────────────────────

class RiskRequest(BaseModel):
    asset_ids: Optional[list[str]] = Field(None, description="Specific asset IDs to score; if omitted uses filters")
    type: Optional[AssetType] = None
    status: Optional[AssetStatus] = None
    tag: Optional[str] = None


class RiskFinding(BaseModel):
    asset_id: str
    asset_value: str
    severity: Literal["critical", "high", "medium", "low", "info"]
    category: str
    description: str
    recommendation: str


class RiskResponse(BaseModel):
    overall_score: int = Field(..., ge=0, le=100, description="0=safe 100=critical")
    risk_level: Literal["critical", "high", "medium", "low"]
    findings: list[RiskFinding] = Field(default_factory=list)
    summary: str
    assets_analyzed: int = 0


# ── Enrichment & categorization ───────────────────────────────────────────────

class EnrichRequest(BaseModel):
    asset_id: Optional[str] = None
    asset: Optional[dict[str, Any]] = Field(None, description="Raw asset dict for ad-hoc enrichment without persisting")


class EnrichmentResult(BaseModel):
    environment: Literal["production", "staging", "development", "unknown"]
    category: str = Field(..., description="e.g. web-app, database, cdn, mail, vpn")
    criticality: Literal["critical", "high", "medium", "low"]
    enriched_metadata: dict[str, Any] = Field(default_factory=dict)
    reasoning: str


class EnrichResponse(BaseModel):
    asset_id: Optional[str]
    enrichment: EnrichmentResult
    asset_updated: bool


# ── Report generation ─────────────────────────────────────────────────────────

class ReportRequest(BaseModel):
    title: Optional[str] = "Asset Inventory & Risk Report"
    type: Optional[AssetType] = None
    status: Optional[AssetStatus] = None
    tag: Optional[str] = None
    format: Literal["markdown", "text"] = "markdown"


class ReportResponse(BaseModel):
    title: str
    content: str
    assets_included: int
    generated_at: datetime


# ── Agentic mode (bonus) ──────────────────────────────────────────────────────

class AgentRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    max_iterations: int = Field(5, ge=1, le=10)


class AgentStep(BaseModel):
    tool: str
    input: Any
    output: Any


class AgentResponse(BaseModel):
    question: str
    answer: str
    steps: list[AgentStep]


# ── Evaluation harness (bonus) ────────────────────────────────────────────────

class EvaluationRequest(BaseModel):
    chain_type: Literal["nl_query", "risk", "enrichment", "report", "agent"]
    input: dict[str, Any]
    output: dict[str, Any]


class EvaluationResponse(BaseModel):
    grounding_score: float = Field(..., ge=0.0, le=1.0)
    completeness_score: float = Field(..., ge=0.0, le=1.0)
    hallucinated_assets: list[str]
    explanation: str
