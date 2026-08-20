import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../api'
import ErrorNote from '../components/ErrorNote'
import PeriodPicker from '../components/PeriodPicker'
import { formatMoney } from '../format'
import { haptic } from '../telegram'
import type { Period } from '../types'

interface Props {
  currentUserId: string
}

export default function StatsPage({ currentUserId }: Props) {
  const [period, setPeriod] = useState<Period>('month')
  const [personId, setPersonId] = useState<string | null>(null)

  const users = useQuery({ queryKey: ['users'], queryFn: api.users })
  const summary = useQuery({
    queryKey: ['summary', period, personId],
    queryFn: () => api.summary(period, { personId }),
  })

  const data = summary.data
  const selectPerson = (id: string | null) => {
    haptic()
    setPersonId(id)
  }

  return (
    <div className="page">
      <PeriodPicker value={period} onChange={setPeriod} />

      {/* Отчёт по одному человеку: те же цифры, но только по его тратам. Его —
          значит записанным на его счёт, кто бы их ни вносил */}
      {(users.data?.length ?? 0) > 1 && (
        <div className="chips">
          <button
            type="button"
            className="chip"
            data-active={!personId}
            onClick={() => selectPerson(null)}
          >
            Вместе
          </button>
          {(users.data ?? []).map((user) => (
            <button
              key={user.id}
              type="button"
              className="chip"
              data-active={personId === user.id}
              onClick={() => selectPerson(personId === user.id ? null : user.id)}
            >
              {user.id === currentUserId ? 'Я' : user.display_name}
            </button>
          ))}
        </div>
      )}

      <ErrorNote error={summary.error} />

      <div className="card">
        <div className="totals">
          <div>
            <span>Расходы</span>
            <b>{formatMoney(data?.expense_minor ?? 0)}</b>
          </div>
          <div>
            <span>Доходы</span>
            <b>{formatMoney(data?.income_minor ?? 0)}</b>
          </div>
          <div>
            <span>Сальдо</span>
            <b style={{ color: (data?.net_minor ?? 0) < 0 ? 'var(--danger)' : 'var(--success)' }}>
              {formatMoney(data?.net_minor ?? 0, { sign: (data?.net_minor ?? 0) > 0 })}
            </b>
          </div>
        </div>
      </div>

      {data && data.by_category.length > 0 && (
        <>
          <p className="section-title">Куда ушли деньги</p>
          <div className="card card--tight">
            {data.by_category.map((item) => (
              <div
                className={`row${item.parent_id ? ' row--nested' : ''}`}
                key={item.category_id ?? 'none'}
              >
                <div className={`row__icon${item.parent_id ? ' row__icon--small' : ''}`}>
                  {item.icon || '•'}
                </div>
                <div className="row__body">
                  <div className="row__title">{item.name}</div>
                  {/* Полоса нагляднее процента: соотношение видно, не читая цифр */}
                  <div className="bar">
                    <i style={{ width: `${Math.max(2, Math.round(item.share * 100))}%` }} />
                  </div>
                </div>
                <div className="row__amount">
                  {formatMoney(item.amount_minor)}
                  <div className="row__sub" style={{ textAlign: 'right' }}>
                    {Math.round(item.share * 100)}%
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {data && !personId && data.by_person.length > 1 && (
        <>
          <p className="section-title">Кто сколько потратил</p>
          <div className="card card--tight">
            {data.by_person.map((item) => (
              <div className="row row--tappable" key={item.user_id}>
                <div className="row__icon">👤</div>
                <div className="row__body">
                  <div className="row__title">
                    {item.name}
                    {item.user_id === currentUserId ? ' (вы)' : ''}
                  </div>
                </div>
                <button
                  type="button"
                  className="btn btn--ghost btn--slim"
                  onClick={() => selectPerson(item.user_id)}
                >
                  {formatMoney(item.amount_minor)}
                </button>
              </div>
            ))}
          </div>
          <p className="hint">
            Трата считается за тем, с чьего счёта записана, — даже если внёс её кто-то другой.
            Кто кому должен по общему счёту — на вкладке «Ещё».
          </p>
        </>
      )}

      {data && data.count === 0 && (
        <p className="hint" style={{ textAlign: 'center' }}>
          За этот период данных нет
        </p>
      )}
    </div>
  )
}
