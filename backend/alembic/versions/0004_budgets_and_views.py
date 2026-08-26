"""budgets and saved report views

Revision ID: c3a91f57e264
Revises: b7e2c9f14d08
Create Date: 2026-08-26 12:00:00.000000

Две новые таблицы и ни одного ALTER существующих — самая безопасная форма миграции
для SQLite: пересобирать ничего не нужно, откат сводится к DROP TABLE.

Обе таблицы пустые на старте и такими остаются, пока человек сам не заведёт лимит
или не сохранит вид отчёта. Умолчаний тут быть не должно: лимит, назначенный
приложением, — это чужая цифра, под которую нечего подгонять, а вид отчёта,
появившийся сам, человек будет искать глазами и не найдёт, откуда он взялся.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Нужен для колонок с собственным типом TZDateTime, который рендерит autogenerate
import app.models.base  # noqa: F401

revision: str = 'c3a91f57e264'
down_revision: str | None = 'b7e2c9f14d08'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'budgets',
        sa.Column('id', sa.String(length=26), nullable=False),
        sa.Column('category_id', sa.String(length=26), nullable=False),
        sa.Column('limit_minor', sa.Integer(), nullable=False),
        sa.Column('created_at', app.models.base.TZDateTime(), nullable=False),
        sa.Column('updated_at', app.models.base.TZDateTime(), nullable=False),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        # Один лимит на категорию: два лимита на одну и ту же строку отчёта
        # означали бы два разных ответа на вопрос «сколько осталось»
        sa.UniqueConstraint('category_id', name='uq_budgets_category'),
    )
    op.create_index(op.f('ix_budgets_category_id'), 'budgets', ['category_id'])

    op.create_table(
        'report_views',
        sa.Column('id', sa.String(length=26), nullable=False),
        sa.Column('owner_id', sa.String(length=26), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('sort', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('created_at', app.models.base.TZDateTime(), nullable=False),
        sa.Column('updated_at', app.models.base.TZDateTime(), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('owner_id', 'name', name='uq_report_views_owner_name'),
    )
    op.create_index(op.f('ix_report_views_owner_id'), 'report_views', ['owner_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_report_views_owner_id'), table_name='report_views')
    op.drop_table('report_views')
    op.drop_index(op.f('ix_budgets_category_id'), table_name='budgets')
    op.drop_table('budgets')
