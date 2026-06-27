"""Certificate lifecycle scanner.

Scans all certificate assets and updates their status and tags based on expiry dates:
  - expired  (expires < now)              → status=stale, tag "expired"
  - expiring-soon (now <= expires < +30d) → status=active, tag "expiring-soon"
  - valid    (expires >= now + 30d)       → clears lifecycle tags; reactivates if stale from expiry

The "expired" tag is used as a sentinel: if we set an asset to stale because it
was expired, and a future run finds the cert renewed, we know it's safe to
reactivate (rather than accidentally waking something stale for another reason).
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.asset import Asset, AssetStatus, AssetType
from app.schemas.asset import LifecycleRefreshResult

_EXPIRING_SOON_DAYS = 30


def _parse_expiry(metadata: dict) -> Optional[datetime]:
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


def refresh_certificate_lifecycle(db: Session) -> LifecycleRefreshResult:
    """Scan all certificate assets and sync their status/tags with expiry dates."""
    now = datetime.now(timezone.utc)
    expiring_threshold = now + timedelta(days=_EXPIRING_SOON_DAYS)

    certs = db.query(Asset).filter(Asset.type == AssetType.certificate).all()

    expired_count = 0
    expiring_soon_count = 0
    renewed_count = 0
    valid_count = 0
    no_expiry_count = 0

    for cert in certs:
        expiry = _parse_expiry(cert.metadata_ or {})

        if expiry is None:
            no_expiry_count += 1
            continue

        tags: set[str] = set(cert.tags or [])
        new_tags = set(tags)
        new_status = cert.status

        if expiry < now:
            # Expired: mark stale and tag
            new_tags = (tags | {"expired"}) - {"expiring-soon"}
            if cert.status == AssetStatus.active:
                new_status = AssetStatus.stale
            expired_count += 1

        elif expiry < expiring_threshold:
            # Expiring soon: tag and reactivate if we're the reason it's stale
            if cert.status == AssetStatus.stale and "expired" in tags:
                new_status = AssetStatus.active
            new_tags = (tags | {"expiring-soon"}) - {"expired"}
            expiring_soon_count += 1

        else:
            # Valid: clear lifecycle tags; reactivate if we caused the stale status
            was_expired = "expired" in tags
            new_tags = tags - {"expired", "expiring-soon"}
            if cert.status == AssetStatus.stale and was_expired:
                new_status = AssetStatus.active
                renewed_count += 1
            valid_count += 1

        # Only write to DB if something actually changed
        if new_tags != tags or new_status != cert.status:
            cert.tags = sorted(new_tags)
            cert.status = new_status
            cert.last_seen = now

    db.commit()

    return LifecycleRefreshResult(
        certificates_scanned=len(certs),
        expired=expired_count,
        expiring_soon=expiring_soon_count,
        renewed=renewed_count,
        valid=valid_count,
        no_expiry_data=no_expiry_count,
        scanned_at=now,
    )
