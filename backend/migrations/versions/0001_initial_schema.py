"""Initial Phase 3 schema: watchlists, portfolios, quotes, alerts.

Revision ID: 0001
Revises:
Create Date: 2026-11-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "watchlist_id",
            sa.Integer(),
            sa.ForeignKey("watchlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(12), nullable=False),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("watchlist_id", "ticker", name="uq_watchlist_ticker"),
    )
    op.create_table(
        "portfolios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("starting_cash", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "paper_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "portfolio_id",
            sa.Integer(),
            sa.ForeignKey("portfolios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(12), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("fee", sa.Float(), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=False),
        sa.Column("price_source", sa.String(40), nullable=False),
        sa.Column("note", sa.String(200), nullable=True),
    )
    op.create_table(
        "quote_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(12), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("open", sa.Float(), nullable=True),
        sa.Column("high", sa.Float(), nullable=True),
        sa.Column("low", sa.Float(), nullable=True),
        sa.Column("prev_close", sa.Float(), nullable=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("exchange_timestamp", sa.DateTime(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_quote_snapshots_ticker", "quote_snapshots", ["ticker"])
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(12), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=False),
        sa.Column("data_source", sa.String(8), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("condition_met", sa.Boolean(), nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_alert_rules_ticker", "alert_rules", ["ticker"])
    op.create_table(
        "alert_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "rule_id",
            sa.Integer(),
            sa.ForeignKey("alert_rules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("triggered_at", sa.DateTime(), nullable=False),
        sa.Column("observed_value", sa.Float(), nullable=True),
        sa.Column("observed_signal", sa.String(12), nullable=True),
        sa.Column("observation_source", sa.String(40), nullable=False),
        sa.Column("observation_as_of", sa.String(40), nullable=True),
        sa.Column("message", sa.String(300), nullable=False),
        sa.Column("acknowledged", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_alert_events_rule_id", "alert_events", ["rule_id"])


def downgrade() -> None:
    op.drop_table("alert_events")
    op.drop_table("alert_rules")
    op.drop_table("quote_snapshots")
    op.drop_table("paper_transactions")
    op.drop_table("portfolios")
    op.drop_table("watchlist_items")
    op.drop_table("watchlists")
