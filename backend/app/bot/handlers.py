import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import entry_actions, main_menu, open_app_button
from app.config import settings
from app.models import CategoryKind, TransactionType, TxSource, User
from app.repositories import accounts as accounts_repo
from app.repositories import categories as categories_repo
from app.repositories import transactions as tx_repo
from app.repositories.transactions import TxFilter
from app.services import catalog as catalog_service
from app.services import ledger, llm_export, quick_entry
from app.services import stats as stats_service
from app.util.dates import resolve_period
from app.util.money import format_amount

log = logging.getLogger(__name__)
router = Router(name="main")

HELP = (
    "Я веду общий бюджет.\n\n"
    "<b>Быстрый ввод</b> — просто напиши сумму и описание:\n"
    "<code>500 продукты</code>\n"
    "<code>1 200,50 такси домой</code>\n"
    "<code>+50000 зарплата</code> — со знаком «+» это доход\n\n"
    "<b>Команды</b>\n"
    "/month — итоги за текущий месяц\n"
    "/balance — остатки по счетам\n"
    "/settle — кто кому должен\n"
    "/llm — выгрузка для анализа нейросетью\n"
    "/sync — выгрузить всё в Google Sheets\n\n"
    "<b>Напоминания</b>\n"
    "Вечером напомню, если за день ничего не записано. "
    "Время и выключатель — в приложении, вкладка «Ещё»."
)


