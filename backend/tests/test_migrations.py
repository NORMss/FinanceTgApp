"""Миграции не должны терять данные.

Проверка появилась не из теории: миграция 0002 в первой редакции пересобирала таблицу
categories через batch_alter_table, и на боевой базе это молча обнуляло parent_id
у всех подкатегорий. Причина — самоссылка parent_id -> categories.id с ON DELETE SET NULL
и включённый PRAGMA foreign_keys: удаление исходной таблицы внутри batch-режима
срабатывает как каскад.

Тест гоняет настоящий alembic на временном файле, поэтому ловит и такие ошибки,
которых не видно ни в модели, ни в самом тексте миграции.
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
INITIAL = "524fea4317a9"


def _alembic(args: list[str], db_path: Path) -> None:
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        "BOT_MODE": "off",
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture
def seeded_db(tmp_path: Path) -> Path:
    """База на первой миграции с деревом категорий и операцией — как у живого пользователя."""
    db_path = tmp_path / "upgrade.db"
    _alembic(["upgrade", INITIAL], db_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executemany(
            "INSERT INTO categories (id, name, kind, parent_id, icon, archived, sort,"
            " created_at, updated_at) VALUES (?, ?, 'EXPENSE', ?, ?, 0, 100,"
            " '2026-08-01 00:00:00', '2026-08-01 00:00:00')",
            [
                ("01ROOT", "Супермаркет", None, "🛒"),
                ("01CHILD1", "Пятёрочка", "01ROOT", "🟢"),
                ("01CHILD2", "КБ", "01ROOT", "🍺"),
            ],
        )
        connection.commit()
    return db_path


def test_existing_users_get_reminder_defaults(seeded_db: Path):
    """Колонки напоминаний NOT NULL, а строки в users уже есть.

    Без server_default такая миграция падает прямо на боевой базе, где пользователи
    завелись с первого дня, — и заметить это на пустой базе невозможно.
    """
    with sqlite3.connect(seeded_db) as connection:
        connection.execute(
            "INSERT INTO users (id, telegram_id, display_name, is_active,"
            " created_at, updated_at) VALUES ('01USER', 111, 'Аня', 1,"
            " '2026-08-01 00:00:00', '2026-08-01 00:00:00')"
        )
        connection.commit()

    _alembic(["upgrade", "head"], seeded_db)

    with sqlite3.connect(seeded_db) as connection:
        row = connection.execute(
            "SELECT reminder_enabled, reminder_time, reminder_tz, reminder_last_sent_on"
            " FROM users WHERE id = '01USER'"
        ).fetchone()

    assert row == (1, "21:00", "", None)


def test_upgrade_keeps_subcategories(seeded_db: Path):
    _alembic(["upgrade", "head"], seeded_db)

    with sqlite3.connect(seeded_db) as connection:
        rows = connection.execute(
            "SELECT c.name, p.name FROM categories c"
            " JOIN categories p ON p.id = c.parent_id ORDER BY c.name"
        ).fetchall()
        broken = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert rows == [("КБ", "Супермаркет"), ("Пятёрочка", "Супермаркет")]
    assert broken == []


def test_upgrade_adds_parent_index(seeded_db: Path):
    _alembic(["upgrade", "head"], seeded_db)

    with sqlite3.connect(seeded_db) as connection:
        indexes = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='categories'"
        ).fetchall()

    assert ("ix_categories_parent_id",) in indexes


def test_downgrade_and_upgrade_roundtrip(seeded_db: Path):
    _alembic(["upgrade", "head"], seeded_db)
    _alembic(["downgrade", INITIAL], seeded_db)
    _alembic(["upgrade", "head"], seeded_db)

    with sqlite3.connect(seeded_db) as connection:
        children = connection.execute(
            "SELECT COUNT(*) FROM categories WHERE parent_id IS NOT NULL"
        ).fetchone()[0]

    assert children == 2
