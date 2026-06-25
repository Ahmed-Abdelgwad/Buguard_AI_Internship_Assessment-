"""CRUD, deduplication, lifecycle, and pagination logic for assets."""
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import or_, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.asset import Asset, AssetStatus
from app.models.relationship import AssetRelationship
from app.schemas.asset import AssetCreate, AssetListParams, AssetPage, AssetUpdate


# ── Read ──────────────────────────────────────────────────────────────────────

def get_asset(db: Session, asset_id: str) -> Optional[Asset]:
    return db.get(Asset, asset_id)


def list_assets(db: Session, params: AssetListParams) -> AssetPage:
    q = db.query(Asset)

    if params.type:
        q = q.filter(Asset.type == params.type)
    if params.status:
        q = q.filter(Asset.status == params.status)
    if params.tag:
        dialect = db.get_bind().dialect.name
        if dialect == "postgresql":
            # PostgreSQL JSONB: use @> containment
            from sqlalchemy.dialects.postgresql import JSONB
            import json as _json
            q = q.filter(Asset.tags.cast(JSONB).contains(_json.dumps([params.tag])))
        else:
            # SQLite: JSON stored as text like ["tag1","tag2"]; match quoted tag
            from sqlalchemy import cast, Text
            q = q.filter(cast(Asset.tags, Text).contains(f'"{params.tag}"'))
    if params.value_contains:
        q = q.filter(Asset.value.ilike(f"%{params.value_contains}%"))

    # Sorting
    sort_col = getattr(Asset, params.sort_by, Asset.last_seen)
    if params.sort_dir == "asc":
        q = q.order_by(sort_col.asc())
    else:
        q = q.order_by(sort_col.desc())

    total = q.count()
    offset = (params.page - 1) * params.page_size
    items = q.offset(offset).limit(params.page_size).all()
    pages = max(1, math.ceil(total / params.page_size))

    return AssetPage(
        items=items,
        total=total,
        page=params.page,
        page_size=params.page_size,
        pages=pages,
    )


# ── Create / upsert (dedup) ───────────────────────────────────────────────────

def _merge_tags(existing: list[str], incoming: list[str]) -> list[str]:
    return sorted(set(existing or []) | set(incoming or []))


def upsert_asset(db: Session, data: AssetCreate) -> tuple[Asset, bool]:
    """Insert or update an asset using (type, value) as the dedup key.

    Returns (asset, created) where created=True means a new row was inserted.

    Uses dialect-aware strategy:
    - PostgreSQL: atomic ON CONFLICT DO UPDATE with JSONB / ARRAY operators.
    - Other (SQLite for tests): check-then-insert-or-update within the session.
    """
    now = datetime.now(timezone.utc)

    dialect = db.get_bind().dialect.name

    if dialect == "postgresql":
        asset_id = data.id or str(uuid.uuid4())
        stmt = (
            pg_insert(Asset)
            .values(
                id=asset_id,
                type=data.type,
                value=data.value,
                status=data.status,
                first_seen=now,
                last_seen=now,
                source=data.source,
                tags=data.tags,
                metadata_=data.metadata,
            )
            .on_conflict_do_update(
                index_elements=["type", "value"],
                set_={
                    "last_seen": now,
                    # JSONB merge: existing || incoming (incoming wins on conflict)
                    "metadata": text("assets.metadata || EXCLUDED.metadata"),
                    # JSONB array union (dedup)
                    "tags": text(
                        "(SELECT jsonb_agg(elem) FROM "
                        "(SELECT DISTINCT elem FROM "
                        "jsonb_array_elements_text(assets.tags || EXCLUDED.tags) AS elem) sub)"
                    ),
                    # Re-activate stale assets that re-appear
                    "status": text(
                        "CASE WHEN assets.status = 'stale' THEN 'active'::asset_status "
                        "ELSE assets.status END"
                    ),
                },
            )
            .returning(Asset.id, Asset.first_seen)
        )
        result = db.execute(stmt)
        row = result.fetchone()
        db.commit()
        asset = db.get(Asset, row[0])
        # first_seen == now means the row was just inserted
        created = abs((asset.first_seen.replace(tzinfo=timezone.utc) - now).total_seconds()) < 1
        return asset, created
    else:
        # SQLite-compatible fallback (used in tests)
        existing = (
            db.query(Asset)
            .filter(Asset.type == data.type, Asset.value == data.value)
            .first()
        )
        if existing:
            existing.last_seen = now
            existing.tags = _merge_tags(existing.tags or [], data.tags or [])
            existing.metadata_ = {**(existing.metadata_ or {}), **(data.metadata or {})}
            if existing.status == AssetStatus.stale:
                existing.status = AssetStatus.active
            db.commit()
            db.refresh(existing)
            return existing, False
        else:
            asset = Asset(
                id=data.id or str(uuid.uuid4()),
                type=data.type,
                value=data.value,
                status=data.status,
                first_seen=now,
                last_seen=now,
                source=data.source,
                tags=data.tags or [],
                metadata_=data.metadata or {},
            )
            db.add(asset)
            db.commit()
            db.refresh(asset)
            return asset, True


