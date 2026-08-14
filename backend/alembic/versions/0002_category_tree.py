"""category tree: wider icon, indexed parent

Revision ID: 8c1d4b2f7a30
Revises: 524fea4317a9
Create Date: 2026-08-15 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Нужен для колонок с собственным типом TZDateTime, который рендерит autogenerate
import app.models.base  # noqa: F401

revision: str = '8c1d4b2f7a30'
down_revision: str | None = '524fea4317a9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Составные эмодзи (👨‍👩‍👧) длиннее восьми символов, а по parent_id теперь ходит
    # каждый запрос списка подкатегорий
    with op.batch_alter_table('categories', schema=None) as batch_op:
        batch_op.alter_column(
            'icon',
            existing_type=sa.String(length=8),
            type_=sa.String(length=16),
            existing_nullable=False,
        )
        batch_op.create_index(batch_op.f('ix_categories_parent_id'), ['parent_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('categories', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_categories_parent_id'))
        batch_op.alter_column(
            'icon',
            existing_type=sa.String(length=16),
            type_=sa.String(length=8),
            existing_nullable=False,
        )
