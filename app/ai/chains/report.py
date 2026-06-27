"""Natural-language report generation chain.

All data is fetched from the database; the LLM only writes prose around real data.
"""
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ai import cache
from app.ai.chains.risk_scoring import _asset_to_dict
from app.ai.llm import get_llm
from app.ai.prompts.report import report_prompt
from app.schemas.analysis import ReportRequest, ReportResponse
from app.schemas.asset import AssetListParams
from app.services.asset_service import list_assets


def run_report(db: Session, req: ReportRequest) -> ReportResponse:
    cache_key = req.model_dump(mode="json")
    cached = cache.get("report", cache_key)
    if cached:
        return cached

    params = AssetListParams(
        type=req.type, status=req.status, tag=req.tag, page=1, page_size=100
    )
    assets = list_assets(db, params).items

    if not assets:
        result = ReportResponse(
            title=req.title,
            content="No assets found matching the specified criteria.",
            assets_included=0,
            generated_at=datetime.now(timezone.utc),
        )
        cache.set("report", cache_key, result)
        return result

    assets_json = json.dumps([_asset_to_dict(a) for a in assets], default=str)
    today = datetime.now(timezone.utc).date().isoformat()

    llm = get_llm()
    chain = report_prompt | llm

    try:
        response = chain.invoke({
            "today": today,
            "title": req.title,
            "format": req.format,
            "count": len(assets),
            "assets_json": assets_json,
        })
        content = response.content if hasattr(response, "content") else str(response)
    except Exception as exc:
        content = f"Report generation failed: {exc}"

    result = ReportResponse(
        title=req.title,
        content=content,
        assets_included=len(assets),
        generated_at=datetime.now(timezone.utc),
    )
    cache.set("report", cache_key, result)
    return result
