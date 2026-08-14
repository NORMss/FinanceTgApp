import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { api } from '../api'
import ErrorNote from '../components/ErrorNote'
import PeriodPicker from '../components/PeriodPicker'
import { formatDay, formatMoney, formatTime } from '../format'
import { notify } from '../telegram'
import type { Category, Period, Transaction } from '../types'

interface Props {
  onDone: (message: string) => void
}

export default function HistoryPage({ onDone }: Props) {
  const queryClient = useQueryClient()
  const [period, setPeriod] = useState<Period>('month')
  const [openId, setOpenId] = useState<string | null>(null)

  const page = useQuery({
    queryKey: ['transactions', period],
    queryFn: () => api.transactions(period, 200),
  })
  const categories = useQuery({ queryKey: ['categories', 'all'], queryFn: () => api.categories() })

  const catalog = useMemo(() => {
    const map = new Map<string, Category>()
    for (const category of categories.data ?? []) map.set(category.id, category)
    return map
  }, [categories.data])

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteTransaction(id),
    onSuccess: () => {
      notify('success')
      onDone('Операция удалена')
      setOpenId(null)
      queryClient.invalidateQueries()
    },
  })

  // Группируем по дню: сплошной список из полусотни строк читать невозможно
  const groups = useMemo(() => {
    const result: { day: string; items: Transaction[] }[] = []
    for (const tx of page.data?.items ?? []) {
      const day = formatDay(tx.occurred_at)
      const last = result[result.length - 1]
      if (last?.day === day) last.items.push(tx)
      else result.push({ day, items: [tx] })
    }
    return result
  }, [page.data])

  return (
    <div className="page">
      <PeriodPicker value={period} onChange={setPeriod} />

      <ErrorNote error={page.error ?? remove.error} />

      {page.isPending && <p className="hint">Загружаем…</p>}
      {page.data?.items.length === 0 && (
        <div className="card">
          <p className="hint" style={{ textAlign: 'center', margin: 0 }}>
            За этот период операций нет
          </p>
        </div>
      )}

      {groups.map((group) => (
        <div key={group.day}>
          <p className="section-title">{group.day}</p>
          <div className="card card--tight">
            {group.items.map((tx) => {
              const category = tx.category_id ? catalog.get(tx.category_id) : undefined
              const isOpen = openId === tx.id
              return (
                <div key={tx.id}>
                  <div
                    className="row"
                    onClick={() => setOpenId(isOpen ? null : tx.id)}
                    role="button"
                    tabIndex={0}
                  >
                    <div className="row__icon">
                      {tx.type === 'transfer' ? '↔' : (category?.icon ?? '•')}
                    </div>
                    <div className="row__body">
                      <div className="row__title">
                        {category?.name ?? (tx.type === 'transfer' ? 'Перевод' : 'Без категории')}
                      </div>
                      <div className="row__sub">
                        {formatTime(tx.occurred_at)}
                        {tx.note ? ` · ${tx.note}` : ''}
                      </div>
                    </div>
                    <div className={`row__amount amount--${tx.type}`}>
                      {tx.type === 'income' ? '+' : tx.type === 'expense' ? '−' : ''}
                      {formatMoney(tx.amount_minor)}
                    </div>
                  </div>
                  {isOpen && (
                    <div style={{ textAlign: 'right', paddingBottom: 8 }}>
                      <button
                        className="btn btn--danger"
                        type="button"
                        disabled={remove.isPending}
                        onClick={() => remove.mutate(tx.id)}
                      >
                        Удалить операцию
                      </button>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      ))}

      {page.data && page.data.total > page.data.items.length && (
        <p className="hint">
          Показаны первые {page.data.items.length} из {page.data.total}
        </p>
      )}
    </div>
  )
}
