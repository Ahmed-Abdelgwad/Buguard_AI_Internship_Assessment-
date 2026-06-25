"""LangChain @tool definitions that wrap the asset service and AI chains.

These tools are used by the agentic mode (agent.py) so the LLM can call
real database operations rather than fabricating answers.
"""
import json
from typing import Optional

from langchain_core.tools import tool

# Tools receive a db session injected via a factory; we use a thread-local approach
# so the agent can call tools without passing the session explicitly.
_db_session_factory = None


def set_db_session_factory(factory):
    """Called once at startup to register the SQLAlchemy session factory."""
    global _db_session_factory
    _db_session_factory = factory


def _get_db():
    if _db_session_factory is None:
        raise RuntimeError("DB session factory not configured")
    return _db_session_factory()


@tool
def search_assets(
    type: Optional[str] = None,
    status: Optional[str] = None,
    tag: Optional[str] = None,
    value_contains: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Search assets in the database with optional filters.

    Args:
        type: Asset type filter (domain, subdomain, ip_address, service, certificate, technology)
        status: Status filter (active, stale, archived)
        tag: Tag to filter by
        value_contains: Substring to search in asset values
        page: Page number (default 1)
        page_size: Results per page (default 20, max 100)
    """
    from app.models.asset import AssetStatus, AssetType
    from app.schemas.asset import AssetListParams
    from app.services.asset_service import list_assets

    db = _get_db()
    try:
        params = AssetListParams(
            type=AssetType(type) if type else None,
            status=AssetStatus(status) if status else None,
            tag=tag,
            value_contains=value_contains,
            page=page,
            page_size=min(page_size, 100),
        )
        page_result = list_assets(db, params)
        items = []
        for a in page_result.items:
            item = {
                "id": a.id,
                "type": a.type,
                "value": a.value,
                "status": a.status,
                "tags": a.tags,
                "last_seen": a.last_seen.isoformat() if a.last_seen else None,
            }
            # Include expiry metadata for certificates so the agent can detect expiry without
            # needing a separate get_asset_details call per certificate.
            if a.type == "certificate":
                meta = getattr(a, "metadata_", None) or getattr(a, "metadata", None) or {}
                expires = meta.get("expires") or meta.get("expiry") or meta.get("not_after")
                if expires:
                    item["expires"] = expires
            items.append(item)
        return json.dumps({"total": page_result.total, "items": items}, default=str)
    finally:
        db.close()


@tool
def get_asset_details(asset_id: str) -> str:
    """Get full details of a specific asset by its ID.

    Args:
        asset_id: The unique identifier of the asset
    """
    from app.services.asset_service import get_asset

    db = _get_db()
    try:
        asset = get_asset(db, asset_id)
        if not asset:
            return json.dumps({"error": f"Asset '{asset_id}' not found"})
        return json.dumps(
            {
                "id": asset.id,
                "type": asset.type,
                "value": asset.value,
                "status": asset.status,
                "first_seen": asset.first_seen.isoformat() if asset.first_seen else None,
                "last_seen": asset.last_seen.isoformat() if asset.last_seen else None,
                "source": asset.source,
                "tags": asset.tags,
                "metadata": asset.metadata_,
            },
            default=str,
        )
    finally:
        db.close()


@tool
def get_asset_relationships(asset_id: str) -> str:
    """Get all relationships and connected assets for a given asset ID.

    Args:
        asset_id: The unique identifier of the asset
    """
    from app.services.asset_service import get_asset_graph

    db = _get_db()
    try:
        graph = get_asset_graph(db, asset_id)
        if not graph:
            return json.dumps({"error": f"Asset '{asset_id}' not found"})
        return json.dumps(
            {
                "asset_id": asset_id,
                "relationships": [
                    {
                        "from": r.from_asset_id,
                        "to": r.to_asset_id,
                        "type": r.rel_type,
                    }
                    for r in graph["relationships"]
                ],
                "related_asset_ids": [a.id for a in graph["related_assets"]],
                "related_asset_values": [a.value for a in graph["related_assets"]],
            },
            default=str,
        )
    finally:
        db.close()


ALL_TOOLS = [search_assets, get_asset_details, get_asset_relationships]
