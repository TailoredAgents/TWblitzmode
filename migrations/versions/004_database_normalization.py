"""Database relationship normalization and auditing

Revision ID: 004_database_normalization
Revises: 003_master_game_plan_tables
Create Date: 2025-10-09 20:00:00.000000

This migration introduces normalized relationship tables to connect team members,
connectors, and prospects, adds auditing columns, and enforces new foreign keys
and indexes required by the Section 9 implementation roadmap.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "004_database_normalization"
down_revision = "003_master_game_plan_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade database schema for normalized connector relationships."""

    # ------------------------------------------------------------------
    # Create team_member_connectors table
    # ------------------------------------------------------------------
    op.create_table(
        "team_member_connectors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("team_member_id", sa.Integer(), nullable=False),
        sa.Column("connector_id", sa.Integer(), nullable=False),
        sa.Column(
            "relationship_type",
            sa.String(length=50),
            nullable=False,
            server_default="primary",
        ),
        sa.Column(
            "source",
            sa.String(length=50),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("archived_by_id", sa.Integer(), nullable=True),
        sa.Column("archived_reason", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_tmc_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_member_id"],
            ["team_members.id"],
            name="fk_tmc_team_member",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["connector_id"],
            ["connectors.id"],
            name="fk_tmc_connector",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["team_members.id"],
            name="fk_tmc_created_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["team_members.id"],
            name="fk_tmc_updated_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["archived_by_id"],
            ["team_members.id"],
            name="fk_tmc_archived_by",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "team_member_id",
            "connector_id",
            name="uq_tmc_org_team_member_connector",
        ),
    )

    op.create_index(
        "idx_tmc_org_team_member",
        "team_member_connectors",
        ["organization_id", "team_member_id"],
    )
    op.create_index(
        "idx_tmc_connector",
        "team_member_connectors",
        ["connector_id"],
    )
    op.create_index(
        "idx_tmc_active",
        "team_member_connectors",
        ["organization_id", "connector_id"],
    )

    # ------------------------------------------------------------------
    # Alter connectors table
    # ------------------------------------------------------------------
    op.add_column("connectors", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.add_column("connectors", sa.Column("first_name", sa.String(length=100), nullable=True))
    op.add_column("connectors", sa.Column("last_name", sa.String(length=100), nullable=True))
    op.add_column(
        "connectors",
        sa.Column("current_company", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "connectors",
        sa.Column("current_title", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "connectors",
        sa.Column(
            "shared_connections_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column("connectors", sa.Column("created_by_id", sa.Integer(), nullable=True))
    op.add_column("connectors", sa.Column("updated_by_id", sa.Integer(), nullable=True))
    op.add_column("connectors", sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("connectors", sa.Column("archived_by_id", sa.Integer(), nullable=True))
    op.add_column("connectors", sa.Column("archived_reason", sa.Text(), nullable=True))
    op.add_column("connectors", sa.Column("last_verified_at", sa.TIMESTAMP(timezone=True), nullable=True))

    op.create_foreign_key(
        "fk_connectors_created_by",
        "connectors",
        "team_members",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_connectors_updated_by",
        "connectors",
        "team_members",
        ["updated_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_connectors_archived_by",
        "connectors",
        "team_members",
        ["archived_by_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index("idx_connectors_tenant", "connectors", ["tenant_id"])
    op.create_index("idx_connectors_current_company", "connectors", ["current_company"])
    op.create_index(
        "idx_connectors_shared_connections",
        "connectors",
        ["shared_connections_count"],
    )

    # ------------------------------------------------------------------
    # Alter prospect_connectors table
    # ------------------------------------------------------------------
    op.add_column("prospect_connectors", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.add_column(
        "prospect_connectors",
        sa.Column("team_member_connector_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "prospect_connectors",
        sa.Column("source", sa.String(length=50), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "prospect_connectors",
        sa.Column("status_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "prospect_connectors",
        sa.Column("algorithm_version", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "prospect_connectors",
        sa.Column("confidence_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "prospect_connectors",
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "prospect_connectors",
        sa.Column("created_by_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "prospect_connectors",
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "prospect_connectors",
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "prospect_connectors",
        sa.Column("archived_by_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "prospect_connectors",
        sa.Column("archived_reason", sa.Text(), nullable=True),
    )

    op.create_foreign_key(
        "fk_pc_team_member_connector",
        "prospect_connectors",
        "team_member_connectors",
        ["team_member_connector_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_pc_created_by",
        "prospect_connectors",
        "team_members",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_pc_updated_by",
        "prospect_connectors",
        "team_members",
        ["updated_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_pc_archived_by",
        "prospect_connectors",
        "team_members",
        ["archived_by_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "idx_prospect_connectors_source",
        "prospect_connectors",
        ["source"],
    )
    op.create_index(
        "idx_prospect_connectors_status",
        "prospect_connectors",
        ["status"],
    )
    op.create_index(
        "idx_prospect_connectors_last_seen",
        "prospect_connectors",
        ["last_seen_at"],
    )

    # ------------------------------------------------------------------
    # Backfill data for new tables and columns
    # ------------------------------------------------------------------
    op.execute(
        """
        UPDATE connectors
        SET tenant_id = organization_id
        WHERE tenant_id IS NULL AND organization_id IS NOT NULL;
        """
    )

    op.execute(
        """
        UPDATE connectors
        SET first_name = split_part(full_name, ' ', 1),
            last_name = NULLIF(trim(substring(full_name from position(' ' IN full_name) + 1)), '')
        WHERE full_name IS NOT NULL AND (first_name IS NULL OR last_name IS NULL);
        """
    )

    op.execute(
        """
        INSERT INTO team_member_connectors (
            organization_id,
            team_member_id,
            connector_id,
            relationship_type,
            source,
            created_at,
            updated_at,
            last_seen_at
        )
        SELECT DISTINCT
            organization_id,
            team_member_id,
            connector_id,
            'primary',
            'legacy_backfill',
            NOW(),
            NOW(),
            NOW()
        FROM prospect_connectors
        WHERE team_member_id IS NOT NULL
        ON CONFLICT (organization_id, team_member_id, connector_id)
        DO UPDATE SET
            last_seen_at = EXCLUDED.last_seen_at,
            updated_at = NOW();
        """
    )

    op.execute(
        """
        UPDATE prospect_connectors pc
        SET tenant_id = pc.organization_id
        WHERE tenant_id IS NULL AND organization_id IS NOT NULL;
        """
    )

    op.execute(
        """
        UPDATE prospect_connectors pc
        SET team_member_connector_id = tmc.id,
            last_seen_at = COALESCE(pc.last_seen_at, pc.updated_at, NOW()),
            source = CASE WHEN pc.source IS NULL OR pc.source = 'unknown'
                          THEN 'legacy_backfill' ELSE pc.source END,
            algorithm_version = COALESCE(pc.algorithm_version, 'legacy'),
            confidence_score = COALESCE(
                pc.confidence_score,
                CASE
                    WHEN pc.shared_connections_count IS NOT NULL AND pc.shared_connections_count > 0
                        THEN LEAST(1.0, 0.35 + (pc.shared_connections_count * 0.05))
                    ELSE 0.25
                END
            )
        FROM team_member_connectors tmc
        WHERE pc.team_member_connector_id IS NULL
          AND pc.team_member_id IS NOT NULL
          AND pc.organization_id = tmc.organization_id
          AND pc.team_member_id = tmc.team_member_id
          AND pc.connector_id = tmc.connector_id;
        """
    )

    # Remove server defaults set during column creation
    op.alter_column(
        "connectors",
        "shared_connections_count",
        server_default=None,
        existing_type=sa.Integer(),
    )
    op.alter_column(
        "prospect_connectors",
        "source",
        server_default=None,
        existing_type=sa.String(length=50),
    )


def downgrade() -> None:
    """Revert connector normalization changes."""

    op.drop_index("idx_prospect_connectors_last_seen", table_name="prospect_connectors")
    op.drop_index("idx_prospect_connectors_status", table_name="prospect_connectors")
    op.drop_index("idx_prospect_connectors_source", table_name="prospect_connectors")

    op.drop_constraint("fk_pc_archived_by", "prospect_connectors", type_="foreignkey")
    op.drop_constraint("fk_pc_updated_by", "prospect_connectors", type_="foreignkey")
    op.drop_constraint("fk_pc_created_by", "prospect_connectors", type_="foreignkey")
    op.drop_constraint("fk_pc_team_member_connector", "prospect_connectors", type_="foreignkey")

    op.drop_column("prospect_connectors", "archived_reason")
    op.drop_column("prospect_connectors", "archived_by_id")
    op.drop_column("prospect_connectors", "archived_at")
    op.drop_column("prospect_connectors", "updated_by_id")
    op.drop_column("prospect_connectors", "created_by_id")
    op.drop_column("prospect_connectors", "last_seen_at")
    op.drop_column("prospect_connectors", "confidence_score")
    op.drop_column("prospect_connectors", "algorithm_version")
    op.drop_column("prospect_connectors", "status_reason")
    op.drop_column("prospect_connectors", "source")
    op.drop_column("prospect_connectors", "team_member_connector_id")
    op.drop_column("prospect_connectors", "tenant_id")

    op.drop_index("idx_connectors_shared_connections", table_name="connectors")
    op.drop_index("idx_connectors_current_company", table_name="connectors")
    op.drop_index("idx_connectors_tenant", table_name="connectors")

    op.drop_constraint("fk_connectors_archived_by", "connectors", type_="foreignkey")
    op.drop_constraint("fk_connectors_updated_by", "connectors", type_="foreignkey")
    op.drop_constraint("fk_connectors_created_by", "connectors", type_="foreignkey")

    op.drop_column("connectors", "last_verified_at")
    op.drop_column("connectors", "archived_reason")
    op.drop_column("connectors", "archived_by_id")
    op.drop_column("connectors", "archived_at")
    op.drop_column("connectors", "updated_by_id")
    op.drop_column("connectors", "created_by_id")
    op.drop_column("connectors", "shared_connections_count")
    op.drop_column("connectors", "current_title")
    op.drop_column("connectors", "current_company")
    op.drop_column("connectors", "last_name")
    op.drop_column("connectors", "first_name")
    op.drop_column("connectors", "tenant_id")

    op.drop_index("idx_tmc_active", table_name="team_member_connectors")
    op.drop_index("idx_tmc_connector", table_name="team_member_connectors")
    op.drop_index("idx_tmc_org_team_member", table_name="team_member_connectors")
    op.drop_table("team_member_connectors")

