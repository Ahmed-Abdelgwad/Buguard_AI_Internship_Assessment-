"""Natural-language asset query chain.

Anti-hallucination design:
  1. LLM extracts *filter parameters only* — never generates asset data.
  2. Actual results come exclusively from the database via asset_service.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ai import cache
from app.ai.llm import get_llm
from app.ai.prompts.nl_query import nl_query_prompt
from app.schemas.analysis import FilterParams, NLQueryResponse
from app.schemas.asset import AssetListParams
from app.services.asset_service import list_assets


def run_nl_query(db: Session, question: str) -> NLQueryResponse:
    cached = cache.get("nl_query", {"question": question})
    if cached:
        return cached

    llm = get_llm()
    chain = nl_query_prompt | llm.with_structured_output(FilterParams)

    today = datetime.now(timezone.utc).date().isoformat()
    filter_extraction_failed = False
    try:
        filter_params: FilterParams = chain.invoke({"question": question, "today": today})
    except Exception:
        filter_params = FilterParams()
        filter_extraction_failed = True

    # Translate FilterParams → AssetListParams for the DB query
    params = AssetListParams(
        type=filter_params.type,
        status=filter_params.status,
        tag=filter_params.tag,
        value_contains=filter_params.value_contains,
        page=1,
        page_size=100,
    )

    page = list_assets(db, params)
    assets = page.items

    # Post-filter by cert expiry dates if specified (DB doesn't index metadata.expires)
    if filter_params.expired_before:
        cutoff = filter_params.expired_before
        assets = [
            a for a in assets
            if _parse_expiry(a.metadata_) and _parse_expiry(a.metadata_) < cutoff
        ]
    if filter_params.expired_after:
        cutoff = filter_params.expired_after
        assets = [
            a for a in assets
            if _parse_expiry(a.metadata_) and _parse_expiry(a.metadata_) > cutoff
        ]

    active_filters = filter_params.model_dump(exclude_none=True)
    if filter_extraction_failed or not active_filters:
        summary = (
            f"Could not extract specific filters from your query — showing all {len(assets)} asset(s). "
            "Try rephrasing with explicit terms like 'active domains' or 'prod certificates'."
        )
    else:
        summary = (
            f"Found {len(assets)} asset(s) matching your query "
            f"with filters: {active_filters}"
        )

    result = NLQueryResponse(
        question=question,
        interpreted_filters=filter_params,
        assets=assets,
        total=len(assets),
        summary=summary,
    )
    cache.set("nl_query", {"question": question}, result)
    return result


def _parse_expiry(metadata: dict) -> datetime | None:
    raw = metadata.get("expires") or metadata.get("expiry") or metadata.get("not_after")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None
