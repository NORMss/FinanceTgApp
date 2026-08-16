"""daily reminders: per-user time and timezone

Revision ID: b7e2c9f14d08
Revises: 8c1d4b2f7a30
Create Date: 2026-08-17 10:00:00.000000

Четыре колонки в users. Это ALTER TABLE ADD COLUMN, который SQLite выполняет на месте,
без пересборки таблицы, — тот самый случай, которого не хватило миграции 0002
(подробности про batch-режим и потерю данных см. в её докстринге).

server_default обязателен: колонки NOT NULL, а строки в таблице уже есть, и без
значения по умолчанию база откажется их дописывать. Существующие пользователи получают
напоминание включённым на 21:00 — фича бесполезна, если её надо сначала где-то найти
и включить, а выключается она одним касанием в приложении.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Нужен для колонок с собственным типом TZDateTime, который рендерит autogenerate
import app.models.base  # noqa: F401

revision: str = 'b7e2c9f14d08'
down_revision: str | None = '8c1d4b2f7a30'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ('reminder_enabled', 'reminder_time', 'reminder_tz', 'reminder_last_sent_on')


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('reminder_enabled', sa.Boolean(), nullable=False, server_default=sa.text('1')),
    )
    op.add_column(
        'users',
        sa.Column('reminder_time', sa.String(length=5), nullable=False, server_default='21:00'),
    )
    op.add_column(
        'users',
        sa.Column('reminder_tz', sa.String(length=64), nullable=False, server_default=''),
    )
    # Отметка «за какую местную дату уже напомнили». NULL — ещё ни разу
    op.add_column('users', sa.Column('reminder_last_sent_on', sa.Date(), nullable=True))


def downgrade() -> None:
    for column in reversed(COLUMNS):
        op.drop_column('users', column)
