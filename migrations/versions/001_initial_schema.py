"""Initial schema: assets and asset_relationships tables

Revision ID: 001
Revises:
Create Date: 2026-06-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enums
    asset_type = postgresql.ENUM(
        "domain", "subdomain", "ip_address", "service", "certificate", "technology",
        name="asset_type",
    )
    asset_status = postgresql.ENUM("active", "stale", "archived", name="asset_status")
    asset_type.create(op.get_bind(), checkfirst=True)
    asset_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "assets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("type", postgresql.ENUM("domain", "subdomain", "ip_address", "service", "certificate", "technology", name="asset_type", create_type=False), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("status", postgresql.ENUM("active", "stale", "archived", name="asset_status", create_type=False), nullable=False, server_default="active"),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
    )

    # Deduplication unique index
    op.create_index("uq_asset_type_value", "assets", ["type", "value"], unique=True)

    # Query indexes
    op.create_index("ix_assets_type", "assets", ["type"])
    op.create_index("ix_assets_status", "assets", ["status"])
    op.create_index("ix_assets_tags", "assets", ["tags"], postgresql_using="gin", postgresql_ops={"tags": "jsonb_ops"})
    op.create_index("ix_assets_last_seen", "assets", ["last_seen"])

    op.create_table(
        "asset_relationships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("from_asset_id", sa.String(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_asset_id", sa.String(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rel_type", sa.String(64), nullable=False),
    )

    op.create_index("ix_rel_from", "asset_relationships", ["from_asset_id"])
    op.create_index("ix_rel_to", "asset_relationships", ["to_asset_id"])
    op.create_index(
        "uq_relationship",
        "asset_relationships",
        ["from_asset_id", "to_asset_id", "rel_type"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("asset_relationships")
    op.drop_table("assets")
    op.execute("DROP TYPE IF EXISTS asset_type")
    op.execute("DROP TYPE IF EXISTS asset_status")
