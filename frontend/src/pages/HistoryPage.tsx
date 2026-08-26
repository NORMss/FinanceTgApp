import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { api } from '../api'
import { fullName, iconOf, indexById } from '../categories'
import CategoryPicker from '../components/CategoryPicker'
import EditSheet from '../components/EditSheet'
import ErrorNote from '../components/ErrorNote'
import PeriodPicker from '../components/PeriodPicker'
import { formatDay, formatMoney, formatTime } from '../format'
import { DEFAULT_RANGE, type Range, rangeKey } from '../period'
import { haptic } from '../telegram'
import type { Filters, Transaction, TransactionType } from '../types'

interface Props {
  currentUserId: string
  /** Условия, с которыми сюда пришли из отчёта. */
  initial?: { range: Range; filters: Filters }
  onDone: (message: string) => void
}

const TYPE_LABELS: Record<TransactionType, string> = {
  expense: 'Расходы',
  income: 'Доходы',
  transfer: 'Переводы',
}

export default function HistoryPage({ currentUserId, initial, onDone }: Props) {
  const [range, setRange] = useState<Range>(initial?.range ?? DEFAULT_RANGE)
  const [filters, setFilters] = useState<Filters>(initial?.filters ?? {})
  const [editing, setEditing] = useState<Transaction | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)

  const page = useQuery({
    queryKey: ['transactions', rangeKey(range), filters],
    queryFn: () => api.transactions(range, filters, 200),
  })
  const categories = useQuery({ queryKey: ['categories', 'all'], queryFn: () => api.categories() })
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: api.accounts })
  const users = useQuery({ queryKey: ['users'], queryFn: api.users })

  const catalog = useMemo(() => indexById(categories.data ?? []), [categories.data])
  const people = useMemo(() => new Map((users.data ?? []).map((u) => [u.id, u])), [users.data])
  // Чья трата — это владелец счёта, с которого она записана: запись за другого делается
  // выбором его личного счёта, автором при этом остаётся тот, кто её вносил
  const owners = useMemo(
    () => new Map((accounts.data ?? []).map((a) => [a.id, a.owner_id])),
    [accounts.data],
  )
  const picked = filters.categoryId ? catalog.get(filters.categoryId) : undefined

  const patch = (next: Partial<Filters>) => {
    haptic()
    setFilters((current) => ({ ...current, ...next }))
  }

  // Группируем по дню: сплошной список из полусотни строк читать невозможно
  const groups = useMemo(() => {
    const result: { day: string; items: Transaction[]; total: number }[] = []
    for (const tx of page.data?.items ?? []) {
      const day = formatDay(tx.occurred_at)
      const delta = tx.type === 'expense' ? tx.amount_minor : 0
      const last = result[result.length - 1]
      if (last?.day === day) {
        last.items.push(tx)
        last.total += delta
      } else {
        result.push({ day, items: [tx], total: delta })
      }
    }
    return result
  }, [page.data])

  const shown = page.data?.items.length ?? 0
  const filtered = Boolean(
    filters.personId || filters.type || filters.search || filters.categoryId,
  )

  return (
    <div className="page">
      <PeriodPicker value={range} onChange={setRange} />

      {/* Фильтр по людям: в семейном учёте первый вопрос к истории — «чья это трата».
          Именно чья, а не кем записана: трату за другого вносят с его личного счёта,
          и найтись она должна у него */}
      {(users.data?.length ?? 0) > 1 && (
        <div className="chips">
          <button
            type="button"
            className="chip"
            data-active={!filters.personId}
            onClick={() => patch({ personId: null })}
          >
            Все
          </button>
          {(users.data ?? []).map((user) => (
            <button
              key={user.id}
              type="button"
              className="chip"
              data-active={filters.personId === user.id}
              onClick={() =>
                patch({ personId: filters.personId === user.id ? null : user.id })
              }
            >
              {user.id === currentUserId ? 'Я' : user.display_name}
            </button>
          ))}
        </div>
      )}

      {/* Категория и вид операции. Категория первой: сюда приходят из отчёта,
          и первое, что человек должен увидеть, — по чему именно фильтр.
          Расходы и доходы стояли в ряду людей и вместе с ним пропадали у того,
          кто ведёт учёт один, — а разделить приход и трату нужно и одному */}
      <div className="chips">
        <button
          type="button"
          className="chip chip--ghost"
          data-active={Boolean(picked)}
          onClick={() => {
            haptic()
            setPickerOpen((current) => !current)
          }}
        >
          {picked ? `${iconOf(picked, catalog)} ${fullName(picked, catalog)}` : '🗂 Категория'}
        </button>
        {picked && (
          <button
            type="button"
            className="chip chip--ghost"
            onClick={() => {
              patch({ categoryId: null })
              setPickerOpen(false)
            }}
          >
            Сбросить
          </button>
        )}
        {(['expense', 'income'] as const).map((value) => (
          <button
            key={value}
            type="button"
            className="chip chip--ghost"
            data-active={filters.type === value}
            onClick={() => patch({ type: filters.type === value ? null : value })}
          >
            {TYPE_LABELS[value]}
          </button>
        ))}
      </div>

      {pickerOpen && (
        <div className="card">
          <CategoryPicker
            categories={categories.data ?? []}
            value={filters.categoryId ?? null}
            onChange={(id) => {
              patch({ categoryId: id })
              if (id) setPickerOpen(false)
            }}
          />
        </div>
      )}

      <input
        className="field"
        placeholder="Поиск по комментарию"
        value={filters.search ?? ''}
        onChange={(event) => setFilters((c) => ({ ...c, search: event.target.value }))}
      />

      <ErrorNote error={page.error} />

      {page.isPending && <p className="hint">Загружаем…</p>}
      {shown === 0 && !page.isPending && (
        <div className="card">
          <p className="hint" style={{ textAlign: 'center', margin: 0 }}>
            {filtered ? 'Ничего не нашлось по этим условиям' : 'За этот период операций нет'}
          </p>
        </div>
      )}

      {groups.map((group) => (
        <div key={group.day}>
          <p className="section-title section-title--row">
            <span>{group.day}</span>
            {group.total > 0 && <span>{formatMoney(group.total)}</span>}
          </p>
          <div className="card card--tight">
            {group.items.map((tx) => {
              const category = tx.category_id ? catalog.get(tx.category_id) : undefined
              const person = people.get(owners.get(tx.account_id) ?? tx.author_id)
              return (
                <div
                  className="row row--tappable"
                  key={tx.id}
                  onClick={() => {
                    haptic()
                    setEditing(tx)
                  }}
                  role="button"
                  tabIndex={0}
                >
                  <div className="row__icon">
                    {tx.type === 'transfer' ? '↔' : category ? iconOf(category, catalog) : '•'}
                  </div>
                  <div className="row__body">
                    <div className="row__title">
                      {category
                        ? fullName(category, catalog)
                        : tx.type === 'transfer'
                          ? 'Перевод'
                          : 'Без категории'}
                    </div>
                    <div className="row__sub">
                      {formatTime(tx.occurred_at)}
                      {person && person.id !== currentUserId ? ` · ${person.display_name}` : ''}
                      {tx.note ? ` · ${tx.note}` : ''}
                      {tx.tags ? ` · #${tx.tags.split(',').join(' #')}` : ''}
                    </div>
                  </div>
                  <div className={`row__amount amount--${tx.type}`}>
                    {tx.type === 'income' ? '+' : tx.type === 'expense' ? '−' : ''}
                    {formatMoney(tx.amount_minor)}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ))}

      {page.data && page.data.total > shown && (
        <p className="hint">
          Показаны первые {shown} из {page.data.total}
        </p>
      )}

      {editing && (
        <EditSheet
          tx={editing}
          categories={categories.data ?? []}
          accounts={accounts.data ?? []}
          onClose={() => setEditing(null)}
          onDone={onDone}
        />
      )}
    </div>
  )
}
