from __future__ import annotations

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from backend.app.config import get_settings
from backend.app.database import Base


def test_initial_migration_up_and_down_on_sqlite(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "migration.sqlite3"
    database_url = f"sqlite:///{database_path}"
    monkeypatch.setenv("QDII_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config()
    config.set_main_option("script_location", "migrations")
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == {
        "alembic_version",
        *Base.metadata.tables.keys(),
    }
    purchase_limit_columns = {
        column["name"]: column for column in inspector.get_columns("daily_purchase_limit")
    }
    assert purchase_limit_columns["source_artifact_id"]["nullable"] is False
    assert purchase_limit_columns["daily_limit_amount"]["nullable"] is True
    assert {
        "availability_state",
        "cap_state",
        "limit_basis",
        "share_scope",
        "raw_text",
        "confidence",
    } <= purchase_limit_columns.keys()
    unique_constraints = inspector.get_unique_constraints("daily_purchase_limit")
    assert any(
        constraint["name"] == "uq_daily_purchase_limit_identity"
        and set(constraint["column_names"])
        == {
            "fund_share_id",
            "snapshot_date",
            "channel_type",
            "channel_key",
            "business_type",
            "limit_basis",
            "share_scope",
            "source_provider",
        }
        for constraint in unique_constraints
    )
    artifact_foreign_key = next(
        foreign_key
        for foreign_key in inspector.get_foreign_keys("daily_purchase_limit")
        if foreign_key["constrained_columns"] == ["source_artifact_id"]
    )
    assert artifact_foreign_key["options"].get("ondelete") == "RESTRICT"
    assert {
        "reported_market_value",
        "reported_units",
        "reported_profit_amount",
        "reported_return_pct",
        "reported_cumulative_profit_amount",
        "anchor_nav_date",
        "anchor_unit_nav",
        "recurring_gross_amount",
        "manual_purchase_fee_pct",
    } <= {column["name"] for column in inspector.get_columns("portfolio_position")}
    assert {
        "management_fee_pct_annual",
        "custody_fee_pct_annual",
        "standard_purchase_fee_pct",
        "discounted_purchase_fee_pct",
        "source_artifact_id",
    } <= {column["name"] for column in inspector.get_columns("daily_fund_fee")}
    assert {"occurred_on", "occurred_year", "amount"} <= {
        column["name"] for column in inspector.get_columns("portfolio_cash_flow")
    }
    assert {"base_currency", "quote_currency", "rate_date", "rate"} <= {
        column["name"] for column in inspector.get_columns("daily_exchange_rate")
    }
    assert {
        "operation",
        "status",
        "active_slot",
        "fund_codes",
        "current_stage",
        "run_ids",
        "recurring_orders_created",
        "recurring_orders_settled",
        "recurring_executions_written",
        "recurring_positions_updated",
        "recurring_latest_nav_date",
    } <= {column["name"] for column in inspector.get_columns("data_operation")}
    assert {
        "portfolio_position_id",
        "nav_date",
        "unit_nav",
        "gross_amount",
        "net_amount",
        "units",
    } <= {column["name"] for column in inspector.get_columns("portfolio_recurring_execution")}
    assert {
        "portfolio_position_id",
        "order_date",
        "expected_confirmation_date",
        "status",
        "gross_amount",
        "net_amount",
        "settled_execution_id",
        "confirmed_at",
    } <= {column["name"] for column in inspector.get_columns("portfolio_recurring_order")}
    assert "recurring_confirmation_lag_days" in {
        column["name"] for column in inspector.get_columns("portfolio_position")
    }

    command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()
    get_settings.cache_clear()


def test_revision_ids_fit_alembic_version_column() -> None:
    config = Config()
    config.set_main_option("script_location", "migrations")
    revisions = ScriptDirectory.from_config(config).walk_revisions()

    assert all(len(revision.revision) <= 32 for revision in revisions)
