"""Risk scoring & summarization chain.

All assets are fetched from the DB before being sent to the LLM.
The LLM only scores; it cannot invent asset IDs or values.
"""
import json
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.ai import cache
from app.ai.llm import get_llm
from app.ai.prompts.risk_scoring import risk_scoring_prompt
from app.models.asset import Asset
from app.schemas.analysis import RiskRequest, RiskResponse
from app.schemas.asset import AssetListParams
from app.services.asset_service import get_asset, list_assets


def run_risk_scoring(db: Session, req: RiskRequest) -> RiskResponse:
    cache_key = req.model_dump(mode="json")
    cached = cache.get("risk_scoring", cache_key)
    if cached:
        return cached

    # Fetch real assets from DB
    if req.asset_ids:
        assets = [a for aid in req.asset_ids if (a := get_asset(db, aid))]
    else:
        params = AssetListParams(
            type=req.type, status=req.status, tag=req.tag, page=1, page_size=100
        )
        assets = list_assets(db, params).items

    if not assets:
        result = RiskResponse(
            overall_score=0,
            risk_level="low",
            findings=[],
            summary="No assets matched the specified criteria.",
            assets_analyzed=0,
        )
        cache.set("risk_scoring", cache_key, result)
        return result

    assets_json = json.dumps([_asset_to_dict(a) for a in assets], default=str)
    today = date.today().isoformat()

    llm = get_llm()
    chain = risk_scoring_prompt | llm.with_structured_output(RiskResponse)

    try:
        result: RiskResponse = chain.invoke({
            "today": today,
            "count": len(assets),
            "assets_json": assets_json,
        })
    except Exception as exc:
        result = RiskResponse(
            overall_score=0,
            risk_level="low",
            findings=[],
            summary=f"Risk analysis failed: {exc}",
            assets_analyzed=len(assets),
        )

    result.assets_analyzed = len(assets)
    cache.set("risk_scoring", cache_key, result)
    return result


def _asset_to_dict(asset) -> dict:
    # Works with both ORM Asset (uses metadata_) and Pydantic AssetOut (uses metadata)
    metadata = getattr(asset, "metadata_", None) or getattr(asset, "metadata", {})
    return {
        "id": asset.id,
        "type": str(asset.type),
        "value": asset.value,
        "status": str(asset.status),
        "first_seen": asset.first_seen.isoformat() if asset.first_seen else None,
        "last_seen": asset.last_seen.isoformat() if asset.last_seen else None,
        "source": asset.source,
        "tags": list(asset.tags or []),
        "metadata": metadata or {},
    }
