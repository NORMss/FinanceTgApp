"""category tree: wider icon, indexed parent

Revision ID: 8c1d4b2f7a30
Revises: 524fea4317a9
Create Date: 2026-08-15 12:00:00.000000

ВАЖНО про SQLite: таблицу categories нельзя пересобирать через batch_alter_table.
У неё есть ссылка на саму себя (parent_id -> categories.id) с ON DELETE SET NULL,
а приложение держит PRAGMA foreign_keys=ON. Batch-режим копирует данные во временную
таблицу и удаляет исходную — и это удаление срабатывает как каскад: все parent_id
обнуляются, дерево категорий превращается в плоский список. Проверено: девять
подкатегорий из девяти теряли родителя.

Поэтому здесь только то, что SQLite умеет делать на месте: создание индекса.
Ширина VARCHAR в SQLite всё равно не проверяется — составное эмодзи помещалось
в колонку и до этой миграции. Расширение типа нужно только «настоящим» базам,
поэтому оно выполняется отдельной веткой для не-SQLite диалектов.
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

INDEX_NAME = 'ix_categories_parent_id'


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == 'sqlite'


def upgrade() -> None:
    # По parent_id теперь ходит каждый список подкатегорий
    op.create_index(INDEX_NAME, 'categories', ['parent_id'], unique=False)

    if not _is_sqlite():
        # Составные эмодзи (👨‍👩‍👧‍👦) — это до 11 кодовых точек, восьми не хватает
        op.alter_column(
            'categories',
            'icon',
            existing_type=sa.String(length=8),
            type_=sa.String(length=16),
            existing_nullable=False,
        )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name='categories')

    if not _is_sqlite():
        op.alter_column(
            'categories',
            'icon',
            existing_type=sa.String(length=16),
            type_=sa.String(length=8),
            existing_nullable=False,
        )
