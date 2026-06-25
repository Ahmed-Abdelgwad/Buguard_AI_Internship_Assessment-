"""Bulk import logic with per-record error isolation and relationship extraction."""
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.ai import cache
from app.schemas.asset import BulkImportResult, ImportFailure, ImportRecord
from app.services import asset_service

# Map of import-record field → relationship type
_REL_FIELD_MAP = {
    "parent": "subdomain_of",
    "covers": "covers",
    "resolves_to": "resolves_to",
    "runs_on": "runs_on",
    "hosted_on": "hosted_on",
}


def bulk_import(db: Session, records: list[Any]) -> BulkImportResult:
    """Ingest a list of raw dicts as assets.

    Per-record failures are captured; a bad record never aborts the rest of the batch.
    Relationships encoded as ``parent``, ``covers``, etc. are created after all assets.
    """
    imported = 0
    updated = 0
    failures: list[ImportFailure] = []

    # Phase 1: upsert assets, collect relationship intentions
    relationship_intentions: list[tuple[str, str, str]] = []  # (from_id, to_id, rel_type)
    asset_id_map: dict[str, str] = {}  # original import id → db id

    for idx, raw in enumerate(records):
        if not isinstance(raw, dict):
            failures.append(ImportFailure(index=idx, record=raw, error="Record is not a JSON object"))
            continue
        try:
            record = ImportRecord.model_validate(raw)
        except ValidationError as exc:
            failures.append(ImportFailure(index=idx, record=raw, error=str(exc)))
            continue

        try:
            asset, created = asset_service.upsert_asset(db, record)
        except Exception as exc:
            db.rollback()
            failures.append(ImportFailure(index=idx, record=raw, error=str(exc)))
            continue

        original_id = raw.get("id") or record.id
        if original_id:
            asset_id_map[original_id] = asset.id

        if created:
            imported += 1
        else:
            updated += 1

        # Collect relationships for phase 2
        for field, rel_type in _REL_FIELD_MAP.items():
            target_original_id = raw.get(field)
            if target_original_id:
                relationship_intentions.append((asset.id, target_original_id, rel_type))

    # Phase 2: create relationships, resolving original IDs → db IDs
    for from_id, target_original_id, rel_type in relationship_intentions:
        to_id = asset_id_map.get(target_original_id, target_original_id)
        try:
            asset_service.create_relationship(db, from_id, to_id, rel_type)
        except Exception:
            # Relationship failures are non-fatal (e.g. target not in this batch)
            pass

    # Invalidate all cached AI results — the DB just changed.
    # Stale cache would return outdated counts/assets to nl_query, risk, and report chains.
    if imported or updated:
        cache.clear()

    return BulkImportResult(
        imported=imported,
        updated=updated,
        failed=len(failures),
        failures=failures,
    )
