"""Asset endpoints — list, graph, bulk import, lifecycle refresh."""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_reader
from app.database import get_db
from app.models.asset import AssetStatus, AssetType
from app.schemas.asset import AssetListParams, AssetOut, AssetPage, BulkImportResult, LifecycleRefreshResult
from app.services import asset_service, import_service, lifecycle_service

router = APIRouter(prefix="/assets", tags=["Assets"])


# ── List (reader+) ────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=AssetPage,
    summary="List assets with filtering and pagination",
    dependencies=[Depends(require_reader)],
)
def list_assets(
    type: AssetType | None = Query(None),
    status: AssetStatus | None = Query(None),
    tag: str | None = Query(None),
    value_contains: str | None = Query(None),
    sort_by: str = Query("last_seen", pattern="^(id|type|value|status|first_seen|last_seen|source)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    params = AssetListParams(
        type=type,
        status=status,
        tag=tag,
        value_contains=value_contains,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
    )
    return asset_service.list_assets(db, params)


# ── Single asset (reader+) ────────────────────────────────────────────────────

@router.get(
    "/{asset_id}",
    response_model=AssetOut,
    summary="Get a single asset by ID",
    dependencies=[Depends(require_reader)],
)
def get_asset(asset_id: str, db: Session = Depends(get_db)):
    asset = asset_service.get_asset(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found")
    return asset


# ── Relationship graph (reader+) ──────────────────────────────────────────────

@router.get(
    "/{asset_id}/graph",
    summary="Get the relationship graph for an asset (JSON)",
    dependencies=[Depends(require_reader)],
)
def get_asset_graph(asset_id: str, db: Session = Depends(get_db)):
    graph = asset_service.get_asset_graph(db, asset_id)
    if not graph:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found")
    asset = graph["asset"]
    return {
        "nodes": [
            {"id": asset.id, "label": asset.value, "type": asset.type, "status": asset.status, "group": "root"}
        ] + [
            {"id": a.id, "label": a.value, "type": str(a.type), "status": str(a.status), "group": str(a.type)}
            for a in graph["related_assets"]
        ],
        "edges": [
            {"from": r.from_asset_id, "to": r.to_asset_id, "label": r.rel_type}
            for r in graph["relationships"]
        ],
    }


# ── Bulk import (admin only) ──────────────────────────────────────────────────

@router.post(
    "/import",
    response_model=BulkImportResult,
    status_code=status.HTTP_200_OK,
    summary="Bulk import assets (idempotent — safe to re-run)",
    dependencies=[Depends(require_admin)],
)
def bulk_import(records: list[Any], db: Session = Depends(get_db)):
    if not isinstance(records, list):
        raise HTTPException(status_code=422, detail="Payload must be a JSON array")
    return import_service.bulk_import(db, records)


# ── Certificate lifecycle refresh (admin only) ────────────────────────────────

@router.post(
    "/lifecycle/refresh",
    response_model=LifecycleRefreshResult,
    status_code=status.HTTP_200_OK,
    summary="Refresh certificate lifecycle status (expired / expiring-soon)",
    dependencies=[Depends(require_admin)],
)
def lifecycle_refresh(db: Session = Depends(get_db)):
    """Scan all certificate assets and update their status and tags based on expiry dates.

    - Expired certs (`expires < now`) → `status=stale`, tag `expired` added
    - Expiring within 30 days         → tag `expiring-soon` added
    - Renewed / still valid certs     → lifecycle tags cleared, reactivated if applicable

    Also runs automatically every 24 hours via the background scheduler.
    """
    return lifecycle_service.refresh_certificate_lifecycle(db)
