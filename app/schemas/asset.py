from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.asset import AssetStatus, AssetType


class AssetCreate(BaseModel):
    id: Optional[str] = None
    type: AssetType
    value: str = Field(..., min_length=1, max_length=2048)
    status: AssetStatus = AssetStatus.active
    source: str = Field(..., min_length=1, max_length=64)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tags")
    @classmethod
    def tags_no_empty(cls, v: list[str]) -> list[str]:
        return [t.strip() for t in v if t.strip()]


class AssetUpdate(BaseModel):
    status: Optional[AssetStatus] = None
    source: Optional[str] = Field(None, min_length=1, max_length=64)
    tags: Optional[list[str]] = None
    metadata: Optional[dict[str, Any]] = None

    @field_validator("tags")
    @classmethod
    def tags_no_empty(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        return [t.strip() for t in v if t.strip()]


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    type: AssetType
    value: str
    status: AssetStatus
    first_seen: datetime
    last_seen: datetime
    source: str
    tags: list[str]
    # validation_alias maps from ORM's `metadata_`; serialization uses field name `metadata`
    metadata: dict[str, Any] = Field(validation_alias="metadata_")


class AssetListParams(BaseModel):
    type: Optional[AssetType] = None
    status: Optional[AssetStatus] = None
    tag: Optional[str] = None
    value_contains: Optional[str] = None
    sort_by: str = "last_seen"
    sort_dir: str = "desc"
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=500)


class AssetPage(BaseModel):
    items: list[AssetOut]
    total: int
    page: int
    page_size: int
    pages: int


class ImportRecord(AssetCreate):
    """One record from a bulk import payload.

    Relationship fields are captured for phase-2 relationship creation
    and are NOT persisted as asset fields.
    """
    parent: Optional[str] = None
    covers: Optional[str] = None
    resolves_to: Optional[str] = None
    runs_on: Optional[str] = None
    hosted_on: Optional[str] = None


class ImportFailure(BaseModel):
    index: int
    record: Any
    error: str


class BulkImportResult(BaseModel):
    imported: int
    updated: int
    failed: int
    failures: list[ImportFailure] = Field(default_factory=list)


class LifecycleRefreshResult(BaseModel):
    certificates_scanned: int
    expired: int
    expiring_soon: int
    renewed: int
    valid: int
    no_expiry_data: int
    scanned_at: datetime
