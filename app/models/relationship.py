import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AssetRelationship(Base):
    __tablename__ = "asset_relationships"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    from_asset_id: Mapped[str] = mapped_column(
        String, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    to_asset_id: Mapped[str] = mapped_column(
        String, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    # subdomain_of | covers | resolves_to | runs_on | hosted_on
    rel_type: Mapped[str] = mapped_column(String(64), nullable=False)

    from_asset = relationship("Asset", foreign_keys=[from_asset_id])
    to_asset = relationship("Asset", foreign_keys=[to_asset_id])

    __table_args__ = (
        Index("ix_rel_from", "from_asset_id"),
        Index("ix_rel_to", "to_asset_id"),
        Index("uq_relationship", "from_asset_id", "to_asset_id", "rel_type", unique=True),
    )

    def __repr__(self) -> str:
        return f"<Rel {self.from_asset_id} --{self.rel_type}--> {self.to_asset_id}>"
