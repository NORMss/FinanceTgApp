import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { api } from '../api'
import { fullName, iconOf, indexById } from '../categories'
import EditSheet from '../components/EditSheet'
import ErrorNote from '../components/ErrorNote'
import PeriodPicker from '../components/PeriodPicker'
import { formatDay, formatMoney, formatTime } from '../format'
import { haptic } from '../telegram'
import type { Filters, Period, Transaction, TransactionType } from '../types'

interface Props {
  currentUserId: string
  onDone: (message: string) => void
}

const TYPE_LABELS: Record<TransactionType, string> = {
  expense: 'Расходы',
  income: 'Доходы',
  transfer: 'Переводы',
}

export default function HistoryPage({ currentUserId, onDone }: Props) {
  const [period, setPeriod] = useState<Period>('month')
  const [filters, setFilters] = useState<Filters>({})
  const [editing, setEditing] = useState<Transaction | null>(null)

  const page = useQuery({
    queryKey: ['transactions', period, filters],
    queryFn: () => api.transactions(period, filters, 200),
  })
  const categories = useQuery({ queryKey: ['categories', 'all'], queryFn: () => api.categories() })
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: api.accounts })
  const users = useQuery({ queryKey: ['users'], queryFn: api.users })

  const catalog = useMemo(() => indexById(categories.data ?? []), [categories.data])
  const authors = useMemo(() => new Map((users.data ?? []).map((u) => [u.id, u])), [users.data])

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
  const filtered = Boolean(filters.authorId || filters.type || filters.search)

  return (
    <div className="page">
      <PeriodPicker value={period} onChange={setPeriod} />

      {/* Фильтр по людям: в семейном учёте первый вопрос к истории — «кто это потратил» */}
      {(users.data?.length ?? 0) > 1 && (
        <div className="chips">
          <button
            type="button"
            className="chip"
            data-active={!filters.authorId}
            onClick={() => patch({ authorId: null })}
          >
            Все
          </button>
          {(users.data ?? []).map((user) => (
            <button
              key={user.id}
              type="button"
              className="chip"
              data-active={filters.authorId === user.id}
              onClick={() =>
                patch({ authorId: filters.authorId === user.id ? null : user.id })
              }
            >
              {user.id === currentUserId ? 'Я' : user.display_name}
            </button>
          ))}
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
              const author = authors.get(tx.author_id)
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
                      {author && author.id !== currentUserId ? ` · ${author.display_name}` : ''}
                      {tx.note ? ` · ${tx.note}` : ''}
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
