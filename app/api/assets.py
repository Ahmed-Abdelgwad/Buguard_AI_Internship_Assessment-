"""Asset endpoints — bulk import and list (Track B minimal API)."""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_api_key
from app.database import get_db
from app.models.asset import AssetStatus, AssetType
from app.schemas.asset import AssetListParams, AssetPage, BulkImportResult
from app.services import asset_service, import_service

router = APIRouter(prefix="/assets", tags=["Assets"])


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=AssetPage, summary="List assets with filtering and pagination")
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


# ── Bulk import ───────────────────────────────────────────────────────────────

@router.post(
    "/import",
    response_model=BulkImportResult,
    status_code=status.HTTP_200_OK,
    summary="Bulk import assets (idempotent — safe to re-run)",
    dependencies=[Depends(require_api_key)],
)
def bulk_import(records: list[Any], db: Session = Depends(get_db)):
    if not isinstance(records, list):
        raise HTTPException(status_code=422, detail="Payload must be a JSON array")
    return import_service.bulk_import(db, records)
