"""Chain-level tools for the agent — wraps each AI chain as a LangChain @tool.

These give the agent the full power of every chain so it can compose them
for complex, multi-step questions without hardcoded orchestration logic.

The db session is obtained via the same factory registered in asset_tools.
"""
import json
from typing import Optional

from langchain_core.tools import tool

from app.ai.tools.asset_tools import _get_db


@tool
def query_assets_natural_language(question: str) -> str:
    """Search and filter assets using a natural-language question.

    Returns matching assets with total count and a filter summary.
    Use for: finding assets by type, status, tags, or value patterns
    when the user describes what they want in plain English.
    """
    from app.ai.chains.nl_query import run_nl_query

    db = _get_db()
    try:
        result = run_nl_query(db, question)
        items = [
            {"id": a.id, "type": str(a.type), "value": a.value, "status": str(a.status)}
            for a in result.assets[:20]
        ]
        return json.dumps(
            {"total": result.total, "summary": result.summary, "assets": items},
            default=str,
        )
    finally:
        db.close()


@tool
def score_asset_risk(
    tag: Optional[str] = None,
    asset_type: Optional[str] = None,
    asset_ids: Optional[str] = None,
) -> str:
    """Run AI risk scoring on a set of assets.

    Returns overall risk score (0-100), risk level, and top findings with recommendations.
    Use for: assessing threats, exposure, or vulnerability of a group of assets.

    Args:
        tag: Filter assets by this tag (e.g. "prod", "staging")
        asset_type: Filter by type: domain, subdomain, ip_address, service, certificate, technology
        asset_ids: Comma-separated asset IDs to assess (overrides tag/type filters)
    """
    from app.ai.chains.risk_scoring import run_risk_scoring
    from app.models.asset import AssetType
    from app.schemas.analysis import RiskRequest

    db = _get_db()
    try:
        ids = [x.strip() for x in asset_ids.split(",")] if asset_ids else None
        req = RiskRequest(
            asset_ids=ids,
            tag=tag,
            type=AssetType(asset_type) if asset_type else None,
        )
        result = run_risk_scoring(db, req)
        return json.dumps(
            {
                "overall_score": result.overall_score,
                "risk_level": result.risk_level,
                "assets_analyzed": result.assets_analyzed,
                "summary": result.summary,
                "top_findings": [
                    {
                        "asset_value": f.asset_value,
                        "severity": f.severity,
                        "description": f.description,
                        "recommendation": f.recommendation,
                    }
                    for f in result.findings[:5]
                ],
            }
        )
    finally:
        db.close()


@tool
def enrich_asset(asset_id: str) -> str:
    """Classify and enrich a specific asset.

    Determines environment (prod/staging/dev), category (web-app, database, cdn…),
    and criticality. Persists enriched metadata back to the database.
    Use for: understanding what an asset is and how critical it is.

    Args:
        asset_id: The unique ID of the asset to enrich
    """
    from app.ai.chains.enrichment import run_enrichment
    from app.schemas.analysis import EnrichRequest

    db = _get_db()
    try:
        result = run_enrichment(db, EnrichRequest(asset_id=asset_id))
        e = result.enrichment
        return json.dumps(
            {
                "asset_id": result.asset_id,
                "environment": e.environment,
                "category": e.category,
                "criticality": e.criticality,
                "reasoning": e.reasoning,
                "asset_updated": result.asset_updated,
            }
        )
    finally:
        db.close()


@tool
def generate_security_report(
    title: Optional[str] = None,
    tag: Optional[str] = None,
    asset_type: Optional[str] = None,
    format: str = "markdown",
) -> str:
    """Generate a comprehensive written security report for a set of assets.

    Returns an executive-level narrative (truncated to 3 000 chars for context).
    Use for: inventory summaries, attack surface overviews, executive briefings.

    Args:
        title: Report title (auto-generated if omitted)
        tag: Limit report to assets with this tag
        asset_type: Limit to a specific asset type
        format: "markdown" (default) or "text"
    """
    from app.ai.chains.report import run_report
    from app.models.asset import AssetType
    from app.schemas.analysis import ReportRequest

    db = _get_db()
    try:
        req = ReportRequest(
            title=title or "Security Report",
            tag=tag,
            type=AssetType(asset_type) if asset_type else None,
            format=format,
        )
        result = run_report(db, req)
        content = result.content
        if len(content) > 3000:
            content = content[:3000] + "\n\n[... report truncated — full content available via /analysis/report ...]"
        return json.dumps(
            {
                "title": result.title,
                "assets_included": result.assets_included,
                "content": content,
            }
        )
    finally:
        db.close()


CHAIN_TOOLS = [
    query_assets_natural_language,
    score_asset_risk,
    enrich_asset,
    generate_security_report,
]