# ── Update ────────────────────────────────────────────────────────────────────

def update_asset(db: Session, asset: Asset, data: AssetUpdate) -> Asset:
    if data.status is not None:
        asset.status = data.status
    if data.source is not None:
        asset.source = data.source
    if data.tags is not None:
        asset.tags = _merge_tags(asset.tags, data.tags)
    if data.metadata is not None:
        asset.metadata_ = {**(asset.metadata_ or {}), **data.metadata}
    asset.last_seen = datetime.now(timezone.utc)
    db.commit()
    db.refresh(asset)
    return asset



# ── Relationships ─────────────────────────────────────────────────────────────

def create_relationship(
    db: Session, from_id: str, to_id: str, rel_type: str
) -> AssetRelationship:
    dialect = db.get_bind().dialect.name

    if dialect == "postgresql":
        stmt = (
            pg_insert(AssetRelationship)
            .values(
                id=uuid.uuid4(),
                from_asset_id=from_id,
                to_asset_id=to_id,
                rel_type=rel_type,
            )
            .on_conflict_do_nothing(index_elements=["from_asset_id", "to_asset_id", "rel_type"])
            .returning(AssetRelationship.id)
        )
        result = db.execute(stmt)
        db.commit()
        row = result.fetchone()
        if row:
            return db.get(AssetRelationship, row[0])
    else:
        # SQLite fallback (used in tests)
        existing = (
            db.query(AssetRelationship)
            .filter_by(from_asset_id=from_id, to_asset_id=to_id, rel_type=rel_type)
            .first()
        )
        if existing:
            return existing
        rel = AssetRelationship(
            id=uuid.uuid4(),
            from_asset_id=from_id,
            to_asset_id=to_id,
            rel_type=rel_type,
        )
        db.add(rel)
        db.commit()
        db.refresh(rel)
        return rel

    # PostgreSQL: relationship already existed
    return (
        db.query(AssetRelationship)
        .filter_by(from_asset_id=from_id, to_asset_id=to_id, rel_type=rel_type)
        .first()
    )


def get_asset_graph(db: Session, asset_id: str) -> dict[str, Any]:
    """Return the asset plus all directly connected assets and their relationships."""
    asset = get_asset(db, asset_id)
    if not asset:
        return None

    rels = (
        db.query(AssetRelationship)
        .filter(
            or_(
                AssetRelationship.from_asset_id == asset_id,
                AssetRelationship.to_asset_id == asset_id,
            )
        )
        .all()
    )

    related_ids = set()
    for r in rels:
        related_ids.add(r.from_asset_id)
        related_ids.add(r.to_asset_id)
    related_ids.discard(asset_id)

    related_assets = db.query(Asset).filter(Asset.id.in_(related_ids)).all()
    return {"asset": asset, "relationships": rels, "related_assets": related_assets}
