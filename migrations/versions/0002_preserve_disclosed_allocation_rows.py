"""Preserve repeated allocation rows disclosed in separate report tables.

Revision ID: 0002_preserve_allocation_rows
Revises: 0001_initial_schema
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_preserve_allocation_rows"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINTS = (
    ("report_asset_allocation", "uq_report_asset_allocation_row", "asset_name_normalized"),
    (
        "report_country_allocation",
        "uq_report_country_allocation_row",
        "country_name_normalized",
    ),
    (
        "report_industry_allocation",
        "uq_report_industry_allocation_row",
        "industry_name_normalized",
    ),
)


def upgrade() -> None:
    for table, constraint, _ in CONSTRAINTS:
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(constraint, type_="unique")


def downgrade() -> None:
    for table, constraint, normalized_column in CONSTRAINTS:
        with op.batch_alter_table(table) as batch_op:
            batch_op.create_unique_constraint(
                constraint,
                ["fund_report_id", normalized_column, "exposure_basis"],
            )
