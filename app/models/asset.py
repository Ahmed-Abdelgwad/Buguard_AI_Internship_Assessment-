import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AssetType(str, enum.Enum):
    domain = "domain"
    subdomain = "subdomain"
    ip_address = "ip_address"
    service = "service"
    certificate = "certificate"
    technology = "technology"


class AssetStatus(str, enum.Enum):
    active = "active"
    stale = "stale"
    archived = "archived"


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    type: Mapped[AssetType] = mapped_column(Enum(AssetType, name="asset_type"), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[AssetStatus] = mapped_column(
        Enum(AssetStatus, name="asset_status"),
        nullable=False,
        default=AssetStatus.active,
        server_default="active",
    )
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("uq_asset_type_value", "type", "value", unique=True),
        Index("ix_assets_type", "type"),
        Index("ix_assets_status", "status"),
        Index("ix_assets_last_seen", "last_seen"),
    )

    def __repr__(self) -> str:
        return f"<Asset id={self.id} type={self.type} value={self.value}>"
