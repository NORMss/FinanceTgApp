"""Разбор взаиморасчётов: из чего сложился долг и нет ли в нём мусора.

    python -m app.repair            # только показать, ничего не меняя
    python -m app.repair --apply    # пересчитать доли у проблемных операций

Зачем это нужно. «Кто кому должен» считается не на лету, а по строкам `tx_splits`,
которые записываются в момент создания или правки операции. Пока в правке был баг
(доли не пересчитывались при смене счёта), в базе оставались доли от операций, которые
уже перенесли с общего счёта на личный. Исправление кода такие строки не трогает:
оно срабатывает только когда операцию правят заново. Эта команда находит их и чинит.

Отдельно она отвечает на вопрос «почему долг вообще есть»: печатает каждую операцию,
которая участвует в расчёте. Часто оказывается, что долг настоящий — просто остаток
на общем счёте нулевой, а это совсем другая величина.
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import dispose_engine, get_session_factory
from app.models import Account, Transaction, TransactionType
from app.repositories import users as users_repo
from app.repositories.transactions import TxFilter
from app.services import ledger
from app.services import stats as stats_service
from app.util.money import format_amount

# Почему доли на этой операции выглядят мусором
NOT_SHARED = "счёт не общий"
NOT_EXPENSE = "не расход"
UNBALANCED = "сумма долей не равна сумме операции"


@dataclass(slots=True)
class Row:
    tx: Transaction
    account: Account | None
    shares: dict[str, int]
    problem: str | None


def _label(account: Account | None) -> str:
    # Значки те же, что в приложении: общий счёт от личного отличается на глаз
    if account is None:
        return "счёт удалён"
    return f"{'👥' if account.is_shared else '👤'} {account.name}"


def _diagnose(tx: Transaction, account: Account | None, shares: dict[str, int]) -> str | None:
    """Могли ли эти доли появиться по нынешним правилам приложения.

    Правило одно: доли создаются у расхода с общего счёта. Всё остальное — либо след
    старого бага, либо ручное деление через API. Поэтому команда ничего не чинит сама,
    а сначала показывает список.
    """
    if not shares:
        return None
    if tx.type != TransactionType.EXPENSE:
        return NOT_EXPENSE
    if account is None or not account.is_shared:
        return NOT_SHARED
    if sum(shares.values()) != tx.amount_minor:
        return UNBALANCED
    return None


async def scan(session: AsyncSession) -> list[Row]:
    """Все живые операции, у которых есть доли, — то есть весь материал взаиморасчётов."""
    result = await session.execute(
        select(Transaction)
        .where(Transaction.deleted_at.is_(None), Transaction.splits.any())
        .order_by(Transaction.occurred_at)
    )
    transactions = list(result.scalars())

    accounts = {
        account.id: account
        for account in (await session.execute(select(Account))).scalars()
    }

    rows = []
    for tx in transactions:
        account = accounts.get(tx.account_id)
        shares = {split.user_id: split.share_minor for split in tx.splits}
        rows.append(Row(tx, account, shares, _diagnose(tx, account, shares)))
    return rows


async def repair(session: AsyncSession, rows: list[Row]) -> int:
    """Пересчитывает доли по текущим правилам. Возвращает число исправленных операций.

    Считает не сама, а через ledger.update_transaction — правила деления должны жить
    в одном месте, иначе починка однажды разойдётся с приложением. Заодно операция
    попадает в outbox и уезжает в Google Sheets.
    """
    fixed = 0
    for row in rows:
        if row.problem is None:
            continue
        await ledger.update_transaction(session, row.tx, splits=None)
        fixed += 1
    await session.commit()
    return fixed


async def report(session: AsyncSession, rows: list[Row]) -> None:
    users = {user.id: user.display_name for user in await users_repo.list_all(session)}
    balances = await stats_service.settle_up(session, TxFilter())

    print("Взаиморасчёты сейчас")
    for item in balances:
        state = "в расчёте"
        if item.net_minor > 0:
            state = f"должны ему {format_amount(item.net_minor)}"
        elif item.net_minor < 0:
            state = f"должен {format_amount(-item.net_minor)}"
        print(
            f"  {item.name:<12} заплатил {format_amount(item.paid_minor):>12}"
            f" · доля {format_amount(item.owed_minor):>12} · {state}"
        )

    if not rows:
        print("\nОпераций с долями нет — делить нечего, и долг взяться неоткуда.")
        return

    print(f"\nОперации, из которых складывается долг ({len(rows)})")
    for row in rows:
        shares = " · ".join(
            f"{users.get(user_id, user_id[:6])} {format_amount(share)}"
            for user_id, share in row.shares.items()
        )
        mark = "  " if row.problem is None else "! "
        note = f" — {row.tx.note}" if row.tx.note else ""
        print(
            f"{mark}{row.tx.occurred_at:%d.%m.%Y} {format_amount(row.tx.amount_minor):>12}"
            f"  [{_label(row.account)}]{note}"
        )
        print(f"    доли: {shares}")
        if row.problem:
            print(f"    ПРОБЛЕМА: {row.problem} — доли остались от прежней версии приложения")

    broken = [row for row in rows if row.problem]
    if not broken:
        print(
            "\nЛишних долей нет: долг настоящий и держится на живых тратах с общего счёта."
            "\nОстаток на общем счёте тут ни при чём — это другая величина: он показывает,"
            "\nсколько денег на счёте, а не кто чью долю ещё не вернул."
            "\nЧтобы закрыть долг, сделайте перевод с личного счёта должника на личный"
            "\nсчёт того, кому должны, — «Ещё → Взаиморасчёты» показывает нужную сумму."
        )
        return

    print(f"\nПроблемных операций: {len(broken)}")
    print("Это следы бага, который чинили в версии от 17.08.2026: правка счёта не")
    print("пересчитывала доли. Новые операции считаются правильно, а эти нужно пересчитать:")
    print("    python -m app.repair --apply")


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Разбор и починка взаиморасчётов")
    parser.add_argument(
        "--apply", action="store_true", help="пересчитать доли у проблемных операций"
    )
    args = parser.parse_args(argv)

    try:
        async with get_session_factory()() as session:
            rows = await scan(session)
            if args.apply:
                fixed = await repair(session, rows)
                print(f"Пересчитано операций: {fixed}\n")
                rows = await scan(session)
            await report(session, rows)
    finally:
        await dispose_engine()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