@router.message(CommandStart())
async def cmd_start(message: Message, user: User) -> None:
    await message.answer(
        f"Привет, {user.display_name}! Веду общий бюджет.\n\n"
        "Кидай траты одной строкой: <code>500 продукты</code>.\n"
        "Или открой приложение — там графики, фильтры и история.",
        reply_markup=main_menu(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP, reply_markup=open_app_button())


@router.message(Command("month"))
@router.message(F.text == "📊 За месяц")
async def cmd_month(message: Message, session: AsyncSession) -> None:
    start, end = resolve_period("month")
    data = await stats_service.period_summary(session, TxFilter(start=start, end=end))

    lines = [
        f"<b>{start:%B %Y}</b>",
        f"Расходы: <b>{format_amount(data['expense_minor'])}</b>",
        f"Доходы: <b>{format_amount(data['income_minor'])}</b>",
        f"Сальдо: <b>{format_amount(data['net_minor'], sign=True)}</b>",
    ]
    if data["by_category"]:
        lines.append("\n<b>Топ категорий</b>")
        for item in data["by_category"][:7]:
            share = round(item.share * 100)
            label = f"{item.icon} {item.name}".strip()
            lines.append(f"{label} — {format_amount(item.amount_minor)} ({share}%)")
    if len(data["by_author"]) > 1:
        lines.append("\n<b>Кто сколько потратил</b>")
        lines += [
            f"{row['name']} — {format_amount(row['amount_minor'])}" for row in data["by_author"]
        ]

    await message.answer("\n".join(lines), reply_markup=open_app_button())


@router.message(Command("balance"))
@router.message(F.text == "🏦 Баланс")
async def cmd_balance(message: Message, session: AsyncSession) -> None:
    balances, total = await stats_service.account_balances(session)
    if not balances:
        await message.answer("Счетов пока нет.")
        return
    lines = ["<b>Остатки</b>"]
    lines += [
        f"{'👥' if item.is_shared else '👤'} {item.name} — "
        f"<b>{format_amount(item.balance_minor)}</b> {item.currency}"
        for item in balances
    ]
    lines.append(f"\nВсего: <b>{format_amount(total)}</b>")
    await message.answer("\n".join(lines))


@router.message(Command("settle"))
async def cmd_settle(message: Message, session: AsyncSession) -> None:
    users = await stats_service.settle_up(session)
    lines = ["<b>Взаиморасчёты</b>"]
    for item in users:
        mark = "получает" if item.net_minor > 0 else "должен"
        if item.net_minor == 0:
            lines.append(f"{item.name} — в расчёте")
        else:
            lines.append(f"{item.name} {mark} <b>{format_amount(abs(item.net_minor))}</b>")
    await message.answer("\n".join(lines))


@router.message(Command("llm"))
async def cmd_llm(message: Message, session: AsyncSession) -> None:
    start, end = resolve_period("year")
    dump = await llm_export.build_dump(session, TxFilter(start=start, end=end))
    text = llm_export.render_markdown(dump)
    document = BufferedInputFile(text.encode("utf-8"), filename="finance-dump.md")
    await message.answer_document(
        document, caption="Выгрузка агрегатов. Скорми её нейросети целиком."
    )


@router.message(Command("sync"))
async def cmd_sync(message: Message) -> None:
    if not settings.sheets_ready:
        await message.answer("Синхронизация с Google Sheets не настроена.")
        return
    from app.sync.scheduler import resync_now

    try:
        result = await resync_now()
    except Exception as exc:  # noqa: BLE001 — пользователю нужен текст ошибки, а не трейс
        await message.answer(f"Не получилось: {exc}")
        return
    await message.answer(
        f"Готово. Обновлено строк: {result['updated']}, добавлено: {result['appended']}."
    )


@router.message(F.text & ~F.text.startswith("/"))
async def quick_add(message: Message, session: AsyncSession, user: User) -> None:
    """Свободный текст трактуем как быстрый ввод операции."""
    try:
        parsed = await quick_entry.parse(session, message.text or "")
    except quick_entry.ParseError as exc:
        await message.answer(f"{exc}. Формат: <code>500 продукты</code>")
        return

    account = await accounts_repo.get_shared(session)
    if account is None:
        accounts = await accounts_repo.list_all(session)
        account = accounts[0] if accounts else None
    if account is None:
        await message.answer("Нет ни одного счёта — заведи его в приложении.")
        return

    tx = await ledger.create_transaction(
        session,
        author=user,
        tx_type=parsed.tx_type,
        amount_minor=parsed.amount_minor,
        account_id=account.id,
        category_id=parsed.category_id,
        note=parsed.note,
        source=TxSource.BOT,
    )
    if parsed.matched_rule_id:
        await categories_repo.bump_rule_hits(session, parsed.matched_rule_id)

    kind = (
        CategoryKind.INCOME if parsed.tx_type == TransactionType.INCOME else CategoryKind.EXPENSE
    )
    suggestions = await categories_repo.list_all(session, kind=kind)
    recent_ids = await tx_repo.recent_category_ids(session, user.id)
    by_id = {category.id: category for category in suggestions}
    ordered = [by_id[cid] for cid in recent_ids if cid in by_id]
    ordered += [category for category in suggestions if category not in ordered]
    options = [
        (category, f"{category.icon} {catalog_service.full_name(category, by_id)}".strip())
        for category in ordered
    ]

    title = "Доход" if parsed.tx_type == TransactionType.INCOME else "Расход"
    category_line = parsed.category_name or "без категории"
    if parsed.category_id and parsed.category_id in by_id:
        category_line = catalog_service.full_name(by_id[parsed.category_id], by_id)
    note_line = f"\n<i>{parsed.note}</i>" if parsed.note else ""
    await message.answer(
        f"{title} <b>{format_amount(parsed.amount_minor)}</b> · {category_line}{note_line}",
        reply_markup=entry_actions(tx.id, options),
    )


@router.callback_query(F.data.startswith("cat:"))
async def set_category(query: CallbackQuery, session: AsyncSession) -> None:
    _, tx_id, category_id = query.data.split(":", 2)
    tx = await tx_repo.get(session, tx_id)
    if tx is None or tx.deleted_at is not None:
        await query.answer("Операция не найдена", show_alert=True)
        return

    category = await categories_repo.get(session, category_id)
    await ledger.update_transaction(session, tx, category_id=category_id)

    label = "без категории"
    if category is not None:
        parents = {}
        if category.parent_id:
            parent = await categories_repo.get(session, category.parent_id)
            parents = {parent.id: parent} if parent else {}
        label = catalog_service.full_name(category, parents)

    await query.answer(f"Категория: {label}" if category else "Готово")
    if query.message:
        note_line = f"\n<i>{tx.note}</i>" if tx.note else ""
        await query.message.edit_text(
            f"Расход <b>{format_amount(tx.amount_minor)}</b> · {label}{note_line}",
            reply_markup=query.message.reply_markup,
        )


@router.callback_query(F.data.startswith("del:"))
async def delete_entry(query: CallbackQuery, session: AsyncSession) -> None:
    tx_id = query.data.split(":", 1)[1]
    tx = await tx_repo.get(session, tx_id)
    if tx is None or tx.deleted_at is not None:
        await query.answer("Уже удалено")
        return
    await ledger.delete_transaction(session, tx)
    await query.answer("Удалено")
    if query.message:
        await query.message.edit_text(
            f"<s>Удалено: {format_amount(tx.amount_minor)}</s>", reply_markup=None
        )
