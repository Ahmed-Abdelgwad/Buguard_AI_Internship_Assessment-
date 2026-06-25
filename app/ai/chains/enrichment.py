"""Automated enrichment & categorization chain.

Classifies an asset and optionally persists the enriched metadata back to the DB.
"""
import json

from sqlalchemy.orm import Session

from app.ai import cache
from app.ai.llm import get_llm
from app.ai.prompts.enrichment import enrichment_prompt
from app.schemas.analysis import EnrichRequest, EnrichResponse, EnrichmentResult
from app.schemas.asset import AssetUpdate
from app.services.asset_service import get_asset, update_asset


def run_enrichment(db: Session, req: EnrichRequest) -> EnrichResponse:
    if not req.asset_id and not req.asset:
        raise ValueError("Provide either asset_id or an asset dict")

    # Build the raw dict to send to the LLM
    if req.asset_id:
        db_asset = get_asset(db, req.asset_id)
        if not db_asset:
            raise ValueError(f"Asset '{req.asset_id}' not found")
        asset_dict = {
            "id": db_asset.id,
            "type": db_asset.type,
            "value": db_asset.value,
            "status": db_asset.status,
            "source": db_asset.source,
            "tags": db_asset.tags,
            "metadata": db_asset.metadata_,
        }
    else:
        asset_dict = req.asset
        db_asset = None

    cache_key = {"asset": asset_dict}
    cached = cache.get("enrichment", cache_key)
    if cached:
        return cached

    asset_json = json.dumps(asset_dict, default=str)

    llm = get_llm()
    chain = enrichment_prompt | llm.with_structured_output(EnrichmentResult)

    try:
        enrichment: EnrichmentResult = chain.invoke({"asset_json": asset_json})
    except Exception as exc:
        enrichment = EnrichmentResult(
            environment="unknown",
            category="unknown",
            criticality="low",
            enriched_metadata={},
            reasoning=f"Enrichment failed: {exc}",
        )

    # Persist enriched metadata back to the asset if we have a DB asset
    asset_updated = False
    if db_asset and enrichment.enriched_metadata:
        update = AssetUpdate(
            metadata={
                "environment": enrichment.environment,
                "category": enrichment.category,
                "criticality": enrichment.criticality,
                **enrichment.enriched_metadata,
            }
        )
        update_asset(db, db_asset, update)
        asset_updated = True

    result = EnrichResponse(
        asset_id=req.asset_id,
        enrichment=enrichment,
        asset_updated=asset_updated,
    )
    cache.set("enrichment", cache_key, result)
    return result
